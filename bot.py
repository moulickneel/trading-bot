from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC HYBRID BOT STARTED 🔥", flush=True)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0
trade_history = []

COOLDOWN = 20
ZONE_TOLERANCE = 0.003

log_buffer = []

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 200:
        log_buffer.pop(0)

# ================= STATS =================
def stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    pnl = sum(t["pnl"] for t in trade_history)
    winrate = (wins / total * 100) if total else 0

    scalp = [t for t in trade_history if t["type"] == "scalp"]
    runner = [t for t in trade_history if t["type"] == "runner"]

    return {
        "total": total,
        "wr": round(winrate,2),
        "pnl": round(pnl,2),
        "scalp_wr": round((sum(1 for t in scalp if t["result"]=="win")/len(scalp)*100),2) if scalp else 0,
        "runner_wr": round((sum(1 for t in runner if t["result"]=="win")/len(runner)*100),2) if runner else 0
    }

# ================= STRUCTURE =================
def get_structure():
    if len(price_data) < 10:
        return None
    highs = price_data[-5:]
    lows = price_data[-10:-5]

    if max(highs) > max(lows):
        return "up"
    elif min(highs) < min(lows):
        return "down"
    return None

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 Price: {price}")

    structure = get_structure()
    if not structure:
        log("⚠️ No structure")
        return

    htf = bias.get(symbol)
    if not htf:
        log("⚠️ No HTF bias")
        return

    log(f"HTF: {htf} | Structure: {structure}")

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and (now - last_trade_time > COOLDOWN):

        decision = None
        trade_type = None

        if len(price_data) < 5:
            return

        p1, p2, p3, p4, p5 = price_data[-1], price_data[-2], price_data[-3], price_data[-4], price_data[-5]

        # -------- SCALP CONDITIONS (STRICT) --------
        for z in reversed(zones[-5:]):
            near = abs(price - z["price"]) < price * ZONE_TOLERANCE

            if near:
                if htf == "buy" and structure == "up" and "bullish" in z["type"]:
                    if p5 > p4 > p3 and p1 > p2 > p3:
                        decision = "buy"
                        trade_type = "scalp"
                        log("🔵 SCALP BUY (zone + pullback + impulse)")
                        break

                elif htf == "sell" and structure == "down" and "bearish" in z["type"]:
                    if p5 < p4 < p3 and p1 < p2 < p3:
                        decision = "sell"
                        trade_type = "scalp"
                        log("🔵 SCALP SELL (zone + pullback + impulse)")
                        break

        # -------- RUNNER CONDITIONS --------
        if not decision:
            if htf == "buy" and structure == "up":
                if p1 > p2 > p3:
                    decision = "buy"
                    trade_type = "runner"
                    log("🔴 RUNNER BUY (momentum)")

            elif htf == "sell" and structure == "down":
                if p1 < p2 < p3:
                    decision = "sell"
                    trade_type = "runner"
                    log("🔴 RUNNER SELL (momentum)")

        if not decision:
            log("❌ No entry")
            return

        risk = price * 0.001

        sl = price - risk if decision == "buy" else price + risk

        current_trade = {
            "side": decision,
            "entry": price,
            "sl": sl,
            "type": trade_type,
            "time": time.strftime('%H:%M:%S'),
            "be_moved": False
        }

        last_trade_time = now

        log(f"🚀 {decision.upper()} [{trade_type}] @ {price}")

    # ================= EXIT =================
    if current_trade:
        side = current_trade["side"]
        entry = current_trade["entry"]
        sl = current_trade["sl"]
        trade_type = current_trade["type"]

        risk = abs(entry - sl)

        r = (price - entry)/risk if side=="buy" else (entry - price)/risk

        # -------- SCALP EXIT --------
        if trade_type == "scalp":
            tp = entry + risk*1.5 if side=="buy" else entry - risk*1.5

            if (side=="buy" and price >= tp) or (side=="sell" and price <= tp):
                pnl = 1.5
                current_trade["result"]="win"
                current_trade["pnl"]=pnl
                trade_history.append(current_trade)
                log(f"✅ SCALP TP HIT {pnl}R")
                current_trade=None

            elif (side=="buy" and price <= sl) or (side=="sell" and price >= sl):
                pnl=-1
                current_trade["result"]="loss"
                current_trade["pnl"]=pnl
                trade_history.append(current_trade)
                log("❌ SCALP SL HIT")
                current_trade=None

        # -------- RUNNER EXIT --------
        elif trade_type == "runner":

            if r >= 1 and not current_trade["be_moved"]:
                current_trade["sl"] = entry
                current_trade["be_moved"] = True
                log("🔒 BE moved")

            if r >= 2:
                if side=="buy":
                    new_sl = price - risk*0.5
                    if new_sl > current_trade["sl"]:
                        current_trade["sl"]=new_sl
                        log("📈 Trail BUY")
                else:
                    new_sl = price + risk*0.5
                    if new_sl < current_trade["sl"]:
                        current_trade["sl"]=new_sl
                        log("📉 Trail SELL")

            if (side=="buy" and price <= current_trade["sl"]) or (side=="sell" and price >= current_trade["sl"]):
                pnl = round(r,2)
                current_trade["result"]="win" if pnl>0 else "loss"
                current_trade["pnl"]=pnl
                trade_history.append(current_trade)
                log(f"EXIT RUNNER {pnl}R")
                current_trade=None

# ================= PRICE LOOP =================
def price_loop():
    while True:
        try:
            url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
            res = requests.get(url, timeout=5).json()
            price = float(res["data"]["amount"])
            on_price_update(price)
        except Exception as e:
            log(f"❌ API Error: {e}")
        time.sleep(1)

threading.Thread(target=price_loop, daemon=True).start()

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}

    log(f"📩 {data}")

    trend = str(data.get("trend","")).lower()
    signal_type = str(data.get("type","")).lower()
    price = float(data.get("price",0) or 0)

    if "bullish" in trend:
        bias[symbol]="buy"
        log("🎯 HTF BUY")

    elif "bearish" in trend:
        bias[symbol]="sell"
        log("🎯 HTF SELL")

    if signal_type in ["bullish_ob","bearish_ob","bullish_fvg","bearish_fvg"]:
        zones.append({
            "type": signal_type,
            "price": price,
            "time": time.strftime('%H:%M:%S')
        })
        log(f"📍 Zone stored {signal_type} @ {price}")

    return {"ok":True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white">

<h2>BTC HYBRID BOT</h2>

<p>Bias: {{bias}}</p>
<p>Active: {{trade}}</p>

<p>Trades: {{s.total}} | Winrate: {{s.wr}}% | PnL: {{s.pnl}}R</p>
<p>Scalp WR: {{s.scalp_wr}}% | Runner WR: {{s.runner_wr}}%</p>

<h3>Zones</h3>
{% for z in zones %}
<div>{{z.time}} | {{z.type}} | {{z.price}}</div>
{% endfor %}

<h3>Trades</h3>
{% for t in hist %}
<div>{{t.time}} | {{t.side}} | {{t.type}} | {{t.result}} | {{t.pnl}}R</div>
{% endfor %}

<h3>Logs</h3>
{% for l in logs %}
<div>{{l}}</div>
{% endfor %}

</body>
</html>
"""

@app.route('/dashboard')
def dash():
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        zones=reversed(zones[-10:]),
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        s=stats()
    )

@app.route('/')
def home():
    return {"status":"HYBRID BOT RUNNING"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
