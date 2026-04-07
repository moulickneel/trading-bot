from flask import Flask, request, jsonify, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC BOT (REST MODE) STARTED 🔥", flush=True)

# =========================
# STATE
# =========================
symbol = "BTCUSDT"

bias = {}
ltf_zones = []
price_store = {}

current_trade = None
last_trade_time = 0
trade_history = []

COOLDOWN = 10

log_buffer = []

# =========================
# LOG
# =========================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 100:
        log_buffer.pop(0)

# =========================
# STATS
# =========================
def stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    pnl = sum(t["pnl"] for t in trade_history)
    winrate = (wins / total * 100) if total else 0
    return total, wins, total-wins, round(winrate,2), round(pnl,2)

# =========================
# STRATEGY CORE
# =========================
def on_price_update(price):
    global current_trade, last_trade_time

    prev = price_store.get(symbol)
    price_store[symbol] = price

    # 🔥 PRICE LOG
    log(f"📡 BTC Price: {price}")

    if not prev:
        return

    htf = bias.get(symbol)
    move = abs(price - prev)
    momentum = move > price * 0.0004
    trend = "up" if price > prev else "down"

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and htf:

        if now - last_trade_time < COOLDOWN:
            return

        decision = None
        confidence = "LOW"

        # Momentum entry
        if momentum:
            if htf == "buy" and trend == "up":
                decision = "buy"
            elif htf == "sell" and trend == "down":
                decision = "sell"

        # Pullback entry
        if not decision:
            if htf == "buy" and trend == "up":
                decision = "buy"
                log("📈 Pullback BUY")
            elif htf == "sell" and trend == "down":
                decision = "sell"
                log("📉 Pullback SELL")

        # LTF boost
        if ltf_zones:
            recent = ltf_zones[-1]["type"]
            if decision == "buy" and "bullish" in recent:
                confidence = "HIGH"
            elif decision == "sell" and "bearish" in recent:
                confidence = "HIGH"

        if decision:
            risk = move * 2 if move else price * 0.002

            sl = price - risk if decision == "buy" else price + risk
            tp = price + risk*2 if decision == "buy" else price - risk*2

            current_trade = {
                "side": decision,
                "entry": price,
                "sl": sl,
                "tp": tp,
                "confidence": confidence,
                "time": time.strftime('%H:%M:%S')
            }

            last_trade_time = now
            log(f"🚀 {decision.upper()} @ {price} | {confidence}")

    # ================= EXIT =================
    if current_trade:
        side = current_trade["side"]
        sl = current_trade["sl"]
        tp = current_trade["tp"]

        result = None
        pnl = 0

        if side == "buy":
            if price <= sl:
                result = "loss"; pnl = -1
            elif price >= tp:
                result = "win"; pnl = 2

        if side == "sell":
            if price >= sl:
                result = "loss"; pnl = -1
            elif price <= tp:
                result = "win"; pnl = 2

        if result:
            current_trade["result"] = result
            current_trade["pnl"] = pnl
            trade_history.append(current_trade)

            log(f"{result.upper()} {pnl}R")

            current_trade = None

# =========================
# PRICE LOOP (REST API)
# =========================
def price_loop():
    while True:
        try:
            url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
            res = requests.get(url, timeout=5).json()
            price = float(res["price"])

            on_price_update(price)

        except Exception as e:
            log(f"❌ API Error: {e}")

        time.sleep(1)

threading.Thread(target=price_loop, daemon=True).start()

# =========================
# WEBHOOK (HTF + LTF)
# =========================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}

    trend = str(data.get("trend","")).lower()
    tf = data.get("timeframe")
    ltf_type = str(data.get("type","")).lower()

    # HTF
    if tf == "HTF":
        if "bullish" in trend:
            bias[symbol] = "buy"
            log("🎯 HTF BUY")
        elif "bearish" in trend:
            bias[symbol] = "sell"
            log("🎯 HTF SELL")

    # LTF
    if tf == "LTF" and ltf_type:
        ltf_zones.append({
            "type": ltf_type,
            "time": time.time()
        })

        if len(ltf_zones) > 20:
            ltf_zones.pop(0)

        log(f"📍 LTF: {ltf_type}")

    return {"ok": True}

# =========================
# IGNORE PRICE ALERTS
# =========================
@app.route('/update_price', methods=['POST'])
def ignore_price():
    log("⚠️ Ignored TradingView price update")
    return {"status": "ignored"}

# =========================
# DASHBOARD
# =========================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h2>BTC LIVE BOT (REST)</h2>

<p><b>Bias:</b> {{bias}}</p>
<p><b>Active Trade:</b> {{trade}}</p>

<p><b>Trades:</b> {{t}} | <b>Winrate:</b> {{wr}}% | <b>PnL:</b> {{pnl}}R</p>

<h3>Recent Trades</h3>
{% for t in hist %}
<div>{{t.time}} | {{t.side}} | {{t.result}} | {{t.pnl}}R | {{t.confidence}}</div>
{% endfor %}

<h3>Logs</h3>
{% for l in logs %}
<div>{{l}}</div>
{% endfor %}

</body>
</html>
"""

@app.route('/dashboard')
def dash():
    t,w,l,wr,pnl = stats()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        t=t, wr=wr, pnl=pnl
    )

@app.route('/')
def home():
    return {"status": "BTC BOT RUNNING (REST MODE)"}

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
