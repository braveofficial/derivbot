# master_bulk_trader.py
import streamlit as st
import websocket
import json
import threading
import time
from datetime import datetime

st.set_page_config(page_title="MASTER BULK TRADER", layout="wide")

# ---------------- THEME SWITCH ---------------- #
def apply_theme(theme: str, running: bool):
    # Dynamic background: Green if running, Blue if stopped
    bg_color = "#064635" if running else "#002B5B"

    if theme == "Dark":
        st.markdown(f"""
            <style>
                body, .stApp {{
                    background-color: {bg_color};
                    color: #f5f5f5;
                    font-family: 'Segoe UI', sans-serif;
                }}
                table, th, td {{
                    background-color: #1e1e1e !important;
                    color: #f5f5f5 !important;
                }}
                .stButton button {{
                    background-color: #333333;
                    color: #ffffff;
                    border-radius: 8px;
                    font-weight: bold;
                }}
            </style>
        """, unsafe_allow_html=True)
    else:  # Light mode
        st.markdown(f"""
            <style>
                body, .stApp {{
                    background-color: {bg_color};
                    color: #000000;
                    font-family: 'Segoe UI', sans-serif;
                }}
                table, th, td {{
                    background-color: #ffffff !important;
                    color: #000000 !important;
                }}
                .stButton button {{
                    background-color: #e0e0e0;
                    color: #000000;
                    border-radius: 8px;
                    font-weight: bold;
                }}
            </style>
        """, unsafe_allow_html=True)

# ---------------- SESSION STATE ---------------- #
if "running" not in st.session_state:
    st.session_state.running = False
if "balance" not in st.session_state:
    st.session_state.balance = 0.0
if "trades" not in st.session_state:
    st.session_state.trades = []

# ---------------- DERIV WEBSOCKET ---------------- #
API_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

def authorize(ws, token):
    ws.send(json.dumps({"authorize": token}))

def subscribe_balance(ws):
    ws.send(json.dumps({"balance": 1, "subscribe": 1}))

def send_proposal(ws, symbol, contract_type, stake, target_digit=None):
    proposal = {
        "proposal": 1,
        "amount": stake,
        "basis": "stake",
        "contract_type": contract_type,
        "currency": "USD",
        "duration": 1,
        "duration_unit": "t",
        "symbol": symbol
    }
    if target_digit is not None:  # Only add barrier if required
        proposal["barrier"] = str(target_digit)
    ws.send(json.dumps(proposal))

def buy_contract(ws, proposal_id, symbol, contract_type, stake):
    ws.send(json.dumps({"buy": proposal_id, "price": 10000}))
    st.session_state.trades.insert(0, {
        "time": datetime.now().strftime("%H:%M:%S"),
        "symbol": symbol,
        "contract": contract_type,
        "stake": stake,
        "status": "Open",
        "payout": None
    })

def ws_worker(token, symbol, contract_type, stake, target_digit):
    def on_open(ws):
        authorize(ws, token)

    def on_message(ws, message):
        data = json.loads(message)

        if "error" in data:
            st.session_state.running = False
            return

        if data.get("msg_type") == "authorize":
            subscribe_balance(ws)
            send_proposal(ws, symbol, contract_type, stake, target_digit)

        if data.get("msg_type") == "balance":
            st.session_state.balance = data["balance"]["balance"]

        if data.get("msg_type") == "proposal":
            proposal_id = data["proposal"]["id"]
            buy_contract(ws, proposal_id, symbol, contract_type, stake)

        if data.get("msg_type") == "proposal_open_contract":
            poc = data["proposal_open_contract"]
            if poc.get("is_sold", False):
                pnl = poc.get("profit", 0.0)
                status = "Won ✅" if pnl > 0 else "Lost ❌"
                for trade in st.session_state.trades:
                    if trade["status"] == "Open":
                        trade["status"] = status
                        trade["payout"] = pnl
                        break

    def on_error(ws, error):
        st.session_state.running = False

    websocket.enableTrace(False)
    ws = websocket.WebSocketApp(
        API_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error
    )
    ws.run_forever()

def run_bot(token, symbol, contract_type, stake, target_digit, continuous):
    st.session_state.running = True
    while st.session_state.running:
        threads = []
        for _ in range(10):
            t = threading.Thread(target=ws_worker, args=(token, symbol, contract_type, stake, target_digit))
            threads.append(t)
            t.start()
            time.sleep(0.3)
        for t in threads:
            t.join()
        if not continuous:
            break

# ---------------- UI ---------------- #
st.title("🤖 MASTER BULK TRADER")

# Theme toggle
col1, col2 = st.columns([4,1])
with col2:
    theme = st.radio("Theme", ["Light", "Dark"], horizontal=True, label_visibility="collapsed")
apply_theme(theme, st.session_state.running)

# API & Controls
st.subheader("Controls")
api_token = st.text_input("Enter your Deriv API Token", type="password")

symbols = {
    "Volatility 10": "R_10",
    "Volatility 25": "R_25",
    "Volatility 50": "R_50",
    "Volatility 75": "R_75",
    "Volatility 100": "R_100",
    "Volatility 10 (1s)": "R_10_1S",
    "Volatility 15 (1s)": "R_15_1S",
    "Volatility 25 (1s)": "R_25_1S",
    "Volatility 50 (1s)": "R_50_1S",
    "Volatility 75 (1s)": "R_75_1S",
    "Volatility 90 (1s)": "R_90_1S",
    "Volatility 100 (1s)": "R_100_1S"
}
symbol = st.selectbox("Market", list(symbols.keys()))

# Contract type + target digit in same row
col1, col2 = st.columns([2,1])
with col1:
    contract_type = st.selectbox(
        "Contract Type", 
        ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER", "DIGITODD", "DIGITEVEN", "RISE", "FALL"]
    )
with col2:
    target_digit = None
    if contract_type in ["DIGITMATCH", "DIGITDIFF", "DIGITOVER", "DIGITUNDER"]:
        target_digit = st.number_input("Digit", min_value=0, max_value=9, step=1)

stake = st.number_input("Stake Amount (USD)", min_value=1.0, value=1.0)
continuous = st.checkbox("Continuous Trading (Loop batches)")

# Status
st.subheader("Status")
st.metric("Account Balance", f"${st.session_state.balance:,.2f}")

# Trades table
st.subheader("Recent Trades")
if len(st.session_state.trades) > 0:
    st.table(st.session_state.trades[:10])
else:
    st.write("No trades yet...")

# Start / Stop
col1, col2 = st.columns(2)
with col1:
    if st.button("▶️ Start"):
        if not api_token:
            st.error("Please enter API token")
        else:
            threading.Thread(
                target=run_bot, 
                args=(api_token, symbols[symbol], contract_type, stake, target_digit, continuous)
            ).start()
with col2:
    if st.button("⏹️ Stop"):
        st.session_state.running = False
