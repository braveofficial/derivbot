import streamlit as st
import websocket
import json
import threading
import time
from urllib.parse import urlparse, parse_qs

# --- SETTINGS ---
APP_ID = 102924  # your deriv app id
MARKET = "R_50"
TRADE_TYPE = "DIGITMATCH"
SYMBOL = "R_50"

st.set_page_config(page_title="MASTER BULK TRADER", layout="wide")

# --- SESSION STATE ---
if "api_token" not in st.session_state:
    st.session_state.api_token = None
if "running" not in st.session_state:
    st.session_state.running = False
if "balance" not in st.session_state:
    st.session_state.balance = 0.0
if "trades" not in st.session_state:
    st.session_state.trades = []
if "bulk_runs" not in st.session_state:
    st.session_state.bulk_runs = 5  # default 5 trades

# --- DASHBOARD ---
st.title("📈 MASTER BULK TRADER")

# --- ACCOUNT CONNECTION ---
st.subheader("Account Connection")
query_params = st.experimental_get_query_params()

# Handle OAuth redirect
if "token" in query_params:
    st.session_state.api_token = query_params["token"][0]

# Show login / logout
if st.session_state.api_token:
    st.success("✅ Connected to Deriv successfully!")
    st.info("🔐 You are connected to your Deriv account.")
    if st.button("🚪 Disconnect"):
        st.session_state.api_token = None
        st.session_state.running = False
        st.session_state.balance = 0.0
        st.session_state.trades = []
        st.experimental_set_query_params()  # Clear token
        st.warning("You have been logged out.")
else:
    # Nothing on dashboard until login
    oauth_url = (
        f"https://oauth.deriv.com/oauth2/authorize?"
        f"app_id={APP_ID}&scope=read,trade&redirect_uri=https://master-bulk-trader.streamlit.app/"
    )
    st.markdown(f"[🔗 Connect with Deriv]({oauth_url})", unsafe_allow_html=True)
    st.stop()  # stop app here until login

# --- BOT LOGIC ---
def run_bot(token, bulk_runs):
    url = "wss://ws.derivws.com/websockets/v3?app_id=" + str(APP_ID)
    ws = websocket.WebSocket()

    try:
        ws.connect(url)
        ws.send(json.dumps({"authorize": token}))
        auth_response = ws.recv()
        auth_data = json.loads(auth_response)
        if "error" in auth_data:
            st.error("❌ Authorization failed. Check app settings.")
            return

        # Fetch balance
        ws.send(json.dumps({"balance": 1}))
        balance_data = json.loads(ws.recv())
        st.session_state.balance = balance_data["balance"]["balance"]

        # Run bulk trades
        for i in range(bulk_runs):
            if not st.session_state.running:
                break
            proposal = {
                "buy": 1,
                "parameters": {
                    "amount": 1,
                    "basis": "stake",
                    "contract_type": TRADE_TYPE,
                    "currency": "USD",
                    "duration": 1,
                    "duration_unit": "t",
                    "symbol": SYMBOL,
                    "barrier": "5"
                },
                "price": 1
            }
            ws.send(json.dumps(proposal))
            result = json.loads(ws.recv())
            st.session_state.trades.append(result)
            time.sleep(1)

        ws.close()

    except Exception as e:
        st.error(f"⚠️ Error: {e}")

# --- DASHBOARD CONTROLS ---
st.subheader("Trading Controls")
st.session_state.bulk_runs = st.slider("Number of bulk trades", 1, 10, st.session_state.bulk_runs)

if not st.session_state.running:
    if st.button("▶️ Start Bulk Trades"):
        st.session_state.running = True
        threading.Thread(target=run_bot, args=(st.session_state.api_token, st.session_state.bulk_runs), daemon=True).start()
else:
    if st.button("⏹️ Stop"):
        st.session_state.running = False

# --- STATUS ---
st.subheader("Status")
st.metric("Account Balance", f"{st.session_state.balance:.2f} USD")
st.write("Executed Trades:", len(st.session_state.trades))
