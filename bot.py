# bot.py - Paper Trading with Dynamic Trailing Stop, No Fixed TP
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ---------- CONFIG ----------
RISK_PERCENT = 1        # risk per trade (%)
TRAILING_SL_PERCENT = 0.5  # trailing stop-loss distance (%)
# -----------------------------

# Store trend by symbol
current_trend = {}
# Store active trades
active_trades = []

def calculate_position_size(account_balance, entry_price, stop_loss_price, risk_percent):
    risk_amount = account_balance * (risk_percent / 100)
    stop_loss_distance = abs(entry_price - stop_loss_price)
    if stop_loss_distance == 0:
        return 0
    return risk_amount / stop_loss_distance

def open_trade(symbol, signal, price, entry_type, zone=None):
    account_balance = 10000  # simulated balance

    # Initial trailing stop based on config
    sl_distance = price * (TRAILING_SL_PERCENT / 100)
    stop_loss = price - sl_distance if signal == "buy" else price + sl_distance

    position_size = calculate_position_size(account_balance, price, stop_loss, RISK_PERCENT)

    trade = {
        "timestamp": str(datetime.now()),
        "symbol": symbol,
        "signal": signal,
        "entry_type": entry_type,
        "zone": zone,
        "entry_price": price,
        "stop_loss": stop_loss,
        "position_size": position_size,
        "status": "open",
        "highest_price": price if signal == "buy" else None,
        "lowest_price": price if signal == "sell" else None
    }
    active_trades.append(trade)
    print(f"--- PAPER TRADE OPENED ---\n{trade}\n--------------------------")
    return trade

def update_trailing_stop(trade, current_price):
    # Buy trade: move stop-loss up as price moves
    if trade["signal"] == "buy":
        if current_price > trade["highest_price"]:
            trade["highest_price"] = current_price
            new_sl = current_price - (current_price * TRAILING_SL_PERCENT / 100)
            if new_sl > trade["stop_loss"]:
                trade["stop_loss"] = new_sl
    # Sell trade: move stop-loss down as price moves
    elif trade["signal"] == "sell":
        if current_price < trade["lowest_price"]:
            trade["lowest_price"] = current_price
            new_sl = current_price + (current_price * TRAILING_SL_PERCENT / 100)
            if new_sl < trade["stop_loss"]:
                trade["stop_loss"] = new_sl

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    symbol = data.get("symbol")
    raw_signal = data.get("signal", "").lower()
    trend = data.get("trend", "").lower()
    zone = data.get("zone", None)
    price = data.get("price")

    # Update trend if BOS
    if "bos" in raw_signal:
        current_trend[symbol] = trend
        return jsonify({"status": "trend updated", "symbol": symbol, "trend": trend})

    # Ignore signals against trend
    if symbol not in current_trend:
        return jsonify({"status": "ignored", "reason": "trend not set yet"})
    if current_trend[symbol] != trend:
        return jsonify({"status": "ignored", "reason": "signal against trend"})

    # Determine trade type
    if "choch" in raw_signal:
        entry_type = "primary"
    elif "ob breakout" in raw_signal or "fvg" in raw_signal:
        entry_type = "secondary"
    else:
        return jsonify({"status": "ignored", "reason": "unknown signal type"})

    # Map signal to buy/sell
    if "bullish" in raw_signal:
        signal = "buy"
    elif "bearish" in raw_signal:
        signal = "sell"
    else:
        return jsonify({"status": "ignored", "reason": "unknown bullish/bearish"})

    # Open paper trade
    trade = open_trade(symbol, signal, price, entry_type, zone)
    return jsonify({"status": "trade executed", "trade": trade})

@app.route("/update_price", methods=["POST"])
def update_price():
    """Send current price to update trailing stops."""
    data = request.json
    symbol = data.get("symbol")
    current_price = data.get("price")

    for trade in active_trades:
        if trade["symbol"] == symbol and trade["status"] == "open":
            update_trailing_stop(trade, current_price)
            # Close trade if price hits trailing stop
            if (trade["signal"] == "buy" and current_price <= trade["stop_loss"]) or \
               (trade["signal"] == "sell" and current_price >= trade["stop_loss"]):
                trade["status"] = "closed"
                trade["exit_price"] = current_price
                trade["closed_at"] = str(datetime.now())
                print(f"--- PAPER TRADE CLOSED ---\n{trade}\n------------------------")
    return jsonify({"status": "updated", "symbol": symbol})

@app.route("/trades", methods=["GET"])
def get_trades():
    return jsonify(active_trades)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
