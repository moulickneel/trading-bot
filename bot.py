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

def get_range(symbol):
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
    prev = recent[:-2]

    swing_low = min(prev)
    swing_high = max(prev)
    last = recent[-1]

    if direction == "buy":
        return min(recent) < swing_low and last > swing_low

    if direction == "sell":
        return max(recent) > swing_high and last < swing_high

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

    # Forex-style lot handling
    if "USD" in symbol:
        return round(units / 100000, 3)

    return round(units, 3)

# ----------------- TRADE ENGINE -----------------

def open_trade(symbol, direction, entry, zone):

    sl = calculate_sl(symbol, direction, entry)
    if sl is None:
        return None, "No SL data"

    if direction == "buy" and sl >= entry:
        return None, "Invalid SL"

    if direction == "sell" and sl <= entry:
        return None, "Invalid SL"

    size = calculate_size(symbol, entry, sl)
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
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "size": size,
        "zone": zone,
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

    entry = trade["entry"]
    sl = trade["sl"]
    tp = trade["tp"]

    if trade["direction"] == "buy":
        if price >= tp:
            close_trade(trade, price, "TP")
        elif price <= sl:
            close_trade(trade, price, "SL")

    elif trade["direction"] == "sell":
        if price <= tp:
            close_trade(trade, price, "TP")
        elif price >= sl:
            close_trade(trade, price, "SL")

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "Institutional Bot Running",
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

    # HTF: Bias setting
    if timeframe == "HTF":
        if "choch" in signal or "bos" in signal:
            bias_map[symbol] = direction
            return jsonify({"status": "bias updated", "bias": direction})

    # LTF: Entry
    if timeframe == "LTF":
        if "fvg" in signal or "ob breakout" in signal:

            if symbol not in bias_map:
                return jsonify({"status": "ignored", "reason": "no bias"})

            if bias_map[symbol] != direction:
                return jsonify({"status": "ignored", "reason": "against bias"})

            if not detect_sweep(symbol, direction):
                return jsonify({"status": "ignored", "reason": "no liquidity sweep"})

            if direction == "buy" and not in_discount(symbol, price):
                return jsonify({"status": "ignored", "reason": "not in discount zone"})

            if direction == "sell" and not in_premium(symbol, price):
                return jsonify({"status": "ignored", "reason": "not in premium zone"})

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
        manage_trade(trade, price)

    return jsonify({"status": "updated"})

@app.route("/trades")
def trades():
    return jsonify(active_trades)

# ----------------- PRO DASHBOARD -----------------

@app.route("/dashboard")
def dashboard():

    total = len(active_trades)
    closed = [t for t in active_trades if t["status"] == "closed"]
    open_trades = [t for t in active_trades if t["status"] == "open"]

    wins = 0
    total_pnl = 0
    total_r = 0

    for t in closed:
        entry = t["entry"]
        exit_price = t["exit"]
        sl = t["sl"]

        risk = abs(entry - sl)

        if t["direction"] == "buy":
            pnl = (exit_price - entry) * t["size"]
        else:
            pnl = (entry - exit_price) * t["size"]

        total_pnl += pnl

        if pnl > 0:
            wins += 1
            total_r += abs(exit_price - entry) / risk
        else:
            total_r -= abs(exit_price - entry) / risk

    win_rate = (wins / len(closed) * 100) if closed else 0
    avg_r = (total_r / len(closed)) if closed else 0

    html = f"""
    <html>
    <head>
        <title>Pro Trading Dashboard</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ font-family: Arial; background: #0f172a; color: #e2e8f0; }}
            .card {{ display:inline-block; padding:15px; margin:10px;
                     background:#1e293b; border-radius:10px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top:20px;}}
            th, td {{ border: 1px solid #334155; padding: 8px; text-align:center;}}
            th {{ background: #1e293b; }}
            .win {{ color:#22c55e; }}
            .loss {{ color:#ef4444; }}
            .open {{ color:#38bdf8; }}
        </style>
    </head>
    <body>

    <h2>📊 Pro Trading Dashboard</h2>

    <div class="card">Total Trades: {total}</div>
    <div class="card">Open Trades: {len(open_trades)}</div>
    <div class="card">Closed Trades: {len(closed)}</div>
    <div class="card">Win Rate: {win_rate:.2f}%</div>
    <div class="card">Total PnL: {total_pnl:.2f}</div>
    <div class="card">Avg R: {avg_r:.2f}</div>

    <table>
        <tr>
            <th>Symbol</th>
            <th>Dir</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>SL</th>
            <th>TP</th>
            <th>Size</th>
            <th>PnL</th>
            <th>Status</th>
        </tr>
    """

    for t in active_trades:

        pnl = ""
        row_class = "open"

        if t["status"] == "closed":
            entry = t["entry"]
            exit_price = t["exit"]

            if t["direction"] == "buy":
                pnl_val = (exit_price - entry) * t["size"]
            else:
                pnl_val = (entry - exit_price) * t["size"]

            pnl = f"{pnl_val:.2f}"
            row_class = "win" if pnl_val > 0 else "loss"

        html += f"""
        <tr class="{row_class}">
            <td>{t['symbol']}</td>
            <td>{t['direction']}</td>
            <td>{t['entry']}</td>
            <td>{t.get('exit','')}</td>
            <td>{t['sl']}</td>
            <td>{t['tp']}</td>
            <td>{t['size']}</td>
            <td>{pnl}</td>
            <td>{t['status']}</td>
        </tr>
        """

    html += "</table></body></html>"

    return html

# ----------------- RUN -----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
