from flask import Flask, request, jsonify, render_template_string
import time
import os

app = Flask(__name__)

print("🔥 PRO BOT WITH ANALYTICS LOADED 🔥", flush=True)

# =========================
# STATE
# =========================
bias = {}
last_signal = {}
price_store = {}
current_trade = None
last_trade_time = 0

trade_history = []

# =========================
# CONFIG
# =========================
COOLDOWN = 60
RR = 2

# =========================
# LOG STORAGE
# =========================
log_buffer = []
MAX_LOGS = 200

def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)

    log_buffer.append(entry)
    if len(log_buffer) > MAX_LOGS:
        log_buffer.pop(0)

# =========================
# HELPERS
# =========================

def strong_momentum(price, prev):
    if prev is None:
        return False
    return abs(price - prev) > price * 0.001

def get_trend(price, prev):
    if prev is None:
        return None
    if price > prev:
        return "up"
    if price < prev:
        return "down"
    return None

def calculate_stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    losses = sum(1 for t in trade_history if t["result"] == "loss")

    winrate = (wins / total * 100) if total > 0 else 0

    return total, wins, losses, round(winrate, 2)

# =========================
# ROUTES
# =========================

@app.route('/')
def home():
    return {
        "status": "BOT RUNNING",
        "bias": bias,
        "trade": current_trade
    }

# =========================
# DASHBOARD UI
# =========================

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Trading Bot Pro Dashboard</title>
<meta http-equiv="refresh" content="3">
<style>
body { font-family: Arial; background:#0f172a; color:#e2e8f0; }
.box { padding:15px; margin:10px; border-radius:10px; background:#1e293b; }
.title { font-size:18px; margin-bottom:10px; }
.log { font-family:monospace; font-size:12px; }
table { width:100%; border-collapse:collapse; }
td, th { padding:6px; border-bottom:1px solid #334155; }
.win { color:#22c55e; }
.loss { color:#ef4444; }
</style>
</head>
<body>

<div class="box">
<div class="title">📊 Status</div>
Bias: {{bias}}<br>
Active Trade: {{trade}}
</div>

<div class="box">
<div class="title">📈 Performance</div>
Total Trades: {{total}}<br>
Wins: {{wins}}<br>
Losses: {{losses}}<br>
Win Rate: {{winrate}}%
</div>

<div class="box">
<div class="title">📜 Trade History</div>
<table>
<tr><th>Time</th><th>Side</th><th>Entry</th><th>Result</th></tr>
{% for t in history %}
<tr>
<td>{{t.time}}</td>
<td>{{t.side}}</td>
<td>{{t.entry}}</td>
<td class="{{t.result}}">{{t.result}}</td>
</tr>
{% endfor %}
</table>
</div>

<div class="box">
<div class="title">🧾 Logs</div>
<div class="log">
{% for l in logs %}
{{l}}<br>
{% endfor %}
</div>
</div>

</body>
</html>
"""

@app.route('/dashboard')
def dashboard():
    total, wins, losses, winrate = calculate_stats()

    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        logs=reversed(log_buffer),
        history=reversed(trade_history[-20:]),
        total=total,
        wins=wins,
        losses=losses,
        winrate=winrate
    )

# =========================
# WEBHOOK
# =========================

@app.route('/webhook', methods=['POST'])
def webhook():
    global bias, last_signal

    data = request.json or {}
    log(f"📩 Webhook: {data}")

    symbol = data.get("symbol")
    signal = str(data.get("signal", "")).lower()
    trend = str(data.get("trend", "")).lower()
    timeframe = data.get("timeframe")

    if timeframe == "HTF":
        if "bullish" in signal or trend == "bullish":
            bias[symbol] = "buy"
            log(f"🎯 Bias BUY set")
        elif "bearish" in signal or trend == "bearish":
            bias[symbol] = "sell"
            log(f"🎯 Bias SELL set")

    if timeframe == "LTF":
        last_signal[symbol] = signal

    return {"ok": True}

# =========================
# PRICE UPDATE
# =========================

@app.route('/update_price', methods=['POST'])
def update_price():
    global current_trade, last_trade_time

    data = request.json or {}

    symbol = data.get("symbol")
    price = data.get("price")

    if symbol is None or price is None:
        return {"error": "bad data"}, 400

    price = float(price)

    prev = price_store.get(symbol)
    price_store[symbol] = price

    log(f"{symbol} @ {price}")

    htf = bias.get(symbol)
    momentum = strong_momentum(price, prev)
    trend = get_trend(price, prev)

    now = time.time()

    if current_trade is None and htf:

        if now - last_trade_time < COOLDOWN:
            return {"status": "cooldown"}

        decision = None

        if momentum:
            if htf == "buy" and trend != "down":
                decision = "buy"
            elif htf == "sell" and trend != "up":
                decision = "sell"

        if decision:
            sl = price * 0.995 if decision == "buy" else price * 1.005
            tp = price + (price - sl) * RR if decision == "buy" else price - (sl - price) * RR

            current_trade = {
                "symbol": symbol,
                "side": decision,
                "entry": price,
                "sl": sl,
                "tp": tp,
                "time": time.strftime('%H:%M:%S')
            }

            last_trade_time = now
            log(f"🚀 {decision.upper()} @ {price}")

    if current_trade:
        side = current_trade["side"]
        sl = current_trade["sl"]
        tp = current_trade["tp"]

        result = None

        if side == "buy":
            if price <= sl:
                result = "loss"
            elif price >= tp:
                result = "win"

        if side == "sell":
            if price >= sl:
                result = "loss"
            elif price <= tp:
                result = "win"

        if result:
            current_trade["result"] = result
            trade_history.append(current_trade)

            log(f"{result.upper()} TRADE")

            current_trade = None

    return {"ok": True}

# =========================
# RUN
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
