from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC BOT (STABLE VERSION) STARTED 🔥", flush=True)

symbol = "BTCUSD"

bias = {}
zones = []
price_store = {}

current_trade = None
last_trade_time = 0
trade_history = []

COOLDOWN = 15
ZONE_TOLERANCE = 0.002

log_buffer = []

# ================= LOG =================
def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(entry, flush=True)
    log_buffer.append(entry)
    if len(log_buffer) > 150:
        log_buffer.pop(0)

# ================= STATS =================
def stats():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t["result"] == "win")
    pnl = sum(t["pnl"] for t in trade_history)
    winrate = (wins / total * 100) if total else 0
    return total, wins, total-wins, round(winrate,2), round(pnl,2)

# ================= HELPERS =================
def near_zone(price, zone_price):
    return abs(price - zone_price) <= price * ZONE_TOLERANCE

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time

    prev = price_store.get(symbol)
    price_store[symbol] = price

    log(f"📡 BTC Price: {price}")

    if not prev:
        return

    # 🔥 SIMPLE TREND (NO MORE NONE)
    trend = "up" if price > prev else "down"

    move = price - prev
    momentum = abs(move) > price * 0.00008

    htf = bias.get(symbol)

    if not htf:
        htf = "buy"  # fallback to keep system alive
        log("⚠️ No HTF → fallback BUY")

    log(f"HTF: {htf} | Trend: {trend} | Momentum: {momentum}")

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and (now - last_trade_time > COOLDOWN):

        decision = None

        # 🔥 PRIMARY: HTF + MOMENTUM
        if htf == "buy" and trend == "up" and momentum:
            decision = "buy"

        elif htf == "sell" and trend == "down" and momentum:
            decision = "sell"

        # 🔥 SECONDARY: ZONE-BASED ENTRY
        for z in reversed(zones[-5:]):
            if near_zone(price, z["price"]):
                if htf == "buy" and "bullish" in z["type"]:
                    decision = "buy"
                    log(f"📍 Zone BUY: {z}")
                elif htf == "sell" and "bearish" in z["type"]:
                    decision = "sell"
                    log(f"📍 Zone SELL: {z}")

        # 🔥 FINAL FALLBACK (ENSURES ACTIVITY)
        if not decision:
            if htf == "buy":
                decision = "buy"
                log("⚡ Forced BUY (HTF)")
            elif htf == "sell":
                decision = "sell"
                log("⚡ Forced SELL (HTF)")

        # ================= EXECUTE =================
        risk = price * 0.001

        sl = price - risk if decision == "buy" else price + risk
        tp = price + risk*2 if decision == "buy" else price - risk*2

        current_trade = {
            "side": decision,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "time": time.strftime('%H:%M:%S')
        }

        last_trade_time = now
        log(f"🚀 {decision.upper()} @ {price}")

    # ================= EXIT =================
    if current_trade:
        side = current_trade["side"]
        sl = current_trade["sl"]
        tp = current_trade["tp"]

        result = None
        pnl = 0

        if side == "buy":
            if price <= sl:
                result = "loss"; pnl = -1
            elif price >= tp:
                result = "win"; pnl = 2

        elif side == "sell":
            if price >= sl:
                result = "loss"; pnl = -1
            elif price <= tp:
                result = "win"; pnl = 2

        if result:
            current_trade["result"] = result
            current_trade["pnl"] = pnl
            trade_history.append(current_trade)

            log(f"{result.upper()} {pnl}R")

            current_trade = None

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

    log(f"📩 Incoming webhook: {data}")

    trend = str(data.get("trend","")).lower()
    signal_type = str(data.get("type","")).lower()
    price = float(data.get("price", 0) or 0)

    # 🔥 HTF
    if "bullish" in trend:
        bias[symbol] = "buy"
        log("🎯 HTF BUY")

    elif "bearish" in trend:
        bias[symbol] = "sell"
        log("🎯 HTF SELL")

    # 🔥 LTF ZONES
    if signal_type in ["bullish_ob", "bearish_ob", "bullish_fvg", "bearish_fvg"] and price > 0:
        zone = {
            "type": signal_type,
            "price": price,
            "time": time.strftime('%H:%M:%S')
        }
        zones.append(zone)
        log(f"📍 Zone stored: {signal_type} @ {price}")

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html>
<head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white;font-family:Arial">

<h2>BTC BOT (STABLE)</h2>

<p><b>Bias:</b> {{bias}}</p>
<p><b>Active Trade:</b> {{trade}}</p>

<p><b>Trades:</b> {{t}} | <b>Winrate:</b> {{wr}}% | <b>PnL:</b> {{pnl}}R</p>

<h3>Zones</h3>
{% for z in zones %}
<div>{{z.time}} | {{z.type}} | {{z.price}}</div>
{% endfor %}

<h3>Recent Trades</h3>
{% for t in hist %}
<div>{{t.time}} | {{t.side}} | {{t.result}} | {{t.pnl}}R</div>
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
    t,w,l,wr,pnl = stats()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        zones=reversed(zones[-10:]),
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        t=t, wr=wr, pnl=pnl
    )

@app.route('/')
def home():
    return {"status": "STABLE BOT RUNNING"}

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
