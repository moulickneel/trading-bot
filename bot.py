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
ltf_context = {}

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
    if len(price_history[symbol]) > 100:
        price_history[symbol].pop(0)

def get_recent_high_low(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 20:
        return None, None
    return min(prices[-20:]), max(prices[-20:])

# ----------------- VOLATILITY -----------------

def get_volatility(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 20:
        return None

    moves = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    recent = moves[-20:]

    return sum(recent) / len(recent)

# ----------------- MARKET STATE -----------------

def market_state(symbol):
    vol = get_volatility(symbol)
    prices = price_history.get(symbol, [])

    if not vol or len(prices) < 20:
        return "unknown"

    range_size = max(prices[-20:]) - min(prices[-20:])

    if range_size < vol * 5:
        return "ranging"

    return "trending"

# ----------------- SMART LOGIC -----------------

def detect_sweep(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 30:
        return False

    vol = get_volatility(symbol)
    if not vol:
        return False

    lookback = prices[-30:]
    swing_low = min(lookback[:-3])
    swing_high = max(lookback[:-3])
    current = prices[-1]
    recent = prices[-3:]

    buffer = vol * 0.5

    if direction == "buy":
        return current < (swing_low - buffer) and recent[-1] > swing_low

    if direction == "sell":
        return current > (swing_high + buffer) and recent[-1] < swing_high

    return False

def detect_momentum(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return False

    vol = get_volatility(symbol)
    if not vol:
        return False

    last, prev, prev2 = prices[-1], prices[-2], prices[-3]

    move = abs(last - prev)
    threshold = vol * 1.2
    expansion = abs(last - prev) > abs(prev - prev2)

    if move < threshold:
        return False

    return (last > prev and expansion) if direction == "buy" else (last < prev and expansion)

def strong_trend(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return False

    vol = get_volatility(symbol)
    if not vol:
        return False

    moves = [prices[i] - prices[i-1] for i in range(-6, -1)]

    strength = sum(m for m in moves if m > 0) if direction == "buy" else sum(abs(m) for m in moves if m < 0)

    return strength > (vol * 3)

def micro_trend(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 6:
        return None

    if prices[-1] > prices[-2] > prices[-3]:
        return "up"
    if prices[-1] < prices[-2] < prices[-3]:
        return "down"
    return "range"

def is_fake_breakout(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 6:
        return False

    return (prices[-1] > prices[-2] and prices[-2] < prices[-3]) if direction == "buy" else (prices[-1] < prices[-2] and prices[-2] > prices[-3])

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

    context = ltf_context.get(symbol, {})
    pullback_active = context.get("pullback", False)

    state = market_state(symbol)

    # ---- Pullback Mode ----
    if pullback_active:
        if sweep:
            return direction, "pullback_sweep"
        if momentum and micro == ("up" if direction == "buy" else "down"):
            return direction, "pullback_confirmation"
        return None

    # ---- Trending Market ----
    if state == "trending":
        if trend and micro == ("up" if direction == "buy" else "down"):
            return direction, "trend_continuation"

    # ---- Ranging Market ----
    if state == "ranging":
        return None

    # ---- Fallback ----
    if momentum:
        return direction, "momentum"

    return None

# ----------------- SL/TP -----------------

def calculate_sl(symbol, direction, entry):
    prices = price_history.get(symbol, [])
    if len(prices) < 20:
        return None

    buffer = entry * (BUFFER_PERCENT / 100)

    return min(prices[-20:]) - buffer if direction == "buy" else max(prices[-20:]) + buffer

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

    if rr >= 1 and not trade["breakeven_done"]:
        trade["sl"] = entry
        trade["breakeven_done"] = True

    if rr >= 1.5 and not trade["partial_closed"]:
        trade["partial_closed"] = True

    if rr >= 2:
        trade["trail_active"] = True

    if trade["trail_active"]:
        prices = price_history.get(trade["symbol"], [])
        if len(prices) >= 5:
            if direction == "buy":
                trade["sl"] = max(trade["sl"], min(prices[-5:]))
            else:
                trade["sl"] = min(trade["sl"], max(prices[-5:]))

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
        "status": "Adaptive SMC Bot Running",
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

    if timeframe == "LTF":

        if symbol not in ltf_context:
            ltf_context[symbol] = {"pullback": False, "last_signal": None}

        current_bias = bias_map.get(symbol)
        if not current_bias:
            return jsonify({"status": "no bias yet"})

        if direction != current_bias:
            ltf_context[symbol]["pullback"] = True
            ltf_context[symbol]["last_signal"] = signal
            print(f"PULLBACK → {symbol}")
        else:
            ltf_context[symbol]["pullback"] = False
            ltf_context[symbol]["last_signal"] = signal
            print(f"CONTINUATION → {symbol}")

    return jsonify({"status": "processed"})

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
    html += "<h2>Adaptive SMC Bot Dashboard</h2><table border=1 cellpadding=5>"
    html += "<tr><th>Symbol</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Status</th></tr>"

    for t in active_trades:
        html += f"<tr><td>{t['symbol']}</td><td>{t['direction']}</td><td>{t['entry']}</td><td>{t['sl']}</td><td>{t['tp']}</td><td>{t['status']}</td></tr>"

    html += "</table></body></html>"
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
