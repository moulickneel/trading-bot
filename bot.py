from flask import Flask, request, jsonify
from datetime import datetime
import csv, os

app = Flask(__name__)

# ---------- CONFIG ----------
ACCOUNT_BALANCE = 10000
RISK_PERCENT = 1
RR_RATIO = 2
BUFFER_PERCENT = 0.1
MIN_RR = 1.5
LOG_FILE = "trade_log.csv"
# ----------------------------

bias_map = {}
bos_map = {}
price_history = {}
active_trades = []

# ----------------- LOGGING -----------------

def log_trade(trade):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=trade.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)

# ----------------- PRICE HISTORY -----------------

def update_price(symbol, price):
    if symbol not in price_history:
        price_history[symbol] = []
    price_history[symbol].append(price)
    if len(price_history[symbol]) > 30:
        price_history[symbol].pop(0)

def get_recent_range(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return None, None
    return min(prices[-10:]), max(prices[-10:])

# ----------------- LIQUIDITY SWEEP -----------------

def detect_sweep(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 8:
        return False

    recent = prices[-8:]
    prev_range = recent[:-2]

    swing_low = min(prev_range)
    swing_high = max(prev_range)

    last = recent[-1]

    if direction == "buy":
        return min(recent) < swing_low and last > swing_low

    if direction == "sell":
        return max(recent) > swing_high and last < swing_high

    return False

# ----------------- PREMIUM / DISCOUNT -----------------

def in_discount_zone(symbol, price):
    low, high = get_recent_range(symbol)
    if low is None:
        return False
    equilibrium = (low + high) / 2
    return price < equilibrium

def in_premium_zone(symbol, price):
    low, high = get_recent_range(symbol)
    if low is None:
        return False
    equilibrium = (low + high) / 2
    return price > equilibrium

# ----------------- SL LOGIC -----------------

def calculate_sl(symbol, direction, entry):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return None

    recent = prices[-10:]
    buffer = entry * (BUFFER_PERCENT / 100)

    if direction == "buy":
        return min(recent) - buffer
    else:
        return max(recent) + buffer

# ----------------- POSITION SIZE -----------------

def calculate_position_size(symbol, entry, sl):
    risk_amount = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    distance = abs(entry - sl)

    if distance <= 0:
        return None

    units = risk_amount / distance

    # Adjust for asset class
    if "USD" in symbol:
        # Forex-like → convert to lots
        lot_size = units / 100000
        return round(lot_size, 3)

    return round(units, 3)

# ----------------- TRADE -----------------

def open_trade(symbol, direction, entry, zone):

    sl = calculate_sl(symbol, direction, entry)
    if sl is None:
        return None, "No SL data"

    if direction == "buy" and sl >= entry:
        return None, "Invalid SL"

    if direction == "sell" and sl <= entry:
        return None, "Invalid SL"

    size = calculate_position_size(symbol, entry, sl)
    if not size:
        return None, "Invalid size"

    risk = abs(entry - sl)
    tp = entry + risk * RR_RATIO if direction == "buy" else entry - risk * RR_RATIO

    rr = abs(tp - entry) / risk
    if rr < MIN_RR:
        return None, "RR too low"

    trade = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "size": size,
        "zone": zone,
        "status": "open",
        "entry_time": str(datetime.now()),
        "partial": False,
        "be": False
    }

    active_trades.append(trade)
    print(f"OPEN → {trade}")
    return trade, None

def manage_trade(trade, price):
    entry = trade["entry"]
    sl = trade["sl"]
    tp = trade["tp"]

    risk = abs(entry - sl)
    profit = (price - entry) if trade["direction"] == "buy" else (entry - price)

    if not trade["partial"] and profit >= risk:
        trade["partial"] = True

    if not trade["be"] and profit >= risk:
        trade["sl"] = entry
        trade["be"] = True

    if (trade["direction"] == "buy" and price >= tp) or \
       (trade["direction"] == "sell" and price <= tp):
        trade["status"] = "closed"
        trade["exit"] = price
        log_trade(trade)

    elif (trade["direction"] == "buy" and price <= trade["sl"]) or \
         (trade["direction"] == "sell" and price >= trade["sl"]):
        trade["status"] = "closed"
        trade["exit"] = price
        log_trade(trade)

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "Institutional Bot Running",
        "bias": bias_map,
        "open_trades": len([t for t in active_trades if t["status"]=="open"])
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    symbol = data.get("symbol")
    signal = (data.get("signal") or "").lower()
    price = data.get("price")
    zone = data.get("zone")
    timeframe = data.get("timeframe")

    if not symbol or not signal or price is None or not timeframe:
        return jsonify({"error": "invalid payload"}), 400

    update_price(symbol, price)

    direction = "buy" if "bullish" in signal else "sell"

    # HTF
    if timeframe == "HTF":
        if "choch" in signal:
            bias_map[symbol] = direction
            return jsonify({"status": "bias set"})

        if "bos" in signal:
            bias_map[symbol] = direction
            return jsonify({"status": "bos confirm"})

    # LTF ENTRY
    if timeframe == "LTF":
        if "fvg" in signal or "ob breakout" in signal:

            if symbol not in bias_map:
                return jsonify({"status": "ignored", "reason": "no bias"})

            if bias_map[symbol] != direction:
                return jsonify({"status": "ignored", "reason": "against bias"})

            # liquidity sweep required
            if not detect_sweep(symbol, direction):
                return jsonify({"status": "ignored", "reason": "no sweep"})

            # premium / discount filter
            if direction == "buy" and not in_discount_zone(symbol, price):
                return jsonify({"status": "ignored", "reason": "not discount"})

            if direction == "sell" and not in_premium_zone(symbol, price):
                return jsonify({"status": "ignored", "reason": "not premium"})

            trade, err = open_trade(symbol, direction, price, zone)

            if err:
                return jsonify({"status": "rejected", "reason": err})

            return jsonify({"status": "executed", "trade": trade})

    return jsonify({"status": "ignored"})

@app.route("/update_price", methods=["POST"])
def update_price_route():
    data = request.json
    symbol = data.get("symbol")
    price = data.get("price")

    update_price(symbol, price)

    for trade in active_trades:
        if trade["symbol"] == symbol and trade["status"] == "open":
            manage_trade(trade, price)

    return jsonify({"status": "updated"})

@app.route("/trades")
def trades():
    return jsonify(active_trades)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
