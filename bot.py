from flask import Flask, request, jsonify
from datetime import datetime
import csv, os

app = Flask(__name__)

# ---------- CONFIG ----------
RISK_PERCENT = 1
RR_RATIO = 2
PARTIAL_R = 1
ACCOUNT_BALANCE = 10000
LOG_FILE = "trade_log.csv"
# ----------------------------

bias_map = {}     # HTF bias (CHOCH)
bos_map = {}      # HTF confirmation
active_trades = []

# ----------------- LOGGING -----------------

def log_trade(trade):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=trade.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)

# ----------------- UTILS -----------------

def position_size(entry, sl):
    risk_amt = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    dist = abs(entry - sl)
    return 0 if dist == 0 else risk_amt / dist

def get_sl_tp(entry, direction):
    sl_percent = 0.4
    if direction == "buy":
        sl = entry - entry * sl_percent / 100
        tp = entry + (entry - sl) * RR_RATIO
    else:
        sl = entry + entry * sl_percent / 100
        tp = entry - (sl - entry) * RR_RATIO
    return sl, tp

# ----------------- TRADE ENGINE -----------------

def open_trade(symbol, direction, entry, zone):
    sl, tp = get_sl_tp(entry, direction)
    size = position_size(entry, sl)

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
        "breakeven_moved": False
    }

    active_trades.append(trade)
    print(f"OPEN TRADE → {trade}")
    return trade

def manage_trade(trade, price):
    entry = trade["entry_price"]
    sl = trade["stop_loss"]
    tp = trade["take_profit"]

    risk = abs(entry - sl)
    profit = (price - entry) if trade["direction"] == "buy" else (entry - price)

    # ---- Partial profit at 1R ----
    if not trade["partial_closed"] and profit >= risk * PARTIAL_R:
        trade["partial_closed"] = True
        print(f"PARTIAL CLOSED → {trade['symbol']}")

    # ---- Move SL to BE ----
    if not trade["breakeven_moved"] and profit >= risk:
        trade["stop_loss"] = entry
        trade["breakeven_moved"] = True
        print(f"BREAKEVEN SET → {trade['symbol']}")

    # ---- TP ----
    if (trade["direction"] == "buy" and price >= tp) or \
       (trade["direction"] == "sell" and price <= tp):
        close_trade(trade, price, "TP hit")

    # ---- SL ----
    elif (trade["direction"] == "buy" and price <= trade["stop_loss"]) or \
         (trade["direction"] == "sell" and price >= trade["stop_loss"]):
        close_trade(trade, price, "SL hit")

def close_trade(trade, price, reason):
    trade["status"] = "closed"
    trade["exit_price"] = price
    trade["exit_time"] = str(datetime.now())
    trade["reason"] = reason

    log_trade(trade)
    print(f"CLOSED TRADE → {trade}")

# ----------------- ROUTES -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "Institutional SMC Bot Running",
        "bias": bias_map,
        "bos": bos_map,
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

    direction = "buy" if "bullish" in raw_signal else "sell"

    # -------- HTF LOGIC --------
    if timeframe == "HTF":
        if "choch" in raw_signal:
            bias_map[symbol] = direction
            bos_map[symbol] = False
            return jsonify({"status": "HTF bias set", "bias": direction})

        if "bos" in raw_signal:
            bos_map[symbol] = True
            return jsonify({"status": "HTF BOS confirmed"})

    # -------- LTF ENTRY --------
    if timeframe == "LTF":
        if "fvg" in raw_signal or "ob breakout" in raw_signal:

            if symbol not in bias_map:
                return jsonify({"status": "ignored", "reason": "no HTF bias"})

            if bias_map[symbol] != direction:
                return jsonify({"status": "ignored", "reason": "against HTF bias"})

            trade = open_trade(symbol, direction, price, zone)
            return jsonify({"status": "trade executed", "trade": trade})

    return jsonify({"status": "ignored"})

@app.route("/update_price", methods=["POST"])
def update_price():
    data = request.json
    symbol = data.get("symbol")
    price = data.get("price")

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
