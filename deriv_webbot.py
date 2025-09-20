# deriv_webbot.py
# Streamlit web dashboard for Deriv bulk trades (users enter their own API token)
# NOTE: Use demo tokens for testing.

import streamlit as st
import websocket
import json
import time
import threading

st.set_page_config(page_title="Deriv Bulk WebBot", layout="wide")

# --------------------------
# Deriv bot (background)
# --------------------------
class DerivBot:
    def __init__(self, api_token, market, stake, digit, bulk_trades=10, settle_sleep=0.5):
        self.api_token = api_token
        self.market = market
        self.stake = float(stake)
        self.digit = int(digit)
        self.bulk_trades = int(bulk_trades)
        self.ws = None
        self.running = False
        self.logs = []
        self.wins = 0
        self.losses = 0
        self.profit = 0.0
        self.currency = "USD"
        self.settle_sleep = settle_sleep

    def log(self, msg):
        ts = time.strftime("[%H:%M:%S]")
        entry = f"{ts} {msg}"
        self.logs.append(entry)

    def connect_and_auth(self):
        try:
            # synchronous WebSocket connection in a background thread
            self.ws = websocket.WebSocket()
            self.ws.connect("wss://ws.derivws.com/websockets/v3?app_id=1089", timeout=10)
            self.ws.send(json.dumps({"authorize": self.api_token}))
            resp = json.loads(self.ws.recv())
            if "error" in resp:
                self.log(f"Authorization error: {resp['error']}")
                return False
            auth = resp.get("authorize", {})
            balance = auth.get("balance", None)
            self.currency = auth.get("currency", "USD")
            if balance is not None:
                self.log(f"Connected. Balance: {balance} {self.currency}")
            else:
                self.log("Connected (no balance in response).")
            return True
        except Exception as e:
            self.log(f"Connection/auth error: {e}")
            return False

    def place_single_trade(self, idx):
        # Build buy request using proposal flow (safe approach would request proposal then buy)
        try:
            # Request proposal
            proposal_req = {
                "proposal": 1,
                "amount": self.stake,
                "basis": "stake",
                "symbol": self.market,
                "contract_type": "DIGITMATCH",
                "currency": self.currency,
                "duration": 1,
                "duration_unit": "t"
            }
            self.ws.send(json.dumps(proposal_req))
            # listen for proposal response
            start = time.time()
            proposal = None
            while time.time() - start < 8:
                msg = json.loads(self.ws.recv())
                if "proposal" in msg:
                    proposal = msg["proposal"]
                    break
                if "error" in msg:
                    self.log(f"Proposal error: {msg['error']}")
                    return 0.0
            if not proposal:
                self.log("No proposal received, skipping trade.")
                return 0.0

            proposal_id = proposal.get("id") or proposal.get("proposal_id") or proposal.get("proposal")
            # Buy using proposal id
            buy_req = {"buy": proposal_id}
            self.ws.send(json.dumps(buy_req))

            # wait for buy or contract messages
            start = time.time()
            buy_resp = None
            contract_id = None
            while time.time() - start < 8:
                msg = json.loads(self.ws.recv())
                # immediate buy response
                if "buy" in msg:
                    buy_resp = msg["buy"]
                    contract_id = buy_resp.get("contract_id") or buy_resp.get("contract")
                    break
                if "error" in msg:
                    self.log(f"Buy error: {msg['error']}")
                    return 0.0

            # Wait short time for settlement-ish messages (real settlement may take longer)
            # In many cases settlement messages appear separately; here we poll a bit.
            time.sleep(self.settle_sleep)
            profit_val = None
            # Attempt to read any pending messages (non-blocking-ish)
            try:
                while True:
                    msg = json.loads(self.ws.recv())
                    if "proposal_open_contract" in msg:
                        poc = msg["proposal_open_contract"]
                        if contract_id and poc.get("contract_id") == contract_id:
                            # if sold
                            if poc.get("is_sold") or poc.get("status") == "sold":
                                buy_price = float(poc.get("buy_price", 0) or 0)
                                sell_price = float(poc.get("sell_price", 0) or 0)
                                profit_val = sell_price - buy_price
                                break
                    if "contract" in msg:
                        c = msg["contract"]
                        if contract_id and (c.get("contract_id") == contract_id or c.get("id") == contract_id):
                            buy_price = float(c.get("buy_price", 0) or 0)
                            sell_price = float(c.get("sell_price", 0) or 0)
                            profit_val = sell_price - buy_price
                            break
                    if "sell" in msg:
                        s = msg["sell"]
                        profit_val = float(s.get("profit", 0) or 0)
                        break
            except Exception:
                # no more messages immediately available
                pass

            # If no profit_val found, treat unknown as 0.0 (you can change policy)
            if profit_val is None:
                profit_val = 0.0

            # Update stats
            if profit_val > 0:
                self.wins += 1
            elif profit_val < 0:
                self.losses += 1
            self.profit += float(profit_val)
            self.log(f"Trade #{idx} result: {profit_val:+.2f} {self.currency}")
            return float(profit_val)

        except Exception as e:
            self.log(f"Trade #{idx} exception: {e}")
            return 0.0

    def start(self):
        self.running = True
        self.logs = []
        self.wins = 0
        self.losses = 0
        self.profit = 0.0

        ok = self.connect_and_auth()
        if not ok:
            self.running = False
            return

        # Fire trades sequentially to keep API happy (if you want true simultaneous, spawn threads here)
        for i in range(1, self.bulk_trades + 1):
            if not self.running:
                self.log("Stopped by user.")
                break
            self.log(f"Placing trade #{i} on {self.market} stake={self.stake}")
            self.place_single_trade(i)
            time.sleep(0.2)

        # close ws
        try:
            if self.ws:
                self.ws.close()
        except:
            pass
        self.running = False
        self.log("Batch finished.")

    def stop(self):
        self.running = False
        try:
            if self.ws:
                self.ws.close()
        except:
            pass
        self.log("Bot stopped by user.")

