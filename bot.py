from flask import Flask, request, jsonify
from datetime import datetime
import csv, os, sys

app = Flask(__name__)

print("🔥 NEW BOT VERSION LOADED 🔥")
sys.stdout.flush()

# ---------- CONFIG ----------
ACCOUNT_BALANCE = 10000
RISK_PERCENT = 1
BUFFER_PERCENT = 0.1
LOG_FILE = "trade_log.csv"
COOLDOWN_SECONDS = 60
DEBUG = True
# ----------------------------

bias_map = {}
price_history = {}
active_trades = []
last_trade_time = {}

# ----------------- DEBUG -----------------

def log(msg):
    if DEBUG:
        print(f"[{datetime.now()}] {msg}")
        sys.stdout.flush()

# ----------------- PRICE -----------------

def update_price(symbol, price):
    if symbol not in price_history:
        price_history[symbol] = []
    price_history[symbol].append(price)
    if len(price_history[symbol]) > 100:
        price_history[symbol].pop(0)

# ----------------- VOLATILITY -----------------

def get_volatility(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return 1
    moves = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    return sum(moves[-10:]) / 10

# ----------------- ENTRY LOGIC -----------------

def auto_entry(symbol):

    log(f"--- AUTO ENTRY CHECK: {symbol} ---")

    if symbol not in bias_map:
        log("❌ No HTF bias")
        return None

    direction = bias_map[symbol]
    prices = price_history.get(symbol, [])

    if len(prices) < 10:
        log("❌ Not enough price data")
        return None

    price = prices[-1]
    vol = get_volatility(symbol)

    log(f"Bias: {direction}")
    log(f"Price: {price}, Volatility: {vol}")

    # Simple momentum detection
    last, prev = prices[-1], prices[-2]
    momentum = abs(last - prev) > vol * 0.5

    log(f"Momentum: {momentum}")

    # Simple trend direction
    trend_up = prices[-1] > prices[-2] > prices[-3]
    trend_down = prices[-1] < prices[-2] < prices[-3]

    log(f"Trend Up: {trend_up}, Trend Down: {trend_down}")

    # ENTRY CONDITIONS (RELAXED)
    if direction == "buy":
        if momentum and trend_up:
            log("✅ BUY ENTRY TRIGGERED")
            return "buy", "momentum"

    if direction == "sell":
        if momentum and trend_down:
            log("✅ SELL ENTRY TRIGGERED")
            return "sell", "momentum"

    log("❌ No valid entry condition")
    return None

# ----------------- SL/TP -----------------

def calculate_sl(symbol, direction, entry):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return None

    buffer = entry * (BUFFER_PERCENT / 100)

    if direction == "buy":
        return min(prices[-10:]) - buffer
    else:
        return max(prices[-10:]) + buffer

def calculate_size(entry, sl):
    risk_amt = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    dist = abs(entry - sl)
    if dist == 0:
        return None
    return round(risk_amt / dist, 3)

# ----------------- TRADE -----------------

def open_trade(symbol, direction, entry, entry_type):

    now = datetime.now()
    last_time = last_trade_time.get(symbol)

    if last_time and (now - last_time).seconds < COOLDOWN_SECONDS:
        log("❌ Cooldown active")
        return None

    last_trade_time[symbol] = now

    sl = calculate_sl(symbol, direction, entry)
    if not sl:
        log("❌ SL failed")
        return None

    size = calculate_size(entry, sl)
    if not size:
        log("❌ Size failed")
        return None

    risk = abs(entry - sl)
    tp = entry + risk * 2 if direction == "buy" else entry - risk * 2

    trade = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "size": size,
        "status": "open",
        "time": str(datetime.now())
    }

    active_trades.append(trade)
    log(f"🚀 TRADE OPENED → {trade}")
    return trade

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "DEBUG BOT RUNNING",
        "bias": bias_map,
        "open_trades": len(active_trades)
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    log(f"📩 WEBHOOK RECEIVED → {data}")

    symbol = data.get("symbol")
    signal = (data.get("signal") or "").lower()
    price = data.get("price")
    timeframe = data.get("timeframe")

    if not symbol or not signal or price is None:
        log("❌ Invalid webhook")
        return jsonify({"error": "invalid"}), 400

    update_price(symbol, price)

    direction = "buy" if "bullish" in signal else "sell"

    if timeframe == "HTF":
        if "bos" in signal or "choch" in signal:
            bias_map[symbol] = direction
            log(f"🎯 BIAS SET → {symbol}: {direction}")

    return jsonify({"status": "ok"})

@app.route("/update_price", methods=["POST"])
def update_price_route():
    data = request.json

    symbol = data.get("symbol")
    price = data.get("price")

    log(f"💰 PRICE UPDATE → {symbol} @ {price}")

    update_price(symbol, price)

    entry = auto_entry(symbol)

    if entry:
        direction, entry_type = entry
        trade = open_trade(symbol, direction, price, entry_type)
        if not trade:
            log("❌ Trade execution failed")
    else:
        log("❌ No entry signal")

    return jsonify({"status": "updated"})

@app.route("/debug")
def debug():
    return jsonify({
        "bias": bias_map,
        "price_points": {k: len(v) for k, v in price_history.items()},
        "active_trades": active_trades
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
