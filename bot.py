from flask import Flask, request, jsonify, render_template_string
import time, os

app = Flask(__name__)

# =========================
# STATE
# =========================
bias = {}
price_store = {}
current_trade = None
last_trade_time = 0
trade_history = []

COOLDOWN = 10

log_buffer = []

def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 100:
        log_buffer.pop(0)

def stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    losses = total - wins
    pnl = sum(t["pnl"] for t in trade_history)
    winrate = (wins/total*100) if total else 0
    return total, wins, losses, round(winrate,2), round(pnl,2)

@app.route('/')
def home():
    return {"status":"running","trade":current_trade}

# ================= DASHBOARD =================
HTML = """
<html>
<head>
<meta http-equiv="refresh" content="2">
<style>
body { background:#0f172a; color:white; font-family:Arial }
.box { padding:15px; margin:10px; background:#1e293b; border-radius:10px }
.win { color:#22c55e }
.loss { color:#ef4444 }
</style>
</head>

<body>

<div class="box">
<h3>📊 Status</h3>
Bias: {{bias}} <br>
Active Trade: {{trade}}
</div>

<div class="box">
<h3>📈 Performance</h3>
Trades: {{t}} | Wins: {{w}} | Losses: {{l}} <br>
Winrate: {{wr}}% <br>
Net PnL (R): {{pnl}}
</div>

<div class="box">
<h3>📜 Trades</h3>
{% for t in hist %}
<div class="{{t.result}}">
{{t.time}} | {{t.side}} | {{t.result}} | {{t.pnl}}R
</div>
{% endfor %}
</div>

<div class="box">
<h3>🧾 Activity</h3>
{% for l in logs %}
{{l}}<br>
{% endfor %}
</div>

</body>
</html>
"""

@app.route('/dashboard')
def dash():
    t,w,l,wr,pnl = stats()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        t=t,w=w,l=l,wr=wr,pnl=pnl
    )

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    symbol = data.get("symbol")
    trend = str(data.get("trend","")).lower()
    tf = data.get("timeframe")

    if tf == "HTF":
        if "bullish" in trend:
            bias[symbol] = "buy"
            log(f"Bias BUY {symbol}")
        elif "bearish" in trend:
            bias[symbol] = "sell"
            log(f"Bias SELL {symbol}")

    return {"ok":True}

# ================= PRICE =================
@app.route('/update_price', methods=['POST'])
def update():
    global current_trade, last_trade_time

    data = request.json or {}
    symbol = data.get("symbol")
    price = float(data.get("price"))

    prev = price_store.get(symbol)
    price_store[symbol] = price

    if not prev:
        return {"ok":True}

    htf = bias.get(symbol)

    move = abs(price - prev)
    momentum = move > price * 0.0004
    trend = "up" if price > prev else "down"

    now = time.time()

    # ENTRY
    if not current_trade and htf:

        if now - last_trade_time < COOLDOWN:
            return {"cooldown":True}

        decision = None

        # Momentum entry
        if momentum:
            if htf=="buy" and trend=="up":
                decision="buy"
            elif htf=="sell" and trend=="down":
                decision="sell"

        # Micro pullback entry
        if not decision:
            if htf=="buy" and trend=="up":
                decision="buy"
                log("📈 Pullback BUY")
            elif htf=="sell" and trend=="down":
                decision="sell"
                log("📉 Pullback SELL")

        if decision:
            risk = move * 2 if move else price * 0.002

            sl = price - risk if decision=="buy" else price + risk
            tp = price + risk*2 if decision=="buy" else price - risk*2

            current_trade = {
                "side":decision,
                "entry":price,
                "sl":sl,
                "tp":tp,
                "risk":risk,
                "time":time.strftime('%H:%M:%S')
            }

            last_trade_time = now
            log(f"🚀 {decision.upper()} @ {price}")

    else:
        if htf:
            log(f"Watching {htf.upper()}...")

    # EXIT
    if current_trade:
        side = current_trade["side"]
        sl = current_trade["sl"]
        tp = current_trade["tp"]

        result=None
        pnl=0

        if side=="buy":
            if price <= sl:
                result="loss"; pnl=-1
            elif price >= tp:
                result="win"; pnl=2

        if side=="sell":
            if price >= sl:
                result="loss"; pnl=-1
            elif price <= tp:
                result="win"; pnl=2

        if result:
            current_trade["result"]=result
            current_trade["pnl"]=pnl
            trade_history.append(current_trade)

            log(f"{result.upper()} {pnl}R")

            current_trade=None

    return {"ok":True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