# --------------------------
# Streamlit UI
# --------------------------
st.title("📊 Deriv Bulk WebBot")

with st.sidebar:
    st.markdown("## Controls")
    api_token = st.text_input("API Token", type="password")
    market = st.selectbox("Market", ["R_10", "R_25", "R_50", "R_75", "R_100"])
    stake = st.number_input("Stake", min_value=0.35, value=1.0, step=0.1)
    digit = st.number_input("Digit (for digit contracts)", min_value=0, max_value=9, value=5, step=1)
    bulk_trades = st.number_input("Bulk trades (runs)", min_value=1, value=10, step=1)
    settle_sleep = st.number_input("settle sleep (s)", min_value=0.0, value=0.5, step=0.1)
    st.markdown("---")
    start_btn = st.button("▶️ Start Bot")
    stop_btn = st.button("⏹️ Stop Bot")

# initialize bot in session_state
if "bot" not in st.session_state:
    st.session_state.bot = None

# Start/Stop logic (non-blocking)
if start_btn:
    if not api_token:
        st.warning("Enter API token (demo token while testing).")
    else:
        st.session_state.bot = DerivBot(api_token, market, stake, digit, bulk_trades, settle_sleep)
        t = threading.Thread(target=st.session_state.bot.start, daemon=True)
        t.start()
        st.success("Bot started (running in background).")

if stop_btn and st.session_state.bot:
    st.session_state.bot.stop()
    st.success("Stop signal sent.")

# Main dashboard: stats and journal
col1, col2 = st.columns([2,3])

with col1:
    st.subheader("Stats")
    if st.session_state.bot:
        st.metric("Wins", st.session_state.bot.wins)
        st.metric("Losses", st.session_state.bot.losses)
        st.metric("Profit", f"{st.session_state.bot.profit:.2f} {st.session_state.bot.currency}")
        st.write("Running:", st.session_state.bot.running)
    else:
        st.write("Bot not started yet.")

with col2:
    st.subheader("Journal (latest messages)")
    if st.session_state.bot:
        # show last 200 lines
        logs = st.session_state.bot.logs[-200:]
        for line in logs[::-1]:
            # simple color by keyword
            if "result" in line and "+" in line:
                st.markdown(f"<span style='color:green'>{line}</span>", unsafe_allow_html=True)
            elif "result" in line and "-" in line:
                st.markdown(f"<span style='color:red'>{line}</span>", unsafe_allow_html=True)
            elif "error" in line or "exception" in line or "stopped" in line:
                st.markdown(f"<span style='color:orange'>{line}</span>", unsafe_allow_html=True)
            else:
                st.write(line)
    else:
        st.write("No logs yet. Start the bot to see activity.")
