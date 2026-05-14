from flask import Flask, request, render_template_string
import time
import requests

app = Flask(__name__)

# ================= GLOBALS =================
bias = None
zones = []
current_trade = None
last_trade_time = 0

price_data = []

# Performance
trade_history = []
total_trades = 0
wins = 0
losses = 0
net_r = 0

# Polling
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
        r = requests.get(
            "https://api.coinbase.com/v2/prices/BTC-USD/spot",
            timeout=1.5
        )

        last_price = float(r.json()["data"]["amount"])
        return last_price

    except:
        return last_price

# ================= HELPERS =================
def clean_zones():
    now = time.time()

    return [
        z for z in zones
        if now - z["timestamp"] < ZONE_TTL
    ]

def winrate():
    if total_trades == 0:
        return 0

    return round((wins / total_trades) * 100, 2)

# ================= MITIGATION =================
def is_zone_mitigated(zone, price):

    if zone["trend"] == "bullish" and price < zone["price"]:
        return True

    if zone["trend"] == "bearish" and price > zone["price"]:
        return True

    return False

# ================= LIQUIDITY SWEEP =================
def liquidity_sweep():

    if len(price_data) < 22:
        return None

    recent_high = max(price_data[-22:-2])
    recent_low = min(price_data[-22:-2])

    current = price_data[-1]
    previous = price_data[-2]

    # Swept previous high
    if current > recent_high and previous <= recent_high:
        return "high_sweep"

    # Swept previous low
    if current < recent_low and previous >= recent_low:
        return "low_sweep"

    return None

# ================= DISPLACEMENT =================
def displacement():

    if len(price_data) < 3:
        return None

    prev = price_data[-2]
    current = price_data[-1]

    # Buy displacement
    if current > prev * 1.001:
        return "buy"

    # Sell displacement
    if current < prev * 0.999:
        return "sell"

    return None

# ================= ENTRY =================
def try_trade(price):
    global current_trade
    global last_trade_time
    global zones

    zones = clean_zones()

    now = time.time()

    if not bias:
        return

    # ===== EXISTING TRADE =====
    if current_trade:

        # If bias flips opposite to trade
        if current_trade["side"] != bias:
            log("⚠️ Bias flipped — closing old trade")
            current_trade = None
        else:
            return

    # ===== COOLDOWN =====
    if now - last_trade_time < COOLDOWN:
        return

    sweep = liquidity_sweep()
    disp = displacement()

    for z in zones[-5:]:

        # Ignore weak internal OB
        if z["type"] == "internal_ob":
            continue

        # Ignore mitigated zones
        if is_zone_mitigated(z, price):
            continue

        # Price near zone
        if abs(price - z["price"]) < price * ZONE_TOLERANCE:

            # ===== BUY =====
            if (
                bias == "buy"
                and z["trend"] == "bullish"
                and sweep == "low_sweep"
                and disp == "buy"
            ):

                sl = price * 0.997

                current_trade = {
                    "side": "buy",
                    "entry": price,
                    "sl": sl,
                    "initial_sl": sl,
                    "be": False,
                    "trail": False,
                    "time": time.strftime('%H:%M:%S')
                }

                last_trade_time = now

                log(f"🚀 BUY ({z['type']}) @ {round(price,2)}")
                return

            # ===== SELL =====
            elif (
                bias == "sell"
                and z["trend"] == "bearish"
                and sweep == "high_sweep"
                and disp == "sell"
            ):

                sl = price * 1.003

                current_trade = {
                    "side": "sell",
                    "entry": price,
                    "sl": sl,
                    "initial_sl": sl,
                    "be": False,
                    "trail": False,
                    "time": time.strftime('%H:%M:%S')
                }

                last_trade_time = now

                log(f"🚀 SELL ({z['type']}) @ {round(price,2)}")
                return

