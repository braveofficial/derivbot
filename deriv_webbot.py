# deriv_webbot.py
# Streamlit DBot-style bulk trader (10 trades per batch), Light/Dark themes, Volatility markets incl. (1s)
#
# Requirements:
#   pip install streamlit websocket-client

import streamlit as st
import websocket
import json
import threading
import time
import datetime
from functools import partial

st.set_page_config(page_title="Deriv Bulk WebBot", layout="wide")

# -------------------------
# Helper / Initial state
# -------------------------
if "running" not in st.session_state:
    st.session_state.running = False
if "transactions" not in st.session_state:
    st.session_state.transactions = []   # list of dicts per trade
if "stats" not in st.session_state:
    st.session_state.stats = {"stake_total": 0.0, "payout_total": 0.0, "wins": 0, "losses": 0, "profit": 0.0}
if "lock" not in st.session_state:
    st.session_state.lock = threading.Lock()
if "theme" not in st.session_state:
    st.session_state.theme = "light"  # or "dark"

# -------------------------
# Markets (labels -> default symbol)
# Note: If Deriv uses different exact symbol codes for (1s) variants in your account,
# you can use the "Override symbol" field to input the correct symbol string.
# -------------------------
MARKET_OPTIONS = [
    ("Volatility 10 Index", "R_10"),
    ("Volatility 25 Index", "R_25"),
    ("Volatility 50 Index", "R_50"),
    ("Volatility 75 Index", "R_75"),
    ("Volatility 100 Index", "R_100"),
    ("Volatility 10 (1s) Index", "R_10_1S"),
    ("Volatility 15 (1s) Index", "R_15_1S"),
    ("Volatility 25 (1s) Index", "R_25_1S"),
    ("Volatility 50 (1s) Index", "R_50_1S"),
    ("Volatility 75 (1s) Index", "R_75_1S"),
    ("Volatility 90 (1s) Index", "R_90_1S"),
    ("Volatility 100 (1s) Index", "R_100_1S"),
]

# -------------------------
# Styling for themes
# -------------------------
LIGHT_CSS = """
<style>
body {background-color: #f8f9fb; color: #111;}
.card { background:#ffffff; border-radius:8px; padding:8px; box-shadow: 0 2px 6px rgba(0,0,0,0.06);}
.win { color: #0a8f2a; font-weight:600; }
.loss { color: #c42a2a; font-weight:600; }
.info { color: #555555; }
.header { font-size:18px; font-weight:700; }
.small { font-size:12px; color:#666; }
</style>
"""
DARK_CSS = """
<style>
body {background-color: #0f1720; color: #e6eef6;}
.card { background:#0b1220; border-radius:8px; padding:8px; box-shadow: 0 2px 10px rgba(0,0,0,0.6);}
.win { color: #5eead4; font-weight:600; }
.loss { color: #fb7185; font-weight:600; }
.info { color: #94a3b8; }
.header { font-size:18px; font-weight:700; }
.small { font-size:12px; color:#94a3b8; }
</style>
"""

def apply_theme():
    if st.session_state.theme == "light":
        st.markdown(LIGHT_CSS, unsafe_allow_html=True)
    else:
        st.markdown(DARK_CSS, unsafe_allow_html=True)

apply_theme()

# -------------------------
# Utilities
# -------------------------
def now_ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def add_transaction(tr):
    with st.session_state.lock:
        st.session_state.transactions.append(tr)
        # update stats
        st.session_state.stats["stake_total"] += float(tr.get("stake",0) or 0)
        st.session_state.stats["payout_total"] += float(tr.get("payout",0) or 0)
        pl = float(tr.get("pl",0) or 0)
        st.session_state.stats["profit"] += pl
        if pl > 0:
            st.session_state.stats["wins"] += 1
        elif pl < 0:
            st.session_state.stats["losses"] += 1

