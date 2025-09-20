def fetch_account_balance(api_token, update_interval=3):
    while st.session_state.running:
        try:
            ws = websocket.WebSocket()
            ws.settimeout(8)
            ws.connect("wss://ws.derivws.com/websockets/v3?app_id=1089")
            auth_req = {"authorize": api_token}
            ws.send(json.dumps(auth_req))
            auth_resp_raw = ws.recv()
            auth_resp = json.loads(auth_resp_raw)
            if "error" in auth_resp:
                with st.session_state.lock:
                    st.session_state.balance = None
                    st.session_state.balance_error = f"Authorization error: {auth_resp['error'].get('message', str(auth_resp['error']))}"
                ws.close()
                time.sleep(update_interval)
                continue
            # fetch balance
            bal_req = {"balance": 1, "currency": "USD"}
            ws.send(json.dumps(bal_req))
            bal_resp_raw = ws.recv()
            bal_resp = json.loads(bal_resp_raw)
            if "balance" in bal_resp:
                balance = bal_resp["balance"].get("balance", None)
                currency = bal_resp["balance"].get("currency", "USD")
                with st.session_state.lock:
                    st.session_state.balance = balance
                    st.session_state.account_currency = currency
                    st.session_state.balance_error = ""
            elif "error" in bal_resp:
                with st.session_state.lock:
                    st.session_state.balance = None
                    st.session_state.balance_error = f"Balance error: {bal_resp['error'].get('message', str(bal_resp['error']))}"
            else:
                with st.session_state.lock:
                    st.session_state.balance = None
                    st.session_state.balance_error = "Unknown error fetching balance."
            ws.close()
        except Exception as e:
            with st.session_state.lock:
                st.session_state.balance = None
                st.session_state.balance_error = f"Exception fetching balance: {e}"
            try:
                ws.close()
            except:
                pass
        time.sleep(update_interval)
