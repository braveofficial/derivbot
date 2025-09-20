# deriv_webbot.py
# Streamlit DBot-style bulk trader with Debug Mode & theme toggle
# Requirements:
#   pip install streamlit websocket-client

import streamlit as st
import websocket
import json
import threading
import time
import datetime

st.set_page_config(page_title="Deriv Bulk WebBot (Debug)", layout="wide")

# ---------------------
# Session defaults
# ---------------------
if "running" not in st.session_state:
    st.session_state.running = False
if "transactions" not in st.session_state:
    st.session_state.transactions = []
if "stats" not in st.session_state:
    st.session_state.stats = {"stake_total": 0.0, "payout_total": 0.0, "wins": 0, "losses": 0, "profit": 0.0}
if "lock" not in st.session_state:
    st.session_state.lock = threading.Lock()
if "debug_enabled" not in st.session_state:
    st.session_state.debug_enabled = False
if "debug_messages_raw" not in st.session_state:
    st.session_state.debug_messages_raw = []  # list of raw strings
if "debug_messages_html" not in st.session_state:
    st.session_state.debug_messages_html = []  # list of formatted html lines
if "theme" not in st.session_state:
    st.session_state.theme = "light"

# ---------------------
# Markets
# ---------------------
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

# ---------------------
# Theme CSS
# ---------------------
LIGHT_CSS = """
<style>
body {background-color: #f8f9fb; color: #111;}
.card { background:#ffffff; border-radius:8px; padding:8px; box-shadow: 0 2px 6px rgba(0,0,0,0.06);}
.win { color: #0a8f2a; font-weight:600; }
.loss { color: #c42a2a; font-weight:600; }
.info { color: #444; }
.header { font-size:18px; font-weight:700; }
.small { font-size:12px; color:#666; }
.debug-box { background:#0f1720; color:#e6eef6; padding:8px; border-radius:6px; font-family:monospace; white-space:pre-wrap; overflow:auto; max-height:300px;}
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
.debug-box { background:#010414; color:#bfe6d8; padding:8px; border-radius:6px; font-family:monospace; white-space:pre-wrap; overflow:auto; max-height:300px;}
</style>
"""

def apply_theme():
    if st.session_state.theme == "light":
        st.markdown(LIGHT_CSS, unsafe_allow_html=True)
    else:
        st.markdown(DARK_CSS, unsafe_allow_html=True)

apply_theme()

# ---------------------
# Utilities
# ---------------------
def now_ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def add_transaction(tr):
    with st.session_state.lock:
        st.session_state.transactions.append(tr)
        st.session_state.stats["stake_total"] += float(tr.get("stake", 0) or 0)
        st.session_state.stats["payout_total"] += float(tr.get("payout", 0) or 0)
        pl = float(tr.get("pl", 0) or 0)
        st.session_state.stats["profit"] += pl
        if pl > 0:
            st.session_state.stats["wins"] += 1
        elif pl < 0:
            st.session_state.stats["losses"] += 1

def debug_log_raw(prefix, obj, level="info"):
    """
    prefix: arrow/string, obj: dict or string, level: 'info'|'success'|'error'
    Stores raw (text) and formatted HTML for display & download.
    """
    if not st.session_state.debug_enabled:
        return
    ts = now_ts()
    if isinstance(obj, (dict, list)):
        payload = json.dumps(obj, indent=2, ensure_ascii=False)
    else:
        payload = str(obj)
    line_raw = f"{ts} {prefix} {payload}"
    st.session_state.debug_messages_raw.append(line_raw)
    color = "#94a3b8"
    if level == "success":
        color = "#4CAF50"
    elif level == "error":
        color = "#FF5252"
    # small HTML escape for safety in the payload viewing
    html_payload = payload.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_line = f"<div style='color:{color}; font-family:monospace; padding:2px;'><b>{ts} {prefix}</b><pre style='margin:0'>{html_payload}</pre></div>"
    st.session_state.debug_messages_html.append(html_line)
    # keep debug arrays capped at e.g. 2000 lines to avoid memory explosion
    if len(st.session_state.debug_messages_raw) > 4000:
        st.session_state.debug_messages_raw = st.session_state.debug_messages_raw[-2000:]
        st.session_state.debug_messages_html = st.session_state.debug_messages_html[-2000:]

