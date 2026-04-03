# bot.py - Advanced SMC Automation Bot (Corrected Logic)

from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ---------- CONFIG ----------
RISK_PERCENT = 1
RR_RATIO = 2                # Risk:Reward (1:2)
TRAILING_AFTER_R = 1       # Start trailing after 1R move
ACCOUNT_BALANCE = 10000
# ----------------------------

# State
bias_map = {}          # CHoCH-based directional bias
bos_confirmed = {}     # BOS confirmation (optional strength)
active_trades = []

# ----------------- UTILS -----------------

def calculate_position_size(entry, sl):
    risk_amount = ACCOUNT_BALANCE * (RISK_PERCENT / 100)
    distance = abs(entry - sl)
    if distance == 0:
        return 0
    return risk_amount / distance

def get_sl_tp(entry, signal):
    # Basic structure-based placeholder (can be upgraded later)
    sl_percent = 0.4
    if signal == "buy":
        sl = entry - entry * sl_percent / 100
        tp = entry + (entry - sl) * RR_RATIO
    else:
        sl = entry + entry * sl_percent / 100
        tp = entry - (sl - entry) * RR_RATIO
    return sl, tp

def open_trade(symbol, signal, entry, zone):
    sl, tp = get_sl_tp(entry, signal)
    size = calculate_position_size(entry, sl)

    trade = {
        "symbol": symbol,
        "signal": signal,
        "zone": zone,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "position_size": size,
        "status": "open",
        "entry_time": str(datetime.now()),
        "moved_to_be": False
    }
    active_trades.append(trade)
    print(f"OPEN TRADE: {trade}")
    return trade

def manage_trade(trade, price):
    entry = trade["entry_price"]
    sl = trade["stop_loss"]
    tp = trade["take_profit"]

    risk = abs(entry - sl)
    current_profit = (price - entry) if trade["signal"] == "buy" else (entry - price)

    # Move SL to breakeven after 1R
    if not trade["moved_to_be"] and current_profit >= risk * TRAILING_AFTER_R:
        trade["stop_loss"] = entry
        trade["moved_to_be"] = True

    # Close at TP
    if (trade["signal"] == "buy" and price >= tp) or \
       (trade["signal"] == "sell" and price <= tp):
        trade["status"] = "closed"
        trade["exit_price"] = price
        trade["reason"] = "TP hit"

    # Close at SL
    elif (trade["signal"] == "buy" and price <= trade["stop_loss"]) or \
         (trade["signal"] == "sell" and price >= trade["stop_loss"]):
        trade["status"] = "closed"
        trade["exit_price"] = price
        trade["reason"] = "SL hit"

# ----------------- ENDPOINTS -----------------

@app.route("/")
def home():
    return jsonify({
        "status": "Advanced SMC Bot Running",
        "bias": bias_map,
        "bos_confirmed": bos_confirmed,
        "active_trades": len([t for t in active_trades if t["status"]=="open"])
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    symbol = data.get("symbol")
    raw_signal = (data.get("signal") or "").lower()
    price = data.get("price")
    zone = data.get("zone", None)
    trend = (data.get("trend") or "").lower()

    if not symbol or not raw_signal or price is None:
        return jsonify({"error":"invalid data"}), 400

    # Identify direction
    direction = "buy" if "bullish" in raw_signal else "sell"

    # ---------- CHOCH ----------
    if "choch" in raw_signal:
        bias_map[symbol] = direction
        bos_confirmed[symbol] = False
        return jsonify({"status":"bias set from CHoCH", "bias": direction})

    # ---------- BOS ----------
    if "bos" in raw_signal:
        bos_confirmed[symbol] = True
        return jsonify({"status":"bos confirmed", "symbol":symbol})

    # ---------- ENTRY (FVG / OB / SWING OB) ----------
    if "fvg" in raw_signal or "ob breakout" in raw_signal:
        if symbol not in bias_map:
            return jsonify({"status":"ignored","reason":"no CHOCH bias yet"})

        if bias_map[symbol] != direction:
            return jsonify({"status":"ignored","reason":"against bias"})

        # Optional: require BOS confirmation
        # if not bos_confirmed.get(symbol, False):
        #     return jsonify({"status":"ignored","reason":"no BOS confirmation"})

        trade = open_trade(symbol, direction, price, zone)
        return jsonify({"status":"trade taken", "trade":trade})

    return jsonify({"status":"ignored"})

@app.route("/update_price", methods=["POST"])
def update_price():
    data = request.json
    symbol = data.get("symbol")
    price = data.get("price")

    for trade in active_trades:
        if trade["symbol"] == symbol and trade["status"] == "open":
            manage_trade(trade, price)

    return jsonify({"status":"updated"})

@app.route("/trades")
def trades():
    return jsonify(active_trades)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
