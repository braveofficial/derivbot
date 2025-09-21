# deriv_webbot.py
import streamlit as st
import websocket
import json
import threading
import time

st.set_page_config(page_title="Deriv Bulk Bot", layout="wide")

# ---------------- THEME SWITCH ---------------- #
def apply_theme(theme: str):
    if theme == "Dark":
        st.markdown("""
            <style>
                body, .stApp { background-color: #1e1e1e; color: #f5f5f5; }
                table, th, td { background-color: #2d2d2d !important; color: #f5f5f5 !important; }
                .stButton button { background-color: #333333; color: #f5f5f5; }
            </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
            <style>
                body, .stApp { background-color: #ffffff; color: #000000; }
                table, th, td { background-color: #f5f5f5 !important; color: #000000 !important; }
                .stButton button { background-color: #f0f0f0; color: #000000; }
            </style>
        """, unsafe_allow_html=True)

# ---------------- SESSION STATE ---------------- #
if "running" not in st.session_state:
    st.session_state.running = False
if "balance" not in st.session_state:
    st.session_state.balance = 0.0

# ---------------- DERIV WEBSOCKET ---------------- #
API_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

def authorize(ws, token):
    ws.send(json.dumps({"authorize": token}))

def subscribe_balance(ws):
    ws.send(json.dumps({"balance": 1, "subscribe": 1}))

def send_proposal(ws, symbol, contract_type, stake):
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
    ws.send(json.dumps(proposal))

def buy_contract(ws, proposal_id):
    ws.send(json.dumps({"buy": proposal_id, "price": 10000}))

def ws_worker(token, symbol, contract_type, stake):
    def on_open(ws):
        authorize(ws, token)

    def on_message(ws, message):
        data = json.loads(message)

        if "error" in data:
            st.session_state.running = False
            return

        if data.get("msg_type") == "authorize":
            subscribe_balance(ws)

        if data.get("msg_type") == "balance":
            st.session_state.balance = data["balance"]["balance"]

        if data.get("msg_type") == "proposal":
            proposal_id = data["proposal"]["id"]
            buy_contract(ws, proposal_id)

        if data.get("msg_type") == "buy":
            pass  # Contract bought

        if data.get("msg_type") == "proposal_open_contract":
            if data["proposal_open_contract"].get("is_sold", False):
                pass  # Trade completed

    def on_error(ws, error):
        st.session_state.running = False

    def on_close(ws, close_status_code, close_msg):
        pass

    websocket.enableTrace(False)
    ws = websocket.WebSocketApp(
        API_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

def run_bot(token, symbol, contract_type, stake, continuous):
    st.session_state.running = True
    while st.session_state.running:
        threads = []
        for _ in range(10):  # 10 trades per batch
            t = threading.Thread(target=ws_worker, args=(token, symbol, contract_type, stake))
            threads.append(t)
            t.start()
            time.sleep(0.3)  # spacing between trades

        for t in threads:
            t.join()

        if not continuous:
            break

# ---------------- UI ---------------- #
st.title("📈 Deriv Bulk Bot")

# Theme toggle
col1, col2 = st.columns([4,1])
with col2:
    theme = st.radio("Theme", ["Light", "Dark"], horizontal=True, label_visibility="collapsed")
    apply_theme(theme)

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
contract_type = st.selectbox("Contract Type", ["DIGITMATCH", "DIGITDIFF", "DIGITODD", "DIGITEVEN", "DIGITOVER", "DIGITUNDER", "RISE", "FALL"])
stake = st.number_input("Stake Amount (USD)", min_value=1.0, value=1.0)
continuous = st.checkbox("Continuous Trading (Loop batches)")

# Status
st.subheader("Status")
st.metric("Account Balance", f"${st.session_state.balance:,.2f}")

# Start / Stop
col1, col2 = st.columns(2)
with col1:
    if st.button("▶️ Start"):
        if not api_token:
            st.error("Please enter API token")
        else:
            threading.Thread(target=run_bot, args=(api_token, symbols[symbol], contract_type, stake, continuous)).start()
with col2:
    if st.button("⏹️ Stop"):
        st.session_state.running = False
