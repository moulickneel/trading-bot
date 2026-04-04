from flask import Flask, request, jsonify
from datetime import datetime
import csv, os

app = Flask(__name__)

# ---------- CONFIG ----------
RISK_PERCENT = 1
RR_RATIO = 2
MIN_RR = 1.5
ACCOUNT_BALANCE = 10000
BUFFER_PERCENT = 0.1
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

# ----------------- PRICE TRACKING -----------------

def update_price_history(symbol, price):
    if symbol not in price_history:
        price_history[symbol] = []
    price_history[symbol].append(price)
    if len(price_history[symbol]) > 20:
        price_history[symbol].pop(0)

def get_swing_levels(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 5:
        return None, None
    return min(prices[-5:]), max(prices[-5:])

# ----------------- LIQUIDITY LOGIC -----------------

def detect_liquidity_sweep(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 6:
        return False

    recent = prices[-6:]
    swing_low = min(recent[:-1])
    swing_high = max(recent[:-1])
    last_price = recent[-1]

    if direction == "buy":
        return last_price > swing_low and min(recent) < swing_low

    if direction == "sell":
        return last_price < swing_high and max(recent) > swing_high

    return False

def is_good_pullback(symbol, entry):
    prices = price_history.get(symbol, [])
    if len(prices) < 5:
        return False

    recent_high = max(prices[-5:])
    recent_low = min(prices[-5:])

    return recent_low < entry < recent_high

def already_in_trade(symbol, direction):
    for t in active_trades:
        if t["symbol"] == symbol and t["direction"] == direction and t["status"] == "open":
            return True
    return False

# ----------------- POSITION SIZING -----------------

def calculate_position_size(entry, sl):
    risk_amt = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    dist = abs(entry - sl)
    if dist <= 0:
        return None
    return risk_amt / dist

# ----------------- SL CALCULATION -----------------

def calculate_sl(symbol, direction, entry):
    swing_low, swing_high = get_swing_levels(symbol)

    if swing_low is None:
        return None

    buffer = entry * (BUFFER_PERCENT / 100)

    if direction == "buy":
        return swing_low - buffer
    else:
        return swing_high + buffer

# ----------------- TRADE ENGINE -----------------

def open_trade(symbol, direction, entry, zone):
    sl = calculate_sl(symbol, direction, entry)

    if sl is None:
        return None, "Not enough data for SL"

    if direction == "buy" and sl >= entry:
        return None, "Invalid SL"
    if direction == "sell" and sl <= entry:
        return None, "Invalid SL"

    size = calculate_position_size(entry, sl)
    if not size:
        return None, "Invalid position size"

    risk = abs(entry - sl)
    tp = entry + risk * RR_RATIO if direction == "buy" else entry - risk * RR_RATIO

    rr = abs(tp - entry) / risk
    if rr < MIN_RR:
        return None, "RR too low"

    trade = {
        "symbol": symbol,
        "direction": direction,
        "zone": zone,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "position_size": size,
        "status": "open",
        "entry_time": str(datetime.now()),
        "partial_closed": False,
        "breakeven": False
    }

    active_trades.append(trade)
    print(f"OPEN → {trade}")
    return trade, None

def close_trade(trade, price, reason):
    trade["status"] = "closed"
    trade["exit_price"] = price
    trade["exit_time"] = str(datetime.now())
    trade["reason"] = reason
    log_trade(trade)
    print(f"CLOSE → {trade}")

def manage_trade(trade, price):
    entry = trade["entry_price"]
    sl = trade["stop_loss"]
    tp = trade["take_profit"]

    risk = abs(entry - sl)
    profit = (price - entry) if trade["direction"] == "buy" else (entry - price)

    # Partial profit at 1R
    if not trade["partial_closed"] and profit >= risk:
        trade["partial_closed"] = True
        print(f"PARTIAL → {trade['symbol']}")

    # Breakeven
    if not trade["breakeven"] and profit >= risk:
        trade["stop_loss"] = entry
        trade["breakeven"] = True
        print(f"BE → {trade['symbol']}")

    # TP
    if (trade["direction"] == "buy" and price >= tp) or \
       (trade["direction"] == "sell" and price <= tp):
        close_trade(trade, price, "TP")

    # SL
    elif (trade["direction"] == "buy" and price <= trade["stop_loss"]) or \
         (trade["direction"] == "sell" and price >= trade["stop_loss"]):
        close_trade(trade, price, "SL")

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "SMC Liquidity Bot Running",
        "bias": bias_map,
        "open_trades": len([t for t in active_trades if t["status"] == "open"])
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    symbol = data.get("symbol")
    raw_signal = (data.get("signal") or "").lower()
    price = data.get("price")
    zone = data.get("zone")
    timeframe = data.get("timeframe")

    if not symbol or not raw_signal or price is None or not timeframe:
        return jsonify({"error": "invalid payload"}), 400

    update_price_history(symbol, price)

    direction = "buy" if "bullish" in raw_signal else "sell"

    # -------- HTF --------
    if timeframe == "HTF":
        if "choch" in raw_signal:
            bias_map[symbol] = direction
            bos_map[symbol] = False
            return jsonify({"status": "bias set"})

        if "bos" in raw_signal:
            bos_map[symbol] = True
            return jsonify({"status": "bos confirmed"})

    # -------- LTF ENTRY --------
    if timeframe == "LTF":
        if "fvg" in raw_signal or "ob breakout" in raw_signal:

            if symbol not in bias_map:
                return jsonify({"status": "ignored", "reason": "no bias"})

            if bias_map[symbol] != direction:
                return jsonify({"status": "ignored", "reason": "against bias"})

            if already_in_trade(symbol, direction):
                return jsonify({"status": "ignored", "reason": "trade exists"})

            if not detect_liquidity_sweep(symbol, direction):
                return jsonify({"status": "ignored", "reason": "no sweep"})

            if not is_good_pullback(symbol, price):
                return jsonify({"status": "ignored", "reason": "bad pullback"})

            trade, err = open_trade(symbol, direction, price, zone)

            if err:
                return jsonify({"status": "rejected", "reason": err})

            return jsonify({"status": "executed", "trade": trade})

    return jsonify({"status": "ignored"})

@app.route("/update_price", methods=["POST"])
def update_price():
    data = request.json
    symbol = data.get("symbol")
    price = data.get("price")

    update_price_history(symbol, price)

    for trade in active_trades:
        if trade["symbol"] == symbol and trade["status"] == "open":
            manage_trade(trade, price)

    return jsonify({"status": "updated"})

@app.route("/trades")
def trades():
    return jsonify(active_trades)

# ----------------- RUN -----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
