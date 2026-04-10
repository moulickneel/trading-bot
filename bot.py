from flask import Flask, request, render_template_string
import time, json

app = Flask(__name__)

symbol = "BTCUSD"

bias = None
zones = []
price_data = []
current_trade = None
last_trade_time = 0

COOLDOWN = 180
ZONE_TOLERANCE = 0.005

log_file = "logs.txt"

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    with open(log_file, "a") as f:
        f.write(entry + "\n")

def get_logs():
    try:
        with open(log_file, "r") as f:
            return f.readlines()[-200:]
    except:
        return []

# ================= CORE ENGINE =================
def process_signal(price):
    global current_trade, last_trade_time

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 {price}")

    if not bias:
        return

    # ===== ENTRY =====
    now = time.time()

    if not current_trade and now - last_trade_time > COOLDOWN:

        for z in zones[-5:]:

            if z["type"] == "internal_ob":
                continue

            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                if bias == "buy" and z["trend"] == "bullish":
                    current_trade = {"side":"buy","entry":price}
                    last_trade_time = now
                    log("🚀 BUY")
                    break

                elif bias == "sell" and z["trend"] == "bearish":
                    current_trade = {"side":"sell","entry":price}
                    last_trade_time = now
                    log("🚀 SELL")
                    break

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    global bias

    data = request.json or {}
    log(f"📩 {data}")

    signal = str(data.get("signal","")).lower()
    trend = str(data.get("trend","")).lower()
    tf = str(data.get("timeframe","")).lower()
    price = float(data.get("price",0))

    # ===== HTF =====
    if tf == "htf":
        if "choch" in signal:
            bias = "buy" if "bullish" in signal else "sell"
            log(f"🔥 CHOCH → {bias}")

        elif "bos" in signal and bias is None:
            bias = "buy" if "bullish" in signal else "sell"
            log(f"📊 BOS → {bias}")

    # ===== LTF =====
    if tf == "ltf":

        if "fvg" in signal:
            ztype = "fvg"
        elif "swing ob" in signal:
            ztype = "swing_ob"
        elif "internal ob" in signal:
            ztype = "internal_ob"
        else:
            return {"ok": True}

        zones.append({
            "type": ztype,
            "trend": trend,
            "price": price,
            "time": time.strftime('%H:%M:%S')
        })

        log(f"📍 {trend} {ztype}")

        # 🚀 PROCESS ENTRY ONLY WHEN LTF ARRIVES
        process_signal(price)

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="5"></head>
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
def dashboard():
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        zones=zones[-10:],
        logs=reversed(get_logs())
    )

@app.route('/health')
def health():
    return {"status":"ok"}

@app.route('/')
def home():
    return {"status":"running"}