# -------------------------
# Trade worker (one websocket per trade)
# -------------------------
def trade_thread(api_token, symbol, contract_type, stake, digit, trade_no, timeout=20):
    """
    Open WS, authorize, request proposal with barrier when needed, buy, wait for settlement (within timeout)
    Append a transaction dict using add_transaction().
    """
    entry = "-"
    exit_ = "-"
    payout = 0.0
    pl = 0.0
    status = "Unknown"

    ws = None
    try:
        ws = websocket.WebSocket()
        ws.settimeout(8)
        ws.connect("wss://ws.derivws.com/websockets/v3?app_id=1089")
        # authorize
        ws.send(json.dumps({"authorize": api_token}))
        auth_resp = json.loads(ws.recv())
        if "error" in auth_resp:
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_,
                "stake": stake, "payout": payout, "pl": pl, "status": f"AuthError: {auth_resp['error']}"
            })
            return

        # Build proposal
        proposal = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "symbol": symbol,
            "contract_type": contract_type,
            "currency": "USD",
            "duration": 1,
            "duration_unit": "t"
        }
        if contract_type in ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER"]:
            proposal["barrier"] = str(digit)

        # send proposal
        ws.send(json.dumps(proposal))

        # wait for proposal response
        proposal_resp = None
        start = time.time()
        while time.time() - start < 6:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                continue
            if "proposal" in msg:
                proposal_resp = msg["proposal"]
                break
            if "error" in msg:
                proposal_resp = {"error": msg["error"]}
                break

        if not proposal_resp or "error" in proposal_resp:
            err = proposal_resp.get("error") if proposal_resp else {"message":"No proposal"}
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_,
                "stake": stake, "payout": payout, "pl": pl, "status": f"ProposalError: {err}"
            })
            return

        proposal_id = proposal_resp.get("id") or proposal_resp.get("proposal") or proposal_resp.get("proposal_id")

        # buy
        buy_req = {"buy": proposal_id}
        ws.send(json.dumps(buy_req))

        buy_resp = None
        start = time.time()
        contract_id = None
        while time.time() - start < 6:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                continue
            if "buy" in msg:
                buy_resp = msg["buy"]
                contract_id = buy_resp.get("contract_id") or buy_resp.get("contract")
                # buy_resp can contain 'buy_price' but settlement comes later
                break
            if "error" in msg:
                buy_resp = {"error": msg["error"]}
                break

        if not buy_resp or "error" in buy_resp:
            err = buy_resp.get("error") if buy_resp else {"message":"No buy response"}
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_,
                "stake": stake, "payout": payout, "pl": pl, "status": f"BuyError: {err}"
            })
            return

        # wait for settlement (listen until we find proposal_open_contract or contract message for contract_id)
        start = time.time()
        while time.time() - start < timeout:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                continue
            if "proposal_open_contract" in msg:
                poc = msg["proposal_open_contract"]
                if contract_id and poc.get("contract_id") == contract_id:
                    buy_price = float(poc.get("buy_price", 0) or 0)
                    if poc.get("is_sold") or poc.get("status") == "sold":
                        sell_price = float(poc.get("sell_price", 0) or 0)
                        payout = sell_price
                        pl = payout - buy_price
                        entry = poc.get("entry_tick", "-")
                        exit_ = poc.get("exit_tick", "-")
                        status = "Win" if pl > 0 else ("Loss" if pl < 0 else "Even")
                        break
            if "contract" in msg:
                c = msg["contract"]
                if contract_id and (c.get("contract_id") == contract_id or c.get("id") == contract_id):
                    buy_price = float(c.get("buy_price", 0) or 0)
                    sell_price = float(c.get("sell_price", 0) or 0)
                    payout = sell_price
                    pl = payout - buy_price
                    entry = c.get("entry_tick", "-")
                    exit_ = c.get("exit_tick", "-")
                    status = "Win" if pl > 0 else ("Loss" if pl < 0 else "Even")
                    break
            if "sell" in msg:
                s = msg["sell"]
                payout = float(s.get("sell_price", s.get("profit", 0)) or 0)
                pl = payout
                status = "Win" if pl > 0 else ("Loss" if pl < 0 else "Even")
                break

        # fallback if not settled in time: set status Unknown and pl 0
        if status == "Unknown":
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_,
                "stake": stake, "payout": payout, "pl": pl, "status": "NoSettlement"
            })
            return

        # final transaction record
        add_transaction({
            "trade_no": trade_no, "entry": entry, "exit": exit_,
            "stake": stake, "payout": payout, "pl": pl, "status": status
        })

    except Exception as e:
        add_transaction({
            "trade_no": trade_no, "entry": entry, "exit": exit_,
            "stake": stake, "payout": payout, "pl": pl, "status": f"Exception: {e}"
        })
    finally:
        try:
            if ws:
                ws.close()
        except:
            pass

# -------------------------
# Bulk batch runner (10 trades) - spawns 10 threads
# -------------------------
def run_bulk_batch(api_token, symbol, contract_type, stake, digit):
    threads = []
    for i in range(1, 11):  # 10 trades per batch
        t = threading.Thread(target=trade_thread, args=(api_token, symbol, contract_type, stake, digit, i), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.02)  # tiny spacing to avoid simultaneous connect spikes

    # wait for all 10 to finish (with reasonable timeout)
    for t in threads:
        t.join(timeout=40)

# -------------------------
# Long-running loop thread: repeat batches until stopped
# -------------------------
def continuous_runner(api_token, symbol, contract_type, stake, digit):
    batch_no = 0
    while st.session_state.running:
        batch_no += 1
        timestamp = now_ts()
        add_transaction({"trade_no": f"Batch {batch_no}", "entry":"-", "exit":"-", "stake":0, "payout":0, "pl":0, "status": f"Starting batch {batch_no} @ {timestamp}"})
        run_bulk_batch(api_token, symbol, contract_type, stake, digit)
        # slight pause between batches
        time.sleep(0.8)
    add_transaction({"trade_no":"System", "entry":"-","exit":"-","stake":0,"payout":0,"pl":0,"status":"Stopped continuous runner"})

