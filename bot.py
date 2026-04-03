# bot.py - Fully Automated SMC Paper Trading Bot for LuxAlgo Alerts
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ---------- CONFIG ----------
RISK_PERCENT = 1          # Risk per trade (%)
TRAILING_SL_PERCENT = 0.5 # Trailing stop-loss distance (%)
ACCOUNT_BALANCE = 10000   # Simulated balance
# -----------------------------

current_trend = {}  # confirmed trend per symbol
pending_chos = {}   # pending early reversal trades
active_trades = []

# ----------------- UTILITY FUNCTIONS -----------------
def calculate_position_size(account_balance, entry_price, stop_loss_price, risk_percent):
    risk_amount = account_balance * (risk_percent / 100)
    distance = abs(entry_price - stop_loss_price)
    if distance == 0:
        return 0
    return risk_amount / distance

def open_trade(symbol, signal, entry_price, stop_loss, entry_type, zone=None, take_profit=None):
    position_size = calculate_position_size(ACCOUNT_BALANCE, entry_price, stop_loss, RISK_PERCENT)
    trade = {
        "timestamp": str(datetime.now()),
        "symbol": symbol,
        "signal": signal,
        "entry_type": entry_type,
        "zone": zone,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_size": position_size,
        "status": "open",
        "highest_price": entry_price if signal == "buy" else None,
        "lowest_price": entry_price if signal == "sell" else None
    }
    active_trades.append(trade)
    print(f"--- PAPER TRADE OPENED ---\n{trade}\n--------------------------")
    return trade

def update_trailing_stop(trade, current_price, trailing_percent):
    if trade["signal"] == "buy":
        if current_price > trade["highest_price"]:
            trade["highest_price"] = current_price
            new_sl = current_price - current_price * trailing_percent / 100
            if new_sl > trade["stop_loss"]:
                trade["stop_loss"] = new_sl
    elif trade["signal"] == "sell":
        if current_price < trade["lowest_price"]:
            trade["lowest_price"] = current_price
            new_sl = current_price + current_price * trailing_percent / 100
            if new_sl < trade["stop_loss"]:
                trade["stop_loss"] = new_sl

# ----------------- STRUCTURE SL/TP -----------------
def get_sl_tp(entry_price, zone, signal):
    """
    Returns SL/TP based on zone
    FVG: SL below/above gap, TP at next structure
    OB: SL below/above OB, TP at next structure
    Swing OB: similar to OB
    Currently using % placeholders
    """
    sl_percent = 0.5
    tp_percent = 1.0
    if signal == "buy":
        sl = entry_price - entry_price * sl_percent / 100
        tp = entry_price + entry_price * tp_percent / 100
    else:
        sl = entry_price + entry_price * sl_percent / 100
        tp = entry_price - entry_price * tp_percent / 100
    return sl, tp

# ----------------- ENDPOINTS -----------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "SMC Bot Running",
        "active_trades": len([t for t in active_trades if t["status"]=="open"]),
        "confirmed_trends": current_trend,
        "pending_chos": pending_chos
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    symbol = data.get("symbol")
    raw_signal = (data.get("signal") or "").lower()
    price = data.get("price")
    zone = data.get("zone")
    trend = (data.get("trend") or "").lower()

    if not symbol or not raw_signal or price is None or not trend:
        return jsonify({"status":"error","reason":"missing fields"}),400

    # Determine type of signal
    signal = None
    entry_type = None
    trend_confirm = None

    # CHoCH signals - early reversal
    if "choch" in raw_signal:
        signal = "buy" if "bullish" in raw_signal else "sell"
        entry_type = "primary"
        trend_confirm = False
    # BOS signals - trend confirmation
    elif "bos" in raw_signal:
        signal = "buy" if "bullish" in raw_signal else "sell"
        entry_type = "primary"
        trend_confirm = True
    # OB Breakouts or FVG - secondary entries
    elif "ob breakout" in raw_signal or "fvg" in raw_signal:
        signal = "buy" if "bullish" in raw_signal else "sell"
        entry_type = "secondary"
        trend_confirm = None
    else:
        return jsonify({"status":"ignored","reason":"unknown signal"}),200

    # ---- Handle CHoCH ----
    if trend_confirm == False:
        pending_chos[symbol] = {
            "signal": signal,
            "zone": zone,
            "entry_type": entry_type,
            "price": price,
            "timestamp": str(datetime.now())
        }
        return jsonify({"status":"CHoCH recorded","symbol":symbol,"signal":signal})

    # ---- Handle BOS ----
    if trend_confirm == True:
        current_trend[symbol] = signal
        # If pending CHoCH exists, execute it
        if symbol in pending_chos:
            choch = pending_chos.pop(symbol)
            sl, tp = get_sl_tp(choch["price"], choch["zone"], choch["signal"])
            trade = open_trade(symbol, choch["signal"], choch["price"], sl, choch["entry_type"], choch["zone"], tp)
            return jsonify({"status":"trend confirmed, CHoCH trade executed","trade":trade})
        return jsonify({"status":"trend updated","symbol":symbol,"trend":signal})

    # ---- Secondary entries ----
    # Ignore if trend not confirmed
    if symbol not in current_trend:
        return jsonify({"status":"ignored","reason":"trend not confirmed yet"})
    if (signal=="buy" and current_trend[symbol]!="buy") or (signal=="sell" and current_trend[symbol]!="sell"):
        return jsonify({"status":"ignored","reason":"signal against confirmed trend"})

    sl, tp = get_sl_tp(price, zone, signal)
    trade = open_trade(symbol, signal, price, sl, entry_type, zone, tp)
    return jsonify({"status":"trade executed","trade":trade})

@app.route("/update_price", methods=["POST"])
def update_price():
    data = request.json
    symbol = data.get("symbol")
    current_price = data.get("price")
    if not symbol or current_price is None:
        return jsonify({"status":"error","reason":"missing fields"}),400

    for trade in active_trades:
        if trade["symbol"]==symbol and trade["status"]=="open":
            update_trailing_stop(trade, current_price, TRAILING_SL_PERCENT)
            # Close on stop-loss
            if (trade["signal"]=="buy" and current_price<=trade["stop_loss"]) or \
               (trade["signal"]=="sell" and current_price>=trade["stop_loss"]):
                trade["status"]="closed"
                trade["exit_price"]=current_price
                trade["closed_at"]=str(datetime.now())
                trade["reason"]="stop_loss hit"
            # Close on take-profit
            elif (trade["signal"]=="buy" and current_price>=trade["take_profit"]) or \
                 (trade["signal"]=="sell" and current_price<=trade["take_profit"]):
                trade["status"]="closed"
                trade["exit_price"]=current_price
                trade["closed_at"]=str(datetime.now())
                trade["reason"]="take_profit hit"
    return jsonify({"status":"prices updated","symbol":symbol})

@app.route("/trades", methods=["GET"])
def get_trades():
    return jsonify({
        "total_trades": len(active_trades),
        "open_trades": len([t for t in active_trades if t["status"]=="open"]),
        "closed_trades": len([t for t in active_trades if t["status"]=="closed"]),
        "trades": active_trades,
        "confirmed_trends": current_trend,
        "pending_chos": pending_chos
    })

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000)
