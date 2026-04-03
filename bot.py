# bot.py
from flask import Flask, request, jsonify
import os
import time
from threading import Thread

app = Flask(__name__)

# =====================
# CONFIGURATION
# =====================
RISK_PER_TRADE = 0.01  # Risk 1% of account balance
ACCOUNT_BALANCE = 1000  # Replace with API call to get live balance

# Trailing stop-loss & take-profit settings
BASE_STOP_LOSS_PCT = 0.01  # Initial 1% stop-loss
BASE_TAKE_PROFIT_PCT = 0.02  # Initial 2% target
TRAILING_SL_STEP_PCT = 0.005  # Adjust SL by 0.5% per 1% favorable price move

# Store active trades
active_trades = {}  # key: symbol, value: trade dict

# =====================
# RISK MANAGEMENT
# =====================
def get_position_size(account_balance, risk_per_trade, stop_loss_pct):
    """Calculate trade size based on account balance and stop-loss risk"""
    return (account_balance * risk_per_trade) / stop_loss_pct

# =====================
# TRADE EXECUTION
# =====================
def execute_trade(symbol, signal, price):
    """Open a new trade based on webhook alert"""
    position_size = get_position_size(ACCOUNT_BALANCE, RISK_PER_TRADE, BASE_STOP_LOSS_PCT)
    
    stop_loss = float(price) * (1 - BASE_STOP_LOSS_PCT) if signal.lower() == "buy" else float(price) * (1 + BASE_STOP_LOSS_PCT)
    take_profit = float(price) * (1 + BASE_TAKE_PROFIT_PCT) if signal.lower() == "buy" else float(price) * (1 - BASE_TAKE_PROFIT_PCT)

    active_trades[symbol] = {
        "signal": signal.lower(),
        "entry_price": float(price),
        "position_size": position_size,
        "stop_loss": stop_loss,
        "take_profit": take_profit
    }

    print(f"--- TRADE OPENED ---")
    print(active_trades[symbol])
    print("--------------------")
    return True

# =====================
# TRAILING STOP-LOSS MANAGEMENT
# =====================
def update_trailing_sl(symbol, current_price):
    trade = active_trades.get(symbol)
    if not trade:
        return

    if trade["signal"] == "buy":
        price_move_pct = (current_price - trade["entry_price"]) / trade["entry_price"]
        if price_move_pct > 0:
            new_sl = trade["stop_loss"] + TRAILING_SL_STEP_PCT * (price_move_pct / BASE_STOP_LOSS_PCT) * trade["entry_price"]
            if new_sl > trade["stop_loss"]:
                trade["stop_loss"] = new_sl
    elif trade["signal"] == "sell":
        price_move_pct = (trade["entry_price"] - current_price) / trade["entry_price"]
        if price_move_pct > 0:
            new_sl = trade["stop_loss"] - TRAILING_SL_STEP_PCT * (price_move_pct / BASE_STOP_LOSS_PCT) * trade["entry_price"]
            if new_sl < trade["stop_loss"]:
                trade["stop_loss"] = new_sl

# =====================
# WEBHOOK ENDPOINT
# =====================
@app.route("/", methods=["GET"])
def home():
    return "LuxAlgo Multi-Instrument Bot Running 24/7!"

@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.json
        symbol = data.get("symbol")
        signal = data.get("signal")
        price = float(data.get("price"))

        if not all([symbol, signal, price]):
            return jsonify({"status": "error", "message": "Missing fields"}), 400

        # Execute the trade
        success = execute_trade(symbol, signal, price)
        return jsonify({"status": "success" if success else "error", "trade": active_trades.get(symbol)})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# =====================
# TRADE MANAGEMENT LOOP
# =====================
def manage_trades():
    while True:
        for symbol, trade in list(active_trades.items()):
            # Replace this with real-time price feed from broker API
            current_price = trade["entry_price"]  # placeholder
            
            # Update trailing stop-loss
            update_trailing_sl(symbol, current_price)

            # Check stop-loss or take-profit hit
            if trade["signal"] == "buy":
                if current_price <= trade["stop_loss"] or current_price >= trade["take_profit"]:
                    print(f"Closing trade {symbol}")
                    del active_trades[symbol]
            elif trade["signal"] == "sell":
                if current_price >= trade["stop_loss"] or current_price <= trade["take_profit"]:
                    print(f"Closing trade {symbol}")
                    del active_trades[symbol]
        time.sleep(5)  # loop every 5 seconds

# =====================
# RUN BOT
# =====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    Thread(target=manage_trades, daemon=True).start()
    app.run(host="0.0.0.0", port=port)
