from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC BOT (STABLE PRO VERSION) STARTED 🔥", flush=True)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0
last_bias_trade = None

trade_history = []

COOLDOWN = 180
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

# ================= PRICE API =================
def get_price():
    try:
        url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        res = requests.get(url, timeout=5).json()
        return float(res["data"]["amount"])
    except:
        log("⚠️ Coinbase failed")
        try:
            url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
            res = requests.get(url, timeout=5).json()
            log("🔁 Using Binance fallback")
            return float(res["price"])
        except:
            log("⚠️ Binance failed")
            try:
                url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
                res = requests.get(url, timeout=5).json()
                log("🔁 Using CoinGecko fallback")
                return float(res["bitcoin"]["usd"])
            except:
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

# ================= STRONG CANDLE =================
def strong_candle():
    if len(price_data) < 3:
        return None

    curr = price_data[-1]
    prev = price_data[-2]
    prev2 = price_data[-3]

    # BUY: HH + HL structure
    if curr > prev and prev > prev2:
        return "buy"

    # SELL: LL + LH structure
    if curr < prev and prev < prev2:
        return "sell"

    return None

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time, last_bias_trade

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 Price: {price}")

    structure = get_structure()
    if not structure:
        return

    htf = bias.get(symbol)
    if not htf:
        return

    log(f"HTF: {htf} | Structure: {structure}")

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and (now - last_trade_time > COOLDOWN):

        if htf == last_bias_trade:
            log("⛔ Already traded this trend")
            return

        decision = None
        trade_type = None

        if len(price_data) < 5:
            return

        p1, p2, p3, p4, p5 = price_data[-1], price_data[-2], price_data[-3], price_data[-4], price_data[-5]

        # -------- SCALP --------
        for z in reversed(zones[-5:]):
            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                if htf == "buy" and structure == "up" and "bullish" in z["type"]:
                    if p5 > p4 > p3 and p1 > p2 and strong_candle() == "buy":
                        decision = "buy"
                        trade_type = "scalp"
                        log("🔵 SCALP BUY")
                        break

                elif htf == "sell" and structure == "down" and "bearish" in z["type"]:
                    if p5 < p4 < p3 and p1 < p2 and strong_candle() == "sell":
                        decision = "sell"
                        trade_type = "scalp"
                        log("🔵 SCALP SELL")
                        break

        # -------- RUNNER --------
        if not decision:

            if htf == "buy" and structure == "up":
                if p5 > p4 > p3 and p1 > p2 and strong_candle() == "buy":
                    decision = "buy"
                    trade_type = "runner"
                    log("🔴 RUNNER BUY")

            elif htf == "sell" and structure == "down":
                if p5 < p4 < p3 and p1 < p2 and strong_candle() == "sell":
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
        last_bias_trade = htf

        log(f"🚀 {decision.upper()} [{trade_type}] @ {price}")

    # ================= EXIT =================
    if current_trade:
        side = current_trade["side"]
        entry = current_trade["entry"]
        sl = current_trade["sl"]
        trade_type = current_trade["type"]

        risk = max(abs(entry - sl), 1)
        r = (price - entry)/risk if side=="buy" else (entry - price)/risk

        # SCALP
        if trade_type == "scalp":
            tp = entry + risk*1.5 if side=="
