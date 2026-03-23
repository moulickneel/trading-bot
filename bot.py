from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    print("Signal received:", data)

    if data["action"] == "buy":
        print("BUY SIGNAL")

    if data["action"] == "sell":
        print("SELL SIGNAL")

    return "ok"

app.run(host="0.0.0.0", port=10000)
