from flask import Flask, request, render_template_string
import time, requests, os

app = Flask(__name__)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0

trade_history = []
log_buffer = []

COOLDOWN = 120
ZONE_TOLERANCE = 0.005

MAX_AGE_FVG = 8
MAX_AGE_OB = 15

last_tick = 0

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 200:
        log_buffer.pop(0)

# ================= PRICE =================
def get_price():
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=2)
        return float(r.json()["data"]["amount"])
    except:
        return None

# ================= DISPLACEMENT =================
def displacement():
    if len(price_data) < 6:
        return None

    c1, c2, c3, c4 = price_data[-1], price_data[-2], price_data[-3], price_data[-4]

    if max(c1,c2) > max(c3,c4) and min(c1,c2) > min(c3,c4) and c1 > max(c3,c4):
        return "buy"

    if max(c1,c2) < max(c3,c4) and min(c1,c2) < min(c3,c4) and c1 < min(c3,c4):
        return "sell"

    return None

# ================= BOT TICK =================
def run_bot():
    global last_tick, current_trade, last_trade_time

    if time.time() - last_tick < 2:
        return

    last_tick = time.time()

    price = get_price()
    if not price:
        return

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 {price}")

    htf = bias.get(symbol)
    if not htf:
        return

    disp = displacement()

    now = time.time()

    # ===== ENTRY =====
    if not current_trade and now - last_trade_time > COOLDOWN:

        decision = None

        for z in zones[-5:]:
            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                if htf == "buy" and "bullish" in z["type"] and disp == "buy":
                    decision = "buy"
                    log("🔵 BUY")

                elif htf == "sell" and "bearish" in z["type"] and disp == "sell":
                    decision = "sell"
                    log("🔴 SELL")

        if decision:
            sl = price * (0.999 if decision=="buy" else 1.001)

            current_trade = {
                "side": decision,
                "entry": price,
                "sl": sl
            }

            last_trade_time = now

    # ===== EXIT =====
    if current_trade:
        side = current_trade["side"]
        entry = current_trade["entry"]
        sl = current_trade["sl"]

        if (side=="buy" and price <= sl) or (side=="sell" and price >= sl):
            log("❌ SL")
            current_trade = None

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    log(f"📩 {data}")

    signal = str(data.get("signal","")).lower()
    trend = str(data.get("trend","")).lower()
    tf = str(data.get("timeframe","")).lower()
    price = float(data.get("price",0))

    if tf == "htf":
        if "bullish" in signal:
            bias[symbol] = "buy"
        elif "bearish" in signal:
            bias[symbol] = "sell"

    if tf == "ltf":
        if "fvg" in signal or "ob" in signal:
            zones.append({
                "type": trend + "_zone",
                "price": price,
                "time": time.strftime('%H:%M:%S')
            })
            log(f"📍 Zone {trend}")

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white">
<h2>BOT</h2>
<p>Bias: {{bias}}</p>
<p>Trade: {{trade}}</p>

<h3>Zones</h3>
{% for z in zones %}
<div>{{z}}</div>
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
    run_bot()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        logs=reversed(log_buffer),
        zones=zones[-10:]
    )

@app.route('/health')
def health():
    run_bot()
    return {"status":"ok"}

@app.route('/')
def home():
    run_bot()
    return {"status":"running"}

if __name__ == "__main__":
    app.run()
