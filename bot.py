from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import time

app = Flask(__name__)

# ===== GLOBAL STATE =====
positions = {}  # symbol-wise positions
trade_log = []
wins = 0
losses = 0

# ===== SETTINGS =====

# % Stop Loss per market
SL_CONFIG = {
    "CRYPTO": 0.003,     # 0.3%
    "MCX": 0.002,        # 0.2%
    "NIFTY": 0.0015      # 0.15%
}

# Cooldown (seconds between trades per symbol)
COOLDOWN = 60

# Allowed symbols
ALLOWED_SYMBOLS = [
    "NIFTY", "BANKNIFTY",
    "GOLDPETAL", "SILVERMIC", "CRUDEOILM",
    "BTCUSDT", "ETHUSDT"
]

# ===== SESSION FILTER =====
def is_trading_session(market):
    ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    h, m = ist.hour, ist.minute

    if market == "NIFTY":
        return (h > 9 or (h == 9 and m >= 15)) and (h < 15 or (h == 15 and m <= 30))

    elif market == "MCX":
        return (h > 9 or (h == 9 and m >= 0)) and (h < 23 or (h == 23 and m <= 30))

    elif market == "CRYPTO":
        return True

    return True


@app.route("/")
def home():
    return "Multi-Market Bot Running"


# ===== WEBHOOK =====
@app.route("/webhook", methods=["POST"])
def webhook():
    global wins, losses

    data = request.json
    if not data:
        return jsonify({"status": "no_data"}), 400

    symbol = data.get("symbol")
    action = data.get("action")
    price = float(data.get("price", 0))
    market = data.get("market", "NIFTY")

    action = action.lower() if action else None

    print("Signal:", data)

    # ===== VALIDATION =====
    if symbol not in ALLOWED_SYMBOLS:
        return jsonify({"status": "ignored_symbol"})

    if not is_trading_session(market):
        return jsonify({"status": "outside_session"})

    # ===== INIT STATE =====
    if symbol not in positions:
        positions[symbol] = {
            "position": None,
            "entry_price": 0,
            "sl": 0,
            "last_trade_time": 0
        }

    pos = positions[symbol]

    # ===== COOLDOWN =====
    now = time.time()
    if now - pos["last_trade_time"] < COOLDOWN:
        return jsonify({"status": "cooldown_active"})

    # ===== SL CONFIG =====
    sl_percent = SL_CONFIG.get(market, 0.002)

    # ===== BUY =====
    if action == "buy":

        # Close short
        if pos["position"] == "SELL":
            pnl = pos["entry_price"] - price

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trade_log.append(f"{symbol} EXIT SELL at {price} | PnL: {pnl}")

        # Open long
        pos["position"] = "BUY"
        pos["entry_price"] = price
        pos["sl"] = price * (1 - sl_percent)
        pos["last_trade_time"] = now

        trade_log.append(f"{symbol} BUY at {price} | SL: {pos['sl']}")

    # ===== SELL =====
    elif action == "sell":

        # Close long
        if pos["position"] == "BUY":
            pnl = price - pos["entry_price"]

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trade_log.append(f"{symbol} EXIT BUY at {price} | PnL: {pnl}")

        # Open short
        pos["position"] = "SELL"
        pos["entry_price"] = price
        pos["sl"] = price * (1 + sl_percent)
        pos["last_trade_time"] = now

        trade_log.append(f"{symbol} SELL at {price} | SL: {pos['sl']}")

    # ===== TRAILING STOP =====
    if pos["position"] == "BUY":
        new_sl = price * (1 - sl_percent)

        if new_sl > pos["sl"]:
            pos["sl"] = new_sl

        if price <= pos["sl"]:
            pnl = price - pos["entry_price"]

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trade_log.append(f"{symbol} SL HIT BUY at {price} | PnL: {pnl}")
            pos["position"] = None

    elif pos["position"] == "SELL":
        new_sl = price * (1 + sl_percent)

        if new_sl < pos["sl"]:
            pos["sl"] = new_sl

        if price >= pos["sl"]:
            pnl = pos["entry_price"] - price

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trade_log.append(f"{symbol} SL HIT SELL at {price} | PnL: {pnl}")
            pos["position"] = None

    return jsonify({
        "symbol": symbol,
        "position": pos["position"],
        "sl": pos["sl"],
        "wins": wins,
        "losses": losses
    })


# ===== LOG =====
@app.route("/log")
def log():
    return {
        "trades": trade_log[-50:],
        "wins": wins,
        "losses": losses,
        "positions": positions
    }


# ===== RUN =====
port = int(os.environ.get("PORT", 10000))
app.run(host="0.0.0.0", port=port)
