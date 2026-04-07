from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return {"status": "running"}

@app.route('/webhook', methods=['POST'])
def webhook():
    print("Webhook received:", request.json, flush=True)
    return {"ok": True}

@app.route('/update_price', methods=['POST'])
def update_price():
    print("Price update:", request.json, flush=True)
    return {"ok": True}
