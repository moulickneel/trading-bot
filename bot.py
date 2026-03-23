from flask import Flask, request, jsonify

app = Flask(__name__)

# ===== PAPER TRADING STATE =====
position = None   # "BUY" or "SELL"
entry_price = None
trade_log = []

@app.route("/")
def home():
    return "Paper Trading Bot Running"

@app.route("/webhook", methods=["POST"])
def webhook():
    global position, entry_price

    data = request.json
    action = data.get("action")

    print("Signal received:", data)

    # Simulated price (you can later pass real price)
    price = data.get("price", 100)

    if action == "buy":
        if position is None:
            position = "BUY"
            entry_price = price
            trade_log.append(f"BUY at {price}")
            print(f"BUY executed at {price}")
        else:
            print("Already in position, skipping BUY")

    elif action == "sell":
        if position == "BUY":
            pnl = price - entry_price
            trade_log.append(f"SELL at {price} | PnL: {pnl}")
            print(f"SELL executed at {price}, PnL: {pnl}")
            position = None
            entry_price = None
        else:
            print("No BUY position to close")

    return jsonify({"status": "ok", "position": position})

@app.route("/log")
def log():
    return {"trades": trade_log}

app.run(host="0.0.0.0", port=10000)
