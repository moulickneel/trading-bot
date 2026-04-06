from flask import Flask, request, jsonify
from datetime import datetime
import csv, os

app = Flask(__name__)

# ---------- CONFIG ----------
ACCOUNT_BALANCE = 10000
RISK_PERCENT = 1
RR_RATIO = 2
BUFFER_PERCENT = 0.1
MIN_RR = 1.2   # relaxed RR for flexibility
LOG_FILE = "trade_log.csv"
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

# ----------------- PRICE HISTORY -----------------

def update_price(symbol, price):
    if symbol not in price_history:
        price_history[symbol] = []
    price_history[symbol].append(price)
    if len(price_history[symbol]) > 50:
        price_history[symbol].pop(0)

def get_range(symbol):
    prices = price_history.get(symbol, [])
    if len(prices) < 10:
        return None, None
    return min(prices[-10:]), max(prices[-10:])

# ----------------- LIQUIDITY -----------------

def detect_sweep(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 8:
        return False

    recent = prices[-8:]
    prev = recent[:-2]

    swing_low = min(prev)
    swing_high = max(prev)
    last = recent[-1]

    if direction == "buy":
        return min(recent) < swing_low and last > swing_low

    if direction == "sell":
        return max(recent) > swing_high and last < swing_high

    return False

# ----------------- MOMENTUM (NEW) -----------------

def detect_momentum(symbol, direction):
    prices = price_history.get(symbol, [])
    if len(prices) < 5:
        return False

    last = prices[-1]
    prev = prices[-2]

    move = abs(last - prev)
    threshold = last * 0.001   # 0.1% move

    if move < threshold:
        return False

    if direction == "buy" and last > prev:
        return True

    if direction == "sell" and last < prev:
        return True

    return False

# ----------------- PREMIUM / DISCOUNT -----------------

def in_discount(symbol, price):
    low, high = get_range(symbol)
    if low is None:
        return False
    return price < (low + high) / 2

def in_premium(symbol, price):
    low, high = get_range(symbol)
    if low is None:
        return False
    return price > (low + high) / 2

# ----------------- SL -----------------

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

def calculate_size(symbol, entry, sl):
    risk_amt = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    dist = abs(entry - sl)

    if dist <= 0:
        return None

    units = risk_amt / dist

    if "USD" in symbol:
        return round(units / 100000, 3)

    return round(units, 3)

# ----------------- TRADE -----------------

def open_trade(symbol, direction, entry, zone, entry_type):

    sl = calculate_sl(symbol, direction, entry)
    if sl is None:
        return None, "No SL"

    size = calculate_size(symbol, entry, sl)
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
        "entry_type": entry_type,
        "status": "open",
        "entry_time": str(datetime.now()),
        "exit": None,
        "exit_time": None
    }

    active_trades.append(trade)
    print("OPEN →", trade)
    return trade, None

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

    if trade["direction"] == "buy":
        if price >= trade["tp"]:
            close_trade(trade, price, "TP")
        elif price <= trade["sl"]:
            close_trade(trade, price, "SL")

    elif trade["direction"] == "sell":
        if price <= trade["tp"]:
            close_trade(trade, price, "TP")
        elif price >= trade["sl"]:
            close_trade(trade, price, "SL")

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "Flexible SMC Bot Running",
        "bias": bias_map,
        "open_trades": len([t for t in active_trades if t["status"] == "open"])
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

    # HTF BIAS
    if timeframe == "HTF":
        if "choch" in signal or "bos" in signal:
            bias_map[symbol] = direction
            return jsonify({"status": "bias updated"})

    # LTF ENTRY
    if timeframe == "LTF":
        if "fvg" in signal or "ob breakout" in signal:

            if symbol not in bias_map:
                return jsonify({"status": "ignored", "reason": "no bias"})

            if bias_map[symbol] != direction:
                return jsonify({"status": "ignored", "reason": "against bias"})

            sweep = detect_sweep(symbol, direction)
            momentum = detect_momentum(symbol, direction)

            if not (sweep or momentum):
                return jsonify({"status": "ignored", "reason": "no entry condition"})

            if direction == "buy" and not (in_discount(symbol, price) or momentum):
                return jsonify({"status": "ignored", "reason": "bad zone"})

            if direction == "sell" and not (in_premium(symbol, price) or momentum):
                return jsonify({"status": "ignored", "reason": "bad zone"})

            entry_type = "pullback" if sweep else "momentum"

            trade, err = open_trade(symbol, direction, price, zone, entry_type)

            if err:
                return jsonify({"status": "rejected", "reason": err})

            return jsonify({"status": "executed", "type": entry_type, "trade": trade})

    return jsonify({"status": "ignored"})

@app.route("/update_price", methods=["POST"])
def update_price_route():
    data = request.json
    symbol = data.get("symbol")
    price = data.get("price")

    update_price(symbol, price)

    for trade in active_trades:
        manage_trade(trade, price)

    return jsonify({"status": "updated"})

@app.route("/dashboard")
def dashboard():

    total = len(active_trades)
    closed = [t for t in active_trades if t["status"] == "closed"]
    open_trades = [t for t in active_trades if t["status"] == "open"]

    wins = 0
    total_pnl = 0

    for t in closed:
        if t["direction"] == "buy":
            pnl = (t["exit"] - t["entry"]) * t["size"]
        else:
            pnl = (t["entry"] - t["exit"]) * t["size"]

        total_pnl += pnl
        if pnl > 0:
            wins += 1

    win_rate = (wins / len(closed) * 100) if closed else 0

    html = f"""
    <html>
    <head>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ background:#111; color:#eee; font-family:Arial; }}
            table {{ width:100%; border-collapse:collapse; }}
            th, td {{ padding:8px; border:1px solid #444; text-align:center; }}
            .win {{ color:lime; }}
            .loss {{ color:red; }}
        </style>
    </head>
    <body>

    <h2>📊 Trading Dashboard</h2>
    <p>Total: {total} | Open: {len(open_trades)} | Closed: {len(closed)} | Win Rate: {win_rate:.2f}% | PnL: {total_pnl:.2f}</p>

    <table>
    <tr><th>Symbol</th><th>Type</th><th>Dir</th><th>Entry</th><th>Exit</th><th>SL</th><th>TP</th><th>PnL</th></tr>
    """

    for t in active_trades:
        pnl = ""
        cls = ""

        if t["status"] == "closed":
            if t["direction"] == "buy":
                val = (t["exit"] - t["entry"]) * t["size"]
            else:
                val = (t["entry"] - t["exit"]) * t["size"]

            pnl = f"{val:.2f}"
            cls = "win" if val > 0 else "loss"

        html += f"<tr class='{cls}'><td>{t['symbol']}</td><td>{t.get('entry_type','')}</td><td>{t['direction']}</td><td>{t['entry']}</td><td>{t.get('exit','')}</td><td>{t['sl']}</td><td>{t['tp']}</td><td>{pnl}</td></tr>"

    html += "</table></body></html>"
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
