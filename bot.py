from flask import Flask, request, render_template_string
import time, requests

app = Flask(__name__)

# ================= GLOBALS =================
bias = None
zones = []
current_trade = None
last_trade_time = 0

price_data = []

# Polling control
last_price = None
last_fetch_time = 0
last_engine_run = 0

# Settings
COOLDOWN = 180
ZONE_TTL = 75 * 60
ZONE_TOLERANCE = 0.005
POLL_INTERVAL = 5

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

# ================= PRICE =================
def get_price():
    global last_price, last_fetch_time

    if time.time() - last_fetch_time < POLL_INTERVAL:
        return last_price

    last_fetch_time = time.time()

    try:
        r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=1.5)
        last_price = float(r.json()["data"]["amount"])
        return last_price
    except:
        return last_price

# ================= ZONE CLEAN =================
def clean_zones():
    now = time.time()
    return [z for z in zones if now - z["timestamp"] < ZONE_TTL]

# ================= MITIGATION =================
def is_fvg_mitigated(zone, price):
    if zone["trend"] == "bullish" and price < zone["price"]:
        return True
    if zone["trend"] == "bearish" and price > zone["price"]:
        return True
    return False

# ================= ENTRY =================
def try_trade(price):
    global current_trade, last_trade_time, zones

    zones = clean_zones()
    now = time.time()

    if not bias:
        return

    if current_trade or now - last_trade_time < COOLDOWN:
        return

    for z in zones[-5:]:

        if z["type"] == "internal_ob":
            continue

        if is_fvg_mitigated(z, price):
            continue

        if abs(price - z["price"]) < price * ZONE_TOLERANCE:

            if bias == "buy" and z["trend"] == "bullish":
                current_trade = {
                    "side": "buy",
                    "entry": price,
                    "sl": price * 0.998,
                    "be": False,
                    "trail": False,
                    "time": time.strftime('%H:%M:%S')
                }
                last_trade_time = now
                log(f"🚀 BUY ({z['type']})")
                return

            elif bias == "sell" and z["trend"] == "bearish":
                current_trade = {
                    "side": "sell",
                    "entry": price,
                    "sl": price * 1.002,
                    "be": False,
                    "trail": False,
                    "time": time.strftime('%H:%M:%S')
                }
                last_trade_time = now
                log(f"🚀 SELL ({z['type']})")
                return

# ================= TRADE MANAGEMENT =================
def manage_trade(price):
    global current_trade

    if not current_trade:
        return

    side = current_trade["side"]
    entry = current_trade["entry"]
    sl = current_trade["sl"]

    risk = abs(entry - sl)
    if risk == 0:
        return

    r = (price - entry)/risk if side=="buy" else (entry - price)/risk

    # Break even
    if r >= 1 and not current_trade["be"]:
        current_trade["sl"] = entry
        current_trade["be"] = True
        log("🔒 BE moved")

    # Trailing
    if r >= 2:
        current_trade["trail"] = True
        if side == "buy":
            current_trade["sl"] = max(current_trade["sl"], price - risk)
        else:
            current_trade["sl"] = min(current_trade["sl"], price + risk)

    # Exit
    if (side=="buy" and price <= current_trade["sl"]) or (side=="sell" and price >= current_trade["sl"]):
        log(f"✅ EXIT {round(r,2)}R")
        current_trade = None

# ================= ENGINE =================
def run_engine():
    global last_engine_run, price_data

    if time.time() - last_engine_run < 3:
        return

    last_engine_run = time.time()

    price = get_price()
    if not price:
        return

    price_data.append(price)
    if len(price_data) > 100:
        price_data.pop(0)

    log(f"📡 {price}")

    manage_trade(price)
    try_trade(price)

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

    # HTF
    if tf == "htf":
        if "choch" in signal:
            bias = "buy" if "bullish" in signal else "sell"
            log(f"🔥 CHOCH → {bias}")
        elif "bos" in signal and bias is None:
            bias = "buy" if "bullish" in signal else "sell"
            log(f"📊 BOS → {bias}")

    # LTF
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
            "timestamp": time.time(),
            "time": time.strftime('%H:%M:%S')
        })

        log(f"📍 {trend} {ztype}")

        run_engine()

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="5"></head>
<body style="background:#0f172a;color:white;font-family:sans-serif">

<h2>🚀 BOT</h2>

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
    run_engine()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        zones=zones[-10:],
        logs=reversed(get_logs())
    )

@app.route('/health')
def health():
    run_engine()
    return {"status":"ok"}

@app.route('/')
def home():
    return {"status":"running"}