# ---------------------
# Trade worker (single trade — one websocket per trade)
# ---------------------
def trade_thread(api_token, symbol, contract_type, stake, digit, trade_no, timeout=25):
    entry = "-"
    exit_ = "-"
    payout = 0.0
    pl = 0.0
    status = "Unknown"

    ws = None
    try:
        debug_log_raw("→ CONNECT", f"Opening WS for trade #{trade_no}", "info")
        ws = websocket.WebSocket()
        ws.settimeout(8)
        ws.connect("wss://ws.derivws.com/websockets/v3?app_id=1089")
        auth_req = {"authorize": api_token}
        debug_log_raw("→ SEND", auth_req, "info")
        ws.send(json.dumps(auth_req))
        auth_resp_raw = ws.recv()
        debug_log_raw("← RECV", auth_resp_raw, "success")
        auth_resp = json.loads(auth_resp_raw)
        if "error" in auth_resp:
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_, "stake": stake,
                "payout": payout, "pl": pl, "status": f"AuthError: {auth_resp['error']}"
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
        debug_log_raw("→ SEND", proposal, "info")
        ws.send(json.dumps(proposal))

        # wait for proposal response
        proposal_resp = None
        start = time.time()
        while time.time() - start < 6:
            try:
                raw = ws.recv()
            except Exception:
                continue
            debug_log_raw("← RECV", raw, "info")
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "proposal" in msg:
                proposal_resp = msg["proposal"]
                break
            if "error" in msg:
                proposal_resp = {"error": msg["error"]}
                break

        if not proposal_resp or "error" in proposal_resp:
            err = proposal_resp.get("error") if proposal_resp else {"message": "No proposal"}
            debug_log_raw("!!", f"Proposal error for trade #{trade_no}: {err}", "error")
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_, "stake": stake,
                "payout": payout, "pl": pl, "status": f"ProposalError: {err}"
            })
            return

        proposal_id = proposal_resp.get("id") or proposal_resp.get("proposal") or proposal_resp.get("proposal_id")
        debug_log_raw("← INFO", {"proposal_id": proposal_id}, "success")

        # buy
        buy_req = {"buy": proposal_id}
        debug_log_raw("→ SEND", buy_req, "info")
        ws.send(json.dumps(buy_req))

        # wait for buy response
        buy_resp = None
        start = time.time()
        contract_id = None
        while time.time() - start < 6:
            try:
                raw = ws.recv()
            except Exception:
                continue
            debug_log_raw("← RECV", raw, "info")
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "buy" in msg:
                buy_resp = msg["buy"]
                contract_id = buy_resp.get("contract_id") or buy_resp.get("contract")
                break
            if "error" in msg:
                buy_resp = {"error": msg["error"]}
                break

        if not buy_resp or "error" in buy_resp:
            err = buy_resp.get("error") if buy_resp else {"message": "No buy response"}
            debug_log_raw("!!", f"Buy error for trade #{trade_no}: {err}", "error")
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_, "stake": stake,
                "payout": payout, "pl": pl, "status": f"BuyError: {err}"
            })
            return

        debug_log_raw("← INFO", {"contract_id": contract_id}, "success")

        # wait for settlement
        start = time.time()
        while time.time() - start < timeout:
            try:
                raw = ws.recv()
            except Exception:
                continue
            debug_log_raw("← RECV", raw, "info")
            try:
                msg = json.loads(raw)
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
                        debug_log_raw("← INFO", {"settled": {"buy": buy_price, "sell": sell_price, "pl": pl}}, "success")
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
                    debug_log_raw("← INFO", {"contract_settled": {"buy": buy_price, "sell": sell_price, "pl": pl}}, "success")
                    break
            if "sell" in msg:
                s = msg["sell"]
                payout = float(s.get("sell_price", s.get("profit", 0)) or 0)
                pl = payout
                status = "Win" if pl > 0 else ("Loss" if pl < 0 else "Even")
                debug_log_raw("← INFO", {"sell_msg": s}, "success")
                break

        if status == "Unknown":
            debug_log_raw("!!", f"Trade #{trade_no} had no settlement within timeout", "error")
            add_transaction({
                "trade_no": trade_no, "entry": entry, "exit": exit_, "stake": stake,
                "payout": payout, "pl": pl, "status": "NoSettlement"
            })
            return

        # final record
        add_transaction({
            "trade_no": trade_no, "entry": entry, "exit": exit_, "stake": stake,
            "payout": payout, "pl": pl, "status": status
        })

    except Exception as e:
        debug_log_raw("!!", f"Exception in trade #{trade_no}: {e}", "error")
        add_transaction({
            "trade_no": trade_no, "entry": entry, "exit": exit_, "stake": stake,
            "payout": payout, "pl": pl, "status": f"Exception:{e}"
        })
    finally:
        try:
            if ws:
                ws.close()
        except:
            pass

