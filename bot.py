from flask import Flask, request, jsonify
from datetime import datetime
import csv, os

app = Flask(__name__)

# ---------- CONFIG ----------
ACCOUNT_BALANCE = 10000
RISK_PERCENT = 1
RR_RATIO = 2
BUFFER_PERCENT = 0.1
LOG_FILE = "trade_log.csv"
MAX_OPEN_TRADES = 1
# ----------------------------

bias_map = {}
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

# ----------------- PRICE -----------------

def update_price(symbol, price):
    if symbol not in price_history:
        price_history[symbol] = []
    price_history[symbol].append(price)
    if len(price_history[symbol]) > 50:
        price_history[symbol].pop(0)

def get_recent_high_low(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return None, None
    return min(prices[-10:]), max(prices[-10:])

# ----------------- SMART LOGIC -----------------

def detect_sweep(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 8:
        return False

    recent = prices[-8:]
    prev = recent[:-2]

    if direction == "buy":
        return min(recent) < min(prev) and recent[-1] > min(prev)
    else:
        return max(recent) > max(prev) and recent[-1] < max(prev)

def detect_momentum(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 5:
        return False

    last = prices[-1]
    prev = prices[-2]

    move = abs(last - prev)
    threshold = last * 0.001

    if move < threshold:
        return False

    return (last > prev) if direction == "buy" else (last < prev)

def micro_trend(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 6:
        return None

    if prices[-1] > prices[-2] > prices[-3]:
        return "up"
    if prices[-1] < prices[-2] < prices[-3]:
        return "down"
    return "range"

def strong_trend(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 8:
        return False

    seq = prices[-5:]
    return all(x < y for x, y in zip(seq, seq[1:])) if direction == "buy" else all(x > y for x, y in zip(seq, seq[1:]))

def is_fake_breakout(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 6:
        return False

    if direction == "buy":
        return prices[-1] > prices[-2] and prices[-2] < prices[-3]
    else:
        return prices[-1] < prices[-2] and prices[-2] > prices[-3]

def avoid_top_bottom(symbol, direction):
    low, high = get_recent_high_low(symbol)
    if low is None:
        return False

    price = price_history[symbol][-1]
    mid = (low + high) / 2

    return price < mid if direction == "buy" else price > mid

# ----------------- ENTRY ENGINE -----------------

def auto_entry(symbol):

    if symbol not in bias_map:
        return None

    direction = bias_map[symbol]

    if not avoid_top_bottom(symbol, direction):
        return None

    if is_fake_breakout(symbol, direction):
        return None

    sweep = detect_sweep(symbol, direction)
    momentum = detect_momentum(symbol, direction)
    trend = strong_trend(symbol, direction)
    micro = micro_trend(symbol)

    if sweep:
        return direction, "pullback"

    if trend and micro == ("up" if direction == "buy" else "down"):
        return direction, "trend_continuation"

    if momentum:
        return direction, "momentum"

    return None

# ----------------- SL/TP -----------------

def calculate_sl(symbol, direction, entry):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return None

    recent = prices[-10:]
    buffer = entry * (BUFFER_PERCENT / 100)

    return min(recent) - buffer if direction == "buy" else max(recent) + buffer

def calculate_size(symbol, entry, sl):
    risk_amt = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    dist = abs(entry - sl)

    if dist <= 0:
        return None

    units = risk_amt / dist
    return round(units / 100000, 3) if "USD" in symbol else round(units, 3)

# ----------------- TRADE -----------------

def open_trade(symbol, direction, entry, entry_type):

    if any(t for t in active_trades if t["symbol"] == symbol and t["status"] == "open"):
        return None

    sl = calculate_sl(symbol, direction, entry)
    if not sl:
        return None

    size = calculate_size(symbol, entry, sl)
    if not size:
        return None

    risk = abs(entry - sl)
    tp = entry + risk * RR_RATIO if direction == "buy" else entry - risk * RR_RATIO

    trade = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "size": size,
        "entry_type": entry_type,
        "status": "open",
        "entry_time": str(datetime.now()),
        "exit": None,
        "exit_time": None,
        "partial_closed": False,
        "breakeven_done": False,
        "trail_active": False
    }

    active_trades.append(trade)
    print("OPEN →", trade)
    return trade

def close_trade(trade, price, reason):
    trade["status"] = "closed"
    trade["exit"] = price
    trade["exit_time"] = str(datetime.now())
    trade["reason"] = reason
    log_trade(trade)
    print("CLOSE →", trade)

def manage_trade(trade, price):
    if trade["status"] != "open":
        return

    entry = trade["entry"]
    sl = trade["sl"]
    direction = trade["direction"]
    risk = abs(entry - sl)

    move = (price - entry) if direction == "buy" else (entry - price)
    rr = move / risk if risk else 0

    # Breakeven
    if rr >= 1 and not trade["breakeven_done"]:
        trade["sl"] = entry
        trade["breakeven_done"] = True
        print("BE SET")

    # Partial
    if rr >= 1.5 and not trade["partial_closed"]:
        trade["partial_closed"] = True
        print("PARTIAL CLOSED")

    # Trailing
    if rr >= 2:
        trade["trail_active"] = True

    if trade["trail_active"]:
        prices = price_history.get(trade["symbol"], [])
        if len(prices) >= 5:
            if direction == "buy":
                trade["sl"] = max(trade["sl"], min(prices[-5:]))
            else:
                trade["sl"] = min(trade["sl"], max(prices[-5:]))

    # Exit
    if direction == "buy":
        if price >= trade["tp"]:
            close_trade(trade, price, "TP")
        elif price <= trade["sl"]:
            close_trade(trade, price, "SL")

    else:
        if price <= trade["tp"]:
            close_trade(trade, price, "TP")
        elif price >= trade["sl"]:
            close_trade(trade, price, "SL")

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "Institutional SMC Bot Running",
        "bias": bias_map,
        "open_trades": len([t for t in active_trades if t["status"] == "open"])
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    symbol = data.get("symbol")
    signal = (data.get("signal") or "").lower()
    price = data.get("price")
    timeframe = data.get("timeframe")

    if not symbol or not signal or price is None or not timeframe:
        return jsonify({"error": "invalid payload"}), 400

    update_price(symbol, price)

    direction = "buy" if "bullish" in signal else "sell"

    if timeframe == "HTF":
        if "choch" in signal or "bos" in signal:
            bias_map[symbol] = direction
            print(f"BIAS → {symbol}: {direction}")
            return jsonify({"status": "bias updated"})

    return jsonify({"status": "ok"})

@app.route("/update_price", methods=["POST"])
def update_price_route():
    data = request.json
    symbol = data.get("symbol")
    price = data.get("price")

    update_price(symbol, price)

    for trade in active_trades:
        manage_trade(trade, price)

    entry = auto_entry(symbol)
    if entry:
        direction, entry_type = entry
        trade = open_trade(symbol, direction, price, entry_type)
        if trade:
            print("AUTO TRADE →", trade)

    return jsonify({"status": "updated"})

@app.route("/dashboard")
def dashboard():
    html = "<html><body style='background:#111;color:#eee;font-family:sans-serif'>"
    html += "<h2>SMC Bot Dashboard</h2><table border=1 cellpadding=5>"
    html += "<tr><th>Symbol</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Status</th></tr>"

    for t in active_trades:
        html += f"<tr><td>{t['symbol']}</td><td>{t['direction']}</td><td>{t['entry']}</td><td>{t['sl']}</td><td>{t['tp']}</td><td>{t['status']}</td></tr>"

    html += "</table></body></html>"
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
