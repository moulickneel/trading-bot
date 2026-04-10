from flask import Flask, request, render_template_string
import time, requests, threading

app = Flask(__name__)

symbol = "BTCUSD"

bias = None
zones = []
price_data = []

current_trade = None
last_trade_time = 0

COOLDOWN = 180
ZONE_TOLERANCE = 0.005
LOOKBACK = 20

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

# ================= LIQUIDITY SWEEP =================
def liquidity_sweep():
    if len(price_data) < LOOKBACK + 5:
        return None

    prev_high = max(price_data[-LOOKBACK-5:-5])
    prev_low = min(price_data[-LOOKBACK-5:-5])

    price = price_data[-1]

    # Sweep + rejection logic
    if price > prev_high and price_data[-2] < prev_high:
        return "high_sweep"

    if price < prev_low and price_data[-2] > prev_low:
        return "low_sweep"

    return None

# ================= BOT LOOP =================
def bot_loop():
    global current_trade, last_trade_time

    while True:
        try:
            price = get_price()

            if price:
                price_data.append(price)
                if len(price_data) > 100:
                    price_data.pop(0)

                log(f"📡 {price}")

                disp = displacement()
                sweep = liquidity_sweep()

                if bias and disp and sweep:

                    now = time.time()

                    if not current_trade and now - last_trade_time > COOLDOWN:

                        for z in zones[-5:]:

                            # Ignore weak zones
                            if z["type"] == "internal_ob":
                                continue

                            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                                # ===== BUY =====
                                if (
                                    bias == "buy"
                                    and z["trend"] == "bullish"
                                    and disp == "buy"
                                    and sweep == "low_sweep"
                                ):
                                    current_trade = {
                                        "side": "buy",
                                        "entry": price,
                                        "sl": price * 0.998,
                                        "be": False
                                    }
                                    last_trade_time = now
                                    log(f"🚀 BUY ({z['type']})")
                                    break

                                # ===== SELL =====
                                elif (
                                    bias == "sell"
                                    and z["trend"] == "bearish"
                                    and disp == "sell"
                                    and sweep == "high_sweep"
                                ):
                                    current_trade = {
                                        "side": "sell",
                                        "entry": price,
                                        "sl": price * 1.002,
                                        "be": False
                                    }
                                    last_trade_time = now
                                    log(f"🚀 SELL ({z['type']})")
                                    break

                # ================= EXIT =================
                if current_trade:
                    side = current_trade["side"]
                    entry = current_trade["entry"]
                    sl = current_trade["sl"]

                    risk = abs(entry - sl)
                    if risk == 0:
                        continue

                    r = (price - entry)/risk if side=="buy" else (entry - price)/risk

                    # Break even
                    if r >= 1 and not current_trade["be"]:
                        current_trade["sl"] = entry
                        current_trade["be"] = True
                        log("🔒 BE moved")

                    # Trailing
                    if r >= 2:
                        if side == "buy":
                            current_trade["sl"] = max(current_trade["sl"], price - risk)
                        else:
                            current_trade["sl"] = min(current_trade["sl"], price + risk)

                    # Exit
                    if (side=="buy" and price <= current_trade["sl"]) or (side=="sell" and price >= current_trade["sl"]):
                        log(f"✅ EXIT {round(r,2)}R")
                        current_trade = None

        except Exception as e:
            log(f"❌ ERROR {e}")

        time.sleep(2)

threading.Thread(target=bot_loop, daemon=True).start()

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

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="3"></head>
<body style="background:#0f172a;color:white;font-family:sans-serif">

<h2>🚀 BOT</h2>

<p><b>Bias:</b> {{bias}}</p>
<p><b>Trade:</b> {{trade}}</p>

<h3>Zones</h3>
{% for z in zones %}
<div>{{z.time}} | {{z.trend}} | {{z.type}} | {{z.price}}</div>
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