# ---------------------
# Bulk batch runner (10 trades) -> spawns 10 threads
# ---------------------
def run_bulk_batch(api_token, symbol, contract_type, stake, digit):
    threads = []
    timestamp = now_ts()
    add_transaction({"trade_no": f"BatchStart_{timestamp}", "entry":"-","exit":"-","stake":0,"payout":0,"pl":0,"status":f"Starting batch @ {timestamp}"})
    for i in range(1, 11):  # 10 trades per batch
        t = threading.Thread(target=trade_thread, args=(api_token, symbol, contract_type, stake, digit, i), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.02)
    for t in threads:
        t.join(timeout=40)
    add_transaction({"trade_no":"BatchEnd", "entry":"-","exit":"-","stake":0,"payout":0,"pl":0,"status":f"Batch finished @ {now_ts()}"})

# ---------------------
# Continuous runner
# ---------------------
def continuous_runner(api_token, symbol, contract_type, stake, digit):
    batch_no = 0
    while st.session_state.running:
        batch_no += 1
        run_bulk_batch(api_token, symbol, contract_type, stake, digit)
        time.sleep(0.8)
    add_transaction({"trade_no":"System", "entry":"-","exit":"-","stake":0,"payout":0,"pl":0,"status":"Stopped continuous runner"})

