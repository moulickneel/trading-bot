from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0

trade_history = []
log_buffer = []

COOLDOWN = 180
ZONE_TOLERANCE = 0.005  # 🔥 increased

MAX_AGE_FVG = 8
MAX_AGE_OB = 15

# ================= LOG =================
def log(msg):
    try:
        entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(entry, flush=True)
        log_buffer.append(entry)
        if len(log_buffer) > 200:
            log_buffer.pop(0)
    except:
        pass

# ================= STATS =================
def stats():
    try:
        total = len(trade_history)
        wins = sum(1 for t in trade_history if t.get("result") == "win")
        pnl = sum(t.get("pnl", 0) for t in trade_history)
        winrate = (wins / total * 100) if total else 0
        return total, round(winrate,2), round(pnl,2)
    except:
        return 0,0,0

# ================= PRICE =================
def get_price():
    apis = [
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    ]

    for url in apis:
        try:
            res = requests.get(url, timeout=3)
            data = res.json()

            if "data" in data:
                return float(data["data"]["amount"])
            if "bitcoin" in data:
                return float(data["bitcoin"]["usd"])

        except Exception as e:
            log(f"⚠️ API fail: {e}")
            continue

    return None

# ================= DISPLACEMENT =================
def displacement_candle():
    if len(price_data) < 6:
        return None

    c1, c2, c3, c4 = price_data[-1], price_data[-2], price_data[-3], price_data[-4]

    high_curr = max(c1, c2)
    low_curr = min(c1, c2)

    high_prev = max(c3, c4)
    low_prev = min(c3, c4)

    if high_curr > high_prev and low_curr > low_prev and c1 > high_prev:
        return "buy"

    if high_curr < high_prev and low_curr < low_prev and c1 < low_prev:
        return "sell"

    return None

# ================= ZONE FILTER =================
def get_valid_zones(price):
    valid = []
    for z in zones[:]:
        try:
            age = len(price_data) - z["index"]

            if "fvg" in z["type"] and age > MAX_AGE_FVG:
                zones.remove(z)
                continue
            if "swing_ob" in z["type"] and age > MAX_AGE_OB:
                zones.remove(z)
                continue

            if abs(price - z["price"]) < price * ZONE_TOLERANCE:
                zones.remove(z)
                log(f"💥 Mitigated {z['type']}")
                continue

            valid.append(z)
        except:
            continue

    return valid

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time

    try:
        price_data.append(price)
        if len(price_data) > 50:
            price_data.pop(0)

        log(f"📡 Price: {price}")

        htf = bias.get(symbol)
        if not htf:
            return

        valid_zones = get_valid_zones(price)

        now = time.time()

        if not current_trade and (now - last_trade_time > COOLDOWN):

            decision = None
            trade_type = None
            disp = displacement_candle()

            # ===== SCALP =====
            for z in reversed(valid_zones[-5:]):
                if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                    if htf == "buy" and "bullish" in z["type"] and disp == "buy":
                        decision = "buy"
                        trade_type = "scalp"
                        log(f"🔵 SCALP BUY ({z['type']})")
                        break

                    elif htf == "sell" and "bearish" in z["type"] and disp == "sell":
                        decision = "sell"
                        trade_type = "scalp"
                        log(f"🔵 SCALP SELL ({z['type']})")
                        break

            # ===== RUNNER =====
            if not decision:
                if htf == "buy" and disp == "buy":
                    decision = "buy"
                    trade_type = "runner"
                    log("🔴 RUNNER BUY")

                elif htf == "sell" and disp == "sell":
                    decision = "sell"
                    trade_type = "runner"
                    log("🔴 RUNNER SELL")

            if not decision:
                return

            risk = max(price * 0.001, 1)
            sl = price - risk if decision == "buy" else price + risk

            current_trade = {
                "side": decision,
                "entry": price,
                "sl": sl,
                "type": trade_type,
                "display_time": time.strftime('%H:%M:%S'),
                "timestamp": time.time(),
                "be_moved": False
            }

            last_trade_time = now

            log(f"🚀 {decision.upper()} [{trade_type}]")

        # ===== EXIT =====
        if current_trade:
            side = current_trade["side"]
            entry = current_trade["entry"]
            sl = current_trade["sl"]

            risk = abs(entry - sl)
            if risk == 0:
                return

            r = (price - entry)/risk if side=="buy" else (entry - price)/risk

            if current_trade["type"] == "scalp":
                tp = entry + risk*1.5 if side=="buy" else entry - risk*1.5

                if (side=="buy" and price >= tp) or (side=="sell" and price <= tp):
                    current_trade["result"]="win"
                    current_trade["pnl"]=1.5
                    trade_history.append(current_trade)
                    log("✅ SCALP TP")
                    current_trade=None

                elif (side=="buy" and price <= sl) or (side=="sell" and price >= sl):
                    current_trade["result"]="loss"
                    current_trade["pnl"]=-1
                    trade_history.append(current_trade)
                    log("❌ SCALP SL")
                    current_trade=None

            else:
                if r >= 1.5 and not current_trade["be_moved"]:
                    current_trade["sl"] = entry
                    current_trade["be_moved"] = True
                    log("🔒 BE moved")

                if r >= 2:
                    if side=="buy":
                        current_trade["sl"] = max(current_trade["sl"], price - risk)
                    else:
                        current_trade["sl"] = min(current_trade["sl"], price + risk)

                if (side=="buy" and price <= current_trade["sl"]) or (side=="sell" and price >= current_trade["sl"]):
                    current_trade["result"]="win" if r>0 else "loss"
                    current_trade["pnl"]=round(r,2)
                    trade_history.append(current_trade)
                    log(f"EXIT RUNNER {round(r,2)}R")
                    current_trade=None

    except Exception as e:
        log(f"❌ CORE ERROR: {e}")

