from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0
last_bias_trade = None

trade_history = []
log_buffer = []

COOLDOWN = 180
ZONE_TOLERANCE = 0.003

MAX_AGE_FVG = 8
MAX_AGE_OB = 15

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

# ================= PRICE =================
def get_price():
    apis = [
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    ]

    for url in apis:
        try:
            res = requests.get(url, timeout=4).json()
            if "data" in res:
                return float(res["data"]["amount"])
            if "price" in res:
                return float(res["price"])
            if "bitcoin" in res:
                return float(res["bitcoin"]["usd"])
        except:
            continue
    return None

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

    return valid

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time, last_bias_trade

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 {price}")

    structure = get_structure()
    if not structure:
        return

    htf = bias.get(symbol)
    if not htf:
        return

    valid_zones = get_valid_zones(price)

    now = time.time()

    if not current_trade and (now - last_trade_time > COOLDOWN):

        if htf == last_bias_trade:
            return

        decision = None
        trade_type = None

        disp = displacement_candle()

        # ===== SCALP =====
        for z in reversed(valid_zones[-5:]):

            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                if htf == "buy" and structure == "up" and "bullish" in z["type"]:
                    if disp == "buy":
                        decision = "buy"
                        trade_type = "scalp"
                        log(f"🔵 SCALP BUY {z['type']}")
                        break

                elif htf == "sell" and structure == "down" and "bearish" in z["type"]:
                    if disp == "sell":
                        decision = "sell"
                        trade_type = "scalp"
                        log(f"🔵 SCALP SELL {z['type']}")
                        break

        # ===== RUNNER =====
        if not decision:
            if htf == "buy" and structure == "up" and disp == "buy":
                decision = "buy"
                trade_type = "runner"

            elif htf == "sell" and structure == "down" and disp == "sell":
                decision = "sell"
                trade_type = "runner"

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
        last_bias_trade = htf

        log(f"🚀 {decision.upper()} {trade_type}")

    # ===== EXIT =====
    if current_trade:
        side = current_trade["side"]
        entry = current_trade["entry"]
        sl = current_trade["sl"]
        trade_type = current_trade["type"]

        risk = abs(entry - sl)
        r = (price - entry)/risk if side=="buy" else (entry - price)/risk

        if trade_type == "scalp":
            tp = entry + risk*1.5 if side=="buy" else entry - risk*1.5

            if (side=="buy" and price >= tp) or (side=="sell" and price <= tp):
                current_trade["result"]="win"
                current_trade["pnl"]=1.5
                trade_history.append(current_trade)
                current_trade=None

            elif (side=="buy" and price <= sl) or (side=="sell" and price >= sl):
                current_trade["result"]="loss"
                current_trade["pnl"]=-1
                trade_history.append(current_trade)
                current_trade=None

        else:
            if r >= 1.5 and not current_trade["be_moved"]:
                current_trade["sl"] = entry
                current_trade["be_moved"] = True

            if r >= 2:
                if side=="buy":
                    current_trade["sl"] = max(current_trade["sl"], price - risk)
                else:
                    current_trade["sl"] = min(current_trade["sl"], price + risk)

            if (side=="buy" and price <= current_trade["sl"]) or (side=="sell" and price >= current_trade["sl"]):
                current_trade["result"]="win" if r>0 else "loss"
                current_trade["pnl"]=round(r,2)
                trade_history.append(current_trade)
                current_trade=None

# ================= LOOP =================
def price_loop():
    while True:
        price = get_price()
        if price:
            on_price_update(price)
        time.sleep(2)

threading.Thread(target=price_loop, daemon=True).start()

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    log(f"📩 {data}")

    price = float(data.get("price",0))
    signal = str(data.get("signal","")).lower()
    trend = str(data.get("trend","")).lower()
    tf = str(data.get("timeframe","")).lower()

    if tf == "htf":
        if "bos" in signal and "internal" not in signal:
            bias[symbol] = "buy" if "bullish" in signal else "sell"
        elif "choch" in signal and "internal" not in signal:
            bias[symbol] = "buy" if "bullish" in signal else "sell"

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

# ================= DASHBOARD =================
@app.route('/dashboard')
def dash():
    t,wr,pnl = stats()
    return {
        "bias": bias,
        "active": current_trade,
        "zones": zones[-5:],
        "trades": t,
        "winrate": wr,
        "pnl": pnl
    }

@app.route('/')
def home():
    return {"status":"running"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
