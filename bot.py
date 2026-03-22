from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    print("Signal:", data)

    if data["action"] == "buy":
        print("BUY ORDER")

    if data["action"] == "sell":
        print("SELL ORDER")

    return "ok"

app.run(host="0.0.0.0", port=10000)