# ================= LOOP =================
def price_loop():
    while True:
        try:
            price = get_price()
            if price:
                on_price_update(price)
            else:
                log("⚠️ Price unavailable")
        except Exception as e:
            log(f"❌ LOOP ERROR: {e}")
        time.sleep(2)

threading.Thread(target=price_loop, daemon=True).start()

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json or {}
        log(f"📩 {data}")

        price = float(data.get("price",0))
        signal = str(data.get("signal","")).lower()
        trend = str(data.get("trend","")).lower()
        tf = str(data.get("timeframe","")).lower()

        if tf == "htf":
            if "bos" in signal and "internal" not in signal:
                bias[symbol] = "buy" if "bullish" in signal else "sell"
                log(f"🎯 HTF {bias[symbol]}")

        if tf == "ltf":
            if "swing ob" in signal or "fvg" in signal:
                zone = ("bullish_" if "bullish" in trend else "bearish_") + ("swing_ob" if "ob" in signal else "fvg")
                zones.append({
                    "type": zone,
                    "price": price,
                    "time": time.strftime('%H:%M:%S'),
                    "index": len(price_data)
                })
                log(f"📍 Zone {zone}")

        return {"ok": True}
    except Exception as e:
        log(f"❌ WEBHOOK ERROR: {e}")
        return {"error": str(e)}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white;font-family:sans-serif">
<h2>🚀 BTC BOT</h2>

<p><b>Bias:</b> {{bias}}</p>
<p><b>Active:</b> {{trade}}</p>
<p><b>Trades:</b> {{t}} | <b>Winrate:</b> {{wr}}% | <b>PnL:</b> {{pnl}}R</p>

<h3>📍 Zones</h3>
{% for z in zones %}
<div>{{z.time}} | {{z.type}} | {{z.price}}</div>
{% endfor %}

<h3>📊 Trades</h3>
{% for t in hist %}
<div>{{t.display_time}} | {{t.side}} | {{t.type}} | {{t.result}} | {{t.pnl}}R</div>
{% endfor %}

<h3>📜 Logs</h3>
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
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        zones=zones[-10:],
        t=t, wr=wr, pnl=pnl
    )

@app.route('/health')
def health():
    return {"status":"ok"}

@app.route('/')
def home():
    return {"status":"running"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