# -------------------------
# UI - 3 column DBot-style layout
# -------------------------
def main_ui():
    # header with theme toggle
    header_col1, header_col2 = st.columns([6,1])
    with header_col1:
        st.title("📊 Deriv Bulk WebBot - DBot Style (Bulk 10)")
    with header_col2:
        theme_choice = st.radio("Theme", ("Light", "Dark"), index=0 if st.session_state.theme=="light" else 1, horizontal=True)
        if theme_choice.lower() != st.session_state.theme:
            st.session_state.theme = theme_choice.lower()
            # reapply theme (insert CSS)
            apply_theme()

    col_left, col_center, col_right = st.columns([1,1.2,1.5])

    # LEFT: Controls
    with col_left:
        st.subheader("⚙️ Controls")
        api_token = st.text_input("🔑 API Token (paste your token)", type="password")
        market_label = st.selectbox("📈 Volatility Market", [m[0] for m in MARKET_OPTIONS])
        default_symbol = dict(MARKET_OPTIONS)[market_label]
        custom_symbol = st.text_input("Symbol override (optional)", value=default_symbol)
        contract_type = st.selectbox("Contract Type", ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER", "DIGITEVEN", "DIGITODD"])
        stake = st.number_input("Stake (USD)", min_value=0.35, value=1.0, step=0.1)
        # show digit only when needed
        if contract_type in ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER"]:
            digit = st.number_input("Digit (0-9)", min_value=0, max_value=9, value=5, step=1)
        else:
            digit = 0
        continuous = st.checkbox("Repeat batches until STOP", value=True)
        st.markdown("**Note:** Each batch fires 10 trades in parallel. Use demo API token for testing.")

        # Start / Stop
        if not st.session_state.running:
            if st.button("▶️ Start (Bulk 10)"):
                if not api_token:
                    st.error("Please enter API token")
                else:
                    # reset session records
                    with st.session_state.lock:
                        st.session_state.transactions = []
                        st.session_state.stats = {"stake_total": 0.0, "payout_total": 0.0, "wins": 0, "losses": 0, "profit": 0.0}
                        st.session_state.running = True
                    # launch runner
                    if continuous:
                        threading.Thread(target=continuous_runner, args=(api_token, custom_symbol, contract_type, stake, digit), daemon=True).start()
                    else:
                        # single batch
                        threading.Thread(target=run_bulk_batch, args=(api_token, custom_symbol, contract_type, stake, digit), daemon=True).start()
                        # do not change running flag for single batch; show running while threads active briefly
                        # set a background thread to reset running flag after a timeout
                        def reset_flag_after(wait=12):
                            st.session_state.running = True
                            time.sleep(wait)
                            st.session_state.running = False
                        threading.Thread(target=reset_flag_after, daemon=True).start()
        else:
            if st.button("⏹️ Stop"):
                st.session_state.running = False

    # CENTER: Bot Status
    with col_center:
        st.subheader("🤖 Bot Status")
        if st.session_state.running:
            st.success("Bot is running (bulk batches)...")
        else:
            st.info("Bot is stopped.")
        st.markdown("**Live Actions / Last messages**", unsafe_allow_html=True)
        # show last few messages from transactions (human-friendly)
        recent = st.session_state.transactions[-6:] if st.session_state.transactions else []
        for item in reversed(recent):
            text = f"{item.get('trade_no')} | {item.get('status')} | P/L: {item.get('pl',0):+.2f}"
            if isinstance(item.get('status'), str) and ("Win" in item.get('status') or (item.get('pl') and item.get('pl')>0)):
                st.markdown(f"<div class='card win'>{now_ts()} {text}</div>", unsafe_allow_html=True)
            elif isinstance(item.get('status'), str) and ("Loss" in item.get('status') or (item.get('pl') and item.get('pl')<0)):
                st.markdown(f"<div class='card loss'>{now_ts()} {text}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='card info'>{now_ts()} {text}</div>", unsafe_allow_html=True)

    # RIGHT: Transactions log
    with col_right:
        st.subheader("📜 Transactions (session)")
        if not st.session_state.transactions:
            st.info("No trades yet.")
        else:
            # show all trades newest first
            for t in reversed(st.session_state.transactions):
                color_class = "win" if t.get("pl",0) > 0 else ("loss" if t.get("pl",0) < 0 else "info")
                # pretty card
                st.markdown(
                    f"<div class='card'>"
                    f"<b>#{t.get('trade_no')}</b> &nbsp; <span class='{color_class}'>{t.get('status')}</span><br>"
                    f"Stake: {t.get('stake')} &nbsp; Payout: {t.get('payout')} &nbsp; P/L: <span class='{color_class}'>{t.get('pl'):+.2f}</span><br>"
                    f"Entry: {t.get('entry')} &nbsp; Exit: {t.get('exit')}"
                    f"</div>", unsafe_allow_html=True)

    # BOTTOM summary
    st.markdown("---")
    st.subheader("📊 Session Summary")
    stats = st.session_state.stats
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Stake", f"${stats['stake_total']:.2f}")
    c2.metric("Total Payout", f"${stats['payout_total']:.2f}")
    c3.metric("Wins", stats["wins"])
    c4.metric("Losses", stats["losses"])
    pl_color = "green" if stats["profit"] >= 0 else "red"
    c5.metric("Profit/Loss", f"${stats['profit']:.2f}")

# Run UI
if __name__ == "__main__":
    main_ui()