# ================= TRADE MANAGEMENT =================
def manage_trade(price):
    global current_trade
    global trade_history
    global total_trades
    global wins
    global losses
    global net_r

    if not current_trade:
        return

    side = current_trade["side"]
    entry = current_trade["entry"]
    sl = current_trade["sl"]

    risk = abs(entry - sl)

    if risk == 0:
        return

    # R calculation
    if side == "buy":
        r = (price - entry) / risk
    else:
        r = (entry - price) / risk

    # ===== BREAK EVEN =====
    if r >= 1 and not current_trade["be"]:

        current_trade["sl"] = entry
        current_trade["be"] = True

        log("🔒 Break-even moved")

    # ===== TRAILING =====
    if r >= 2:

        current_trade["trail"] = True

        if side == "buy":
            current_trade["sl"] = max(
                current_trade["sl"],
                price - risk
            )

        else:
            current_trade["sl"] = min(
                current_trade["sl"],
                price + risk
            )

    # ===== EXIT =====
    exit_trade = False

    if side == "buy" and price <= current_trade["sl"]:
        exit_trade = True

    if side == "sell" and price >= current_trade["sl"]:
        exit_trade = True

    if exit_trade:

        result = round(r, 2)

        trade_history.append({
            "side": side,
            "result": result,
            "time": time.strftime('%H:%M:%S')
        })

        total_trades += 1

        if result > 0:
            wins += 1
        else:
            losses += 1

        net_r += result

        log(f"✅ EXIT {result}R")

        current_trade = None

# ================= ENGINE =================
def run_engine():
    global last_engine_run
    global price_data

    # Prevent overload
    if time.time() - last_engine_run < 3:
        return

    last_engine_run = time.time()

    price = get_price()

    if not price:
        return

    price_data.append(price)

    if len(price_data) > 100:
        price_data.pop(0)

    manage_trade(price)
    try_trade(price)

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    global bias
    global zones

    data = request.json or {}

    signal = str(data.get("signal", "")).lower()
    trend = str(data.get("trend", "")).lower()
    tf = str(data.get("timeframe", "")).lower()
    price = float(data.get("price", 0))

    log(f"📩 {signal}")

    # ===== HTF =====
    if tf == "htf":

        if "choch" in signal:

            bias = "buy" if "bullish" in signal else "sell"

            log(f"🔥 Bias → {bias}")

        elif "bos" in signal and bias is None:

            bias = "buy" if "bullish" in signal else "sell"

            log(f"📊 Bias → {bias}")

    # ===== LTF =====
    elif tf == "ltf":

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

    run_engine()

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head>
<meta http-equiv="refresh" content="5">
<title>Trading Bot Dashboard</title>
</head>

<body style="background:#0f172a;color:white;font-family:sans-serif;padding:20px;">

<h1>🚀 Trading Bot Dashboard</h1>

<hr>

<h2>📌 Active Status</h2>

<p><b>Bias:</b> {{bias}}</p>

<p><b>Active Trade:</b></p>

{% if trade %}
<div style="padding:10px;border:1px solid white;">
Side: {{trade.side}} <br>
Entry: {{trade.entry}} <br>
SL: {{trade.sl}} <br>
BE: {{trade.be}} <br>
Trailing: {{trade.trail}} <br>
Time: {{trade.time}}
</div>
{% else %}
<p>No active trade</p>
{% endif %}

<hr>

<h2>📊 Performance</h2>

<p>Total Trades: {{total}}</p>
<p>Wins: {{wins}}</p>
<p>Losses: {{losses}}</p>
<p>Winrate: {{wr}}%</p>
<p>Net R: {{netr}}</p>

<hr>

<h2>📜 Recent Trades</h2>

{% for t in history %}
<div style="padding:5px;">
{{t.time}} | {{t.side}} | {{t.result}}R
</div>
{% endfor %}

<hr>

<h2>🧠 Recent Logs</h2>

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
        total=total_trades,
        wins=wins,
        losses=losses,
        wr=winrate(),
        netr=round(net_r, 2),
        history=reversed(trade_history[-10:]),
        logs=reversed(get_logs()[-30:])
    )

@app.route('/health')
def health():

    run_engine()

    return {"status": "ok"}

@app.route('/')
def home():

    return {"status": "running"}
