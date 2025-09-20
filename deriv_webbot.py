# deriv_webbot.py
import streamlit as st
import websocket
import json
import threading
import time

st.set_page_config(page_title="Deriv Bot", layout="wide")

# -----------------------------
# GLOBAL STATE
# -----------------------------
if "transactions" not in st.session_state:
    st.session_state.transactions = []
if "running" not in st.session_state:
    st.session_state.running = False
if "stats" not in st.session_state:
    st.session_state.stats = {"stake": 0, "payout": 0, "wins": 0, "losses": 0, "profit": 0}

# -----------------------------
# PLACE TRADE FUNCTION
# -----------------------------
def place_trade(ws, market, stake, digit, contract_type, trade_no):
    proposal = {
        "proposal": 1,
        "amount": stake,
        "basis": "stake",
        "contract_type": contract_type,
        "currency": "USD",
        "duration": 1,
        "duration_unit": "t",
        "symbol": market,
    }

    if contract_type in ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER"]:
        proposal["barrier"] = str(digit)

    ws.send(json.dumps(proposal))
    proposal_resp = json.loads(ws.recv())

    if "error" in proposal_resp:
        return {"error": proposal_resp["error"]["message"]}

    proposal_id = proposal_resp["proposal"]["id"]

    # Buy contract
    buy_req = {"buy": proposal_id, "price": stake}
    ws.send(json.dumps(buy_req))
    buy_resp = json.loads(ws.recv())

    if "error" in buy_resp:
        return {"error": buy_resp["error"]["message"]}

    contract_id = buy_resp["buy"]["contract_id"]

    # Wait for result
    while True:
        resp = json.loads(ws.recv())
        if "proposal_open_contract" in resp:
            poc = resp["proposal_open_contract"]
            if poc["contract_id"] == contract_id and poc.get("is_sold", False):
                buy_price = float(poc["buy_price"])
                sell_price = float(poc["sell_price"])
                profit = sell_price - buy_price
                status = "Win" if profit > 0 else "Loss"

                # Save transaction
                st.session_state.transactions.append({
                    "trade_no": trade_no,
                    "entry": poc.get("entry_tick", "-"),
                    "exit": poc.get("exit_tick", "-"),
                    "stake": buy_price,
                    "payout": sell_price,
                    "pl": profit,
                    "status": status
                })

                # Update stats
                st.session_state.stats["stake"] += buy_price
                st.session_state.stats["payout"] += sell_price
                st.session_state.stats["profit"] += profit
                if status == "Win":
                    st.session_state.stats["wins"] += 1
                else:
                    st.session_state.stats["losses"] += 1
                break

    return {"success": True}

# -----------------------------
# BOT THREAD
# -----------------------------
def run_bot(api_token, market, contract_type, stake, digit, runs):
    ws = websocket.WebSocket()
    ws.connect("wss://ws.derivws.com/websockets/v3?app_id=1089")
    ws.send(json.dumps({"authorize": api_token}))
    ws.recv()  # auth response

    for i in range(1, runs + 1):
        if not st.session_state.running:
            break
        place_trade(ws, market, stake, digit, contract_type, i)
        time.sleep(1)

    ws.close()
    st.session_state.running = False

# -----------------------------
# UI LAYOUT
# -----------------------------
st.title("📊 Deriv DBot-Style Bot")

col1, col2, col3 = st.columns([1, 1.2, 1.5])

# -----------------------------
# LEFT PANEL - Controls
# -----------------------------
with col1:
    st.subheader("⚙️ Controls")
    api_token = st.text_input("API Token", type="password")
    market = st.selectbox("Market", ["R_10", "R_25", "R_50", "R_75", "R_100"])
    contract_type = st.selectbox("Contract Type", ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER", "DIGITEVEN", "DIGITODD"])
    stake = st.number_input("Stake", min_value=1.0, value=100.0, step=1.0)
    digit = st.number_input("Digit (0-9)", min_value=0, max_value=9, value=5)
    runs = st.number_input("No. of runs", min_value=1, value=10)

    if not st.session_state.running:
        if st.button("▶️ Start Bot"):
            st.session_state.running = True
            st.session_state.transactions = []
            st.session_state.stats = {"stake": 0, "payout": 0, "wins": 0, "losses": 0, "profit": 0}
            threading.Thread(target=run_bot, args=(api_token, market, contract_type, stake, digit, runs), daemon=True).start()
    else:
        if st.button("⏹️ Stop Bot"):
            st.session_state.running = False

# -----------------------------
# CENTER PANEL - Bot Status
# -----------------------------
with col2:
    st.subheader("🤖 Bot Status")
    if st.session_state.running:
        st.success("Bot is Running...")
    else:
        st.error("Bot is Stopped.")

    st.write("Live Actions:")
    if st.session_state.transactions:
        last = st.session_state.transactions[-1]
        st.write(f"Trade {last['trade_no']} → {last['status']} ({last['pl']:+.2f} USD)")
    else:
        st.write("No trades yet...")

# -----------------------------
# RIGHT PANEL - Transactions
# -----------------------------
with col3:
    st.subheader("📑 Transactions")
    if st.session_state.transactions:
        for t in st.session_state.transactions[::-1]:  # show latest first
            color = "green" if t["status"] == "Win" else "red"
            st.markdown(
                f"<div style='border:1px solid #ccc; padding:6px; margin-bottom:4px;'>"
                f"<b>#{t['trade_no']}</b> | Entry: {t['entry']} | Exit: {t['exit']}<br>"
                f"Stake: {t['stake']} | Payout: {t['payout']}<br>"
                f"<span style='color:{color};'>Result: {t['status']} ({t['pl']:+.2f} USD)</span>"
                f"</div>", unsafe_allow_html=True
            )
    else:
        st.info("No transactions yet.")

# -----------------------------
# BOTTOM SUMMARY
# -----------------------------
st.markdown("---")
st.subheader("📊 Summary (Session)")
stats = st.session_state.stats
colA, colB, colC, colD, colE = st.columns(5)
colA.metric("Total Stake", f"${stats['stake']:.2f}")
colB.metric("Total Payout", f"${stats['payout']:.2f}")
colC.metric("Wins", stats["wins"])
colD.metric("Losses", stats["losses"])
pl_color = "green" if stats["profit"] >= 0 else "red"
colE.metric("Profit/Loss", f"${stats['profit']:.2f}", delta_color="normal")
