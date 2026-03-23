from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# ===== STATE =====
position = None
entry_price = 0
sl = 0

trade_log = []
wins = 0
losses = 0

# ===== SETTINGS =====
ATR_MULTIPLIER = 1.5

# ===== SESSION FUNCTION =====
def is_trading_session(market):
    ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    h, m = ist.hour, ist.minute

    # NIFTY / Stocks
    if market == "NIFTY":
        return (h > 9 or (h == 9 and m >= 15)) and (h < 15 or (h == 15 and m <= 30))

    # MCX
    elif market == "MCX":
        return (h > 9 or (h == 9 and m >= 0)) and (h < 23 or (h == 23 and m <= 30))

    # Crypto (24/7)
    elif market == "CRYPTO":
        return True

    return True


@app.route("/")
def home():
    return "Multi-Market Trend Bot Running"


@app.route("/webhook", methods=["POST"])
def webhook():
    global position, entry_price, sl, wins, losses

    data = request.json

    action = data.get("action")
    price = float(data.get("price", 0))
    atr = float(data.get("atr", 5))
    ema = float(data.get("ema", 0))
    market = data.get("market", "NIFTY")

    print("Signal:", data)

    # ===== SESSION FILTER =====
    if not is_trading_session(market):
        print(f"{market} market closed")
        return jsonify({"status": "outside_session"})

    # ===== TREND FILTER =====
    if action == "buy" and price < ema:
        print("Trend not bullish, skipping")
        return jsonify({"status": "ignored_trend"})

    # ===== ENTRY =====
    if action == "buy" and position is None:
        position = "BUY"
        entry_price = price
        sl = price - (atr * ATR_MULTIPLIER)

        trade_log.append(f"{market} BUY at {price} | SL: {sl}")
        print(f"BUY at {price}")

    # ===== TRAILING STOP =====
    if position == "BUY":
        new_sl = price - (atr * ATR_MULTIPLIER)

        if new_sl > sl:
            sl = new_sl
            print(f"SL Trailed to {sl}")

        # ===== EXIT =====
        if price <= sl:
            pnl = price - entry_price

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trade_log.append(f"{market} EXIT at {price} | PnL: {pnl}")
            print(f"EXIT at {price}, PnL: {pnl}")

            position = None

    return jsonify({
        "position": position,
        "sl": sl,
        "wins": wins,
        "losses": losses
    })


@app.route("/log")
def log():
    return {
        "trades": trade_log,
        "wins": wins,
        "losses": losses
    }


# ===== RUN SERVER =====
port = int(os.environ.get("PORT", 10000))
app.run(host="0.0.0.0", port=port)
