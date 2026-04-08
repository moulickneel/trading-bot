from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC BOT (DISCIPLINED MODE) STARTED 🔥", flush=True)

symbol = "BTCUSD"

bias = {}
price_store = {}

current_trade = None
last_trade_time = 0
trade_history = []

COOLDOWN = 8  # slightly controlled

log_buffer = []

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 120:
        log_buffer.pop(0)

# ================= STATS =================
def stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    pnl = sum(t["pnl"] for t in trade_history)
    winrate = (wins / total * 100) if total else 0
    return total, wins, total-wins, round(winrate,2), round(pnl,2)

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time

    prev = price_store.get(symbol)
    prev2 = price_store.get("prev2")

    price_store[symbol] = price

    log(f"📡 BTC Price: {price}")

    if not prev:
        return

    # ========= STRUCTURE TREND =========
    trend = None
    if prev2:
        if price > prev and prev > prev2:
            trend = "up"
        elif price < prev and prev < prev2:
            trend = "down"

    price_store["prev2"] = prev

    move = price - prev
    momentum = abs(move) > price * 0.00008  # tuned

    htf = bias.get(symbol)

    log(f"HTF: {htf} | Trend: {trend} | Momentum: {momentum}")

    if not htf:
        log("⚠️ No HTF bias — skipping trade")
        return

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and (now - last_trade_time > COOLDOWN):

        decision = None

        # 🔥 STRICT HTF ALIGNMENT
        if htf == "buy":
            if trend == "up" and momentum:
                decision = "buy"

        elif htf == "sell":
            if trend == "down" and momentum:
                decision = "sell"

        if not decision:
            log("❌ No valid entry condition")
            return

        risk = price * 0.001

        sl = price - risk if decision == "buy" else price + risk
        tp = price + risk*2 if decision == "buy" else price - risk*2

        current_trade = {
            "side": decision,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "time": time.strftime('%H:%M:%S')
        }

        last_trade_time = now
        log(f"🚀 {decision.upper()} @ {price}")

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

# ================= PRICE LOOP =================
def price_loop():
    while True:
        try:
            url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
            res = requests.get(url, timeout=5).json()
            price = float(res["data"]["amount"])

            on_price_update(price)

        except Exception as e:
            log(f"❌ API Error: {e}")

        time.sleep(1)

threading.Thread(target=price_loop, daemon=True).start()

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}

    trend = str(data.get("trend","")).lower()

    if "bullish" in trend:
        bias[symbol] = "buy"
        log("🎯 HTF BUY")

    elif "bearish" in trend:
        bias[symbol] = "sell"
        log("🎯 HTF SELL")

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h2>BTC BOT (DISCIPLINED)</h2>

<p><b>Bias:</b> {{bias}}</p>
<p><b>Active Trade:</b> {{trade}}</p>

<p><b>Trades:</b> {{t}} | <b>Winrate:</b> {{wr}}% | <b>PnL:</b> {{pnl}}R</p>

<h3>Recent Trades</h3>
{% for t in hist %}
<div>{{t.time}} | {{t.side}} | {{t.result}} | {{t.pnl}}R</div>
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
        hist=reversed(trade_history[-25:]),
        logs=reversed(log_buffer),
        t=t, wr=wr, pnl=pnl
    )

@app.route('/')
def home():
    return {"status": "DISCIPLINED BOT RUNNING"}

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
