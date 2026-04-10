from flask import Flask, request, render_template_string
import time, requests

app = Flask(__name__)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []
current_trade = None

log_buffer = []
last_price = None
last_fetch = 0

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 200:
        log_buffer.pop(0)

# ================= SAFE PRICE =================
def get_price():
    global last_price, last_fetch

    # fetch only every 3 seconds
    if time.time() - last_fetch < 3:
        return last_price

    last_fetch = time.time()

    try:
        r = requests.get(
            "https://api.coinbase.com/v2/prices/BTC-USD/spot",
            timeout=1.5
        )
        last_price = float(r.json()["data"]["amount"])
        return last_price
    except:
        log("⚠️ price fetch fail")
        return last_price

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
def bot_tick():
    global current_trade

    price = get_price()
    if not price:
        return

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 {price}")

    htf = bias.get(symbol)
    disp = displacement()

    if not htf or not disp:
        return

    # ENTRY
    if not current_trade:
        for z in zones[-5:]:
            if abs(price - z["price"]) < price * 0.005:

                if htf == "buy" and disp == "buy":
                    current_trade = {"side": "buy", "entry": price}
                    log("🚀 BUY")

                elif htf == "sell" and disp == "sell":
                    current_trade = {"side": "sell", "entry": price}
                    log("🚀 SELL")

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
                "type": trend,
                "price": price,
                "time": time.strftime('%H:%M:%S')
            })
            log(f"📍 Zone {trend}")

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="3"></head>
<body style="background:#0f172a;color:white">
<h2>BTC BOT</h2>

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
def dashboard():
    bot_tick()  # safe, fast
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        zones=zones[-10:],
        logs=reversed(log_buffer)
    )

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/')
def home():
    return {"status": "running"}

if __name__ == "__main__":
    app.run()
