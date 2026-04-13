from flask import Flask, request, render_template_string
import time

app = Flask(__name__)

symbol = "BTCUSD"

bias = None
zones = []
current_trade = None
last_trade_time = 0

COOLDOWN = 180
ZONE_TTL = 75 * 60  # 75 minutes

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

# ================= CLEAN OLD ZONES =================
def clean_zones():
    now = time.time()
    return [z for z in zones if now - z["timestamp"] < ZONE_TTL]

# ================= ENTRY ENGINE =================
def try_trade(price):
    global current_trade, last_trade_time, zones

    zones = clean_zones()

    now = time.time()

    if not bias:
        return

    if current_trade or now - last_trade_time < COOLDOWN:
        return

    for z in zones[-5:]:

        # Skip weak zones
        if z["type"] == "internal_ob":
            continue

        # Price near zone
        if abs(price - z["price"]) < price * 0.005:

            if bias == "buy" and z["trend"] == "bullish":
                current_trade = {
                    "side": "buy",
                    "entry": price,
                    "time": time.strftime('%H:%M:%S')
                }
                last_trade_time = now
                log(f"🚀 BUY ({z['type']})")
                return

            elif bias == "sell" and z["trend"] == "bearish":
                current_trade = {
                    "side": "sell",
                    "entry": price,
                    "time": time.strftime('%H:%M:%S')
                }
                last_trade_time = now
                log(f"🚀 SELL ({z['type']})")
                return

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    global bias, zones

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

        zone = {
            "type": ztype,
            "trend": trend,
            "price": price,
            "timestamp": time.time(),
            "time": time.strftime('%H:%M:%S')
        }

        zones.append(zone)
        log(f"📍 {trend} {ztype}")

        # 🚀 ENTRY TRIGGERED HERE (NO LOOP)
        try_trade(price)

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="5"></head>
<body style="background:#0f172a;color:white">

<h2>BOT</h2>

<p><b>Bias:</b> {{bias}}</p>
<p><b>Trade:</b> {{trade}}</p>

<h3>Zones</h3>
{% for z in zones %}
<div>{{z.time}} | {{z.type}} | {{z.price}}</div>
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