# ---------------------
# UI
# ---------------------
def main_ui():
    # header + theme toggle
    header_col1, header_col2 = st.columns([6,1])
    with header_col1:
        st.title("📊 Deriv Bulk WebBot - DBot Style (Bulk 10)")
    with header_col2:
        theme_choice = st.radio("Theme", ("Light","Dark"), index=0 if st.session_state.theme=="light" else 1, horizontal=True)
        if theme_choice.lower() != st.session_state.theme:
            st.session_state.theme = theme_choice.lower()
            apply_theme()

    # layout
    left, center, right = st.columns([1,1.1,1.6])

    # left: controls + debug toggle + download
    with left:
        st.subheader("⚙️ Controls")
        api_token = st.text_input("🔑 API Token", type="password")
        market_label = st.selectbox("📈 Volatility Market", [m[0] for m in MARKET_OPTIONS])
        default_symbol = dict(MARKET_OPTIONS)[market_label]
        custom_symbol = st.text_input("Symbol override (optional)", value=default_symbol)
        contract_type = st.selectbox("Contract Type", ["DIGITMATCH","DIGITDIFF","DIGITOVER","DIGITUNDER","DIGITEVEN","DIGITODD"])
        stake = st.number_input("Stake (USD)", min_value=0.35, value=1.0, step=0.1)
        if contract_type in ["DIGITMATCH","DIGITDIFF","DIGITOVER","DIGITUNDER"]:
            digit = st.number_input("Digit (0-9)", min_value=0, max_value=9, value=5, step=1)
        else:
            digit = 0
        continuous = st.checkbox("Repeat batches until STOP", value=True)
        st.markdown("Note: Each batch fires 10 trades (parallel). Use demo token for testing.")

        # Debug toggle
        if st.checkbox("Enable Debug Mode", value=st.session_state.debug_enabled):
            st.session_state.debug_enabled = True
        else:
            st.session_state.debug_enabled = False

        # Start / Stop
        if not st.session_state.running:
            if st.button("▶️ Start (Bulk 10)"):
                if not api_token:
                    st.error("Please enter API token")
                else:
                    with st.session_state.lock:
                        st.session_state.transactions = []
                        st.session_state.stats = {"stake_total": 0.0, "payout_total": 0.0, "wins": 0, "losses": 0, "profit": 0.0}
                        st.session_state.running = True
                        # clear debug logs when (re)starting
                        st.session_state.debug_messages_raw = []
                        st.session_state.debug_messages_html = []
                    if continuous:
                        threading.Thread(target=continuous_runner, args=(api_token, custom_symbol, contract_type, stake, digit), daemon=True).start()
                    else:
                        threading.Thread(target=run_bulk_batch, args=(api_token, custom_symbol, contract_type, stake, digit), daemon=True).start()
        else:
            if st.button("⏹️ Stop"):
                st.session_state.running = False

    # center: status + recent messages
    with center:
        st.subheader("🤖 Bot Status")
        if st.session_state.running:
            st.success("Bot is running (bulk batches)...")
        else:
            st.info("Bot is stopped.")
        st.markdown("**Live actions / last messages**")
        recent = st.session_state.transactions[-6:] if st.session_state.transactions else []
        for item in reversed(recent):
            text = f"{item.get('trade_no')} | {item.get('status')} | P/L: {item.get('pl',0):+.2f}"
            if item.get("pl", 0) > 0:
                st.markdown(f"<div class='card win'>{now_ts()} {text}</div>", unsafe_allow_html=True)
            elif item.get("pl", 0) < 0:
                st.markdown(f"<div class='card loss'>{now_ts()} {text}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='card info'>{now_ts()} {text}</div>", unsafe_allow_html=True)

        # Debug expander (auto-expanded if debug enabled)
        if st.session_state.debug_enabled:
            debug_exp = st.expander("📡 Debug Log (raw WebSocket send/recv) — Auto-expanded", expanded=True)
        else:
            debug_exp = st.expander("📡 Debug Log (raw WebSocket send/recv)", expanded=False)

        with debug_exp:
            st.markdown("**Downloadable raw debug log**")
            if st.session_state.debug_messages_raw:
                st.download_button("📥 Download Debug Log", "\n".join(st.session_state.debug_messages_raw), file_name="debug_log.txt", mime="text/plain")
            else:
                st.write("No debug messages yet.")
            st.markdown("---")
            # Show formatted HTML debug messages with color
            if st.session_state.debug_messages_html:
                # display last 300 messages for performance
                html_to_show = "\n".join(st.session_state.debug_messages_html[-300:])
                st.markdown(f"<div class='debug-box'>{html_to_show}</div>", unsafe_allow_html=True)
            else:
                st.write("Debug messages will appear here when enabled.")

    # right: transactions list + session summary
    with right:
        st.subheader("📜 Transactions (session)")
        if not st.session_state.transactions:
            st.info("No trades yet.")
        else:
            for t in reversed(st.session_state.transactions):
                cls = "win" if t.get("pl",0) > 0 else ("loss" if t.get("pl",0) < 0 else "info")
                st.markdown(
                    f"<div class='card'>"
                    f"<b>#{t.get('trade_no')}</b> &nbsp; <span class='{cls}'>{t.get('status')}</span><br>"
                    f"Stake: {t.get('stake')} &nbsp; Payout: {t.get('payout')} &nbsp; P/L: <span class='{cls}'>{t.get('pl'):+.2f}</span><br>"
                    f"Entry: {t.get('entry')} &nbsp; Exit: {t.get('exit')}"
                    f"</div>", unsafe_allow_html=True)

    # bottom summary
    st.markdown("---")
    st.subheader("📊 Session Summary")
    s = st.session_state.stats
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Stake", f"${s['stake_total']:.2f}")
    c2.metric("Total Payout", f"${s['payout_total']:.2f}")
    c3.metric("Wins", s["wins"])
    c4.metric("Losses", s["losses"])
    c5.metric("Profit/Loss", f"${s['profit']:.2f}")

# run
if __name__ == "__main__":
    main_ui()
