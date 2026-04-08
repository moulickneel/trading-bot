from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC SMC BOT STARTED 🔥", flush=True)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0
trade_history = []

COOLDOWN = 20
ZONE_TOLERANCE = 0.003

log_buffer = []

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 200:
        log_buffer.pop(0)

# ================= STATS =================
def stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    pnl = sum(t["pnl"] for t in trade_history)
    winrate = (wins / total * 100) if total else 0
    return total, round(winrate,2), round(pnl,2)

# ================= STRUCTURE =================
def get_structure():
    if len(price_data) < 10:
        return None

    highs = price_data[-5:]
    lows = price_data[-10:-5]

    if max(highs) > max(lows):
        return "up"
    elif min(highs) < min(lows):
        return "down"

    return None

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 Price: {price}")

    structure = get_structure()

    if not structure:
        log("⚠️ No structure yet")
        return

    htf = bias.get(symbol)

    if not htf:
        log("⚠️ No HTF bias")
        return

    log(f"HTF: {htf} | Structure: {structure}")

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and (now - last_trade_time > COOLDOWN):

        decision = None

        # 🔥 STRICT HTF FILTER
        if htf == "buy" and structure != "up":
            log("❌ Blocked: Not in uptrend")
            return

        if htf == "sell" and structure != "down":
            log("❌ Blocked: Not in downtrend")
            return

        # 🔥 CHECK ZONE ENTRY
        for z in reversed(zones[-10:]):
            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                if htf == "buy" and "bullish" in z["type"]:
                    decision = "buy"
                    log(f"📍 BUY from zone {z}")

                elif htf == "sell" and "bearish" in z["type"]:
                    decision = "sell"
                    log(f"📍 SELL from zone {z}")

        # 🔥 MOMENTUM CONFIRMATION
        if len(price_data) >= 3:
            p1, p2, p3 = price_data[-1], price_data[-2], price_data[-3]

            if htf == "buy" and p1 > p2 > p3:
                decision = "buy"
                log("⚡ Momentum BUY")

            elif htf == "sell" and p1 < p2 < p3:
                decision = "sell"
                log("⚡ Momentum SELL")

        if not decision:
            log("❌ No valid entry")
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

    log(f"📩 {data}")

    trend = str(data.get("trend","")).lower()
    signal_type = str(data.get("type","")).lower()
    price = float(data.get("price", 0) or 0)

    if "bullish" in trend:
        bias[symbol] = "buy"
        log("🎯 HTF BUY")

    elif "bearish" in trend:
        bias[symbol] = "sell"
        log("🎯 HTF SELL")

    if signal_type in ["bullish_ob","bearish_ob","bullish_fvg","bearish_fvg"]:
        zones.append({
            "type": signal_type,
            "price": price,
            "time": time.strftime('%H:%M:%S')
        })
        log(f"📍 Zone stored {signal_type} @ {price}")

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white">

<h2>BTC SMC BOT</h2>

<p>Bias: {{bias}}</p>
<p>Active: {{trade}}</p>
<p>Trades: {{t}} | Winrate: {{wr}}% | PnL: {{pnl}}R</p>

<h3>Zones</h3>
{% for z in zones %}
<div>{{z.time}} | {{z.type}} | {{z.price}}</div>
{% endfor %}

<h3>Trades</h3>
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
    t,wr,pnl = stats()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        zones=reversed(zones[-10:]),
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        t=t, wr=wr, pnl=pnl
    )

@app.route('/')
def home():
    return {"status": "SMC BOT RUNNING"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
