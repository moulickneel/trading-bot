from flask import Flask, request, render_template_string
import time, os, threading, requests

app = Flask(__name__)

print("🔥 BTC BOT (FINAL STABLE VERSION) STARTED 🔥", flush=True)

symbol = "BTCUSD"

bias = {}
zones = []
price_data = []

current_trade = None
last_trade_time = 0
last_bias_trade = None

trade_history = []
log_buffer = []

COOLDOWN = 180
ZONE_TOLERANCE = 0.003

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
    return total, round(winrate,2), round(pnl,2)

# ================= PRICE FETCH =================
def get_price():
    apis = [
        ("coinbase", "https://api.coinbase.com/v2/prices/BTC-USD/spot"),
        ("binance", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"),
        ("coingecko", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
    ]

    for name, url in apis:
        try:
            res = requests.get(url, timeout=4).json()

            if name == "coinbase":
                return float(res["data"]["amount"])

            elif name == "binance":
                return float(res["price"])

            elif name == "coingecko":
                return float(res["bitcoin"]["usd"])

        except:
            continue

    return None

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

# ================= STRONG CANDLE =================
def strong_candle():
    if len(price_data) < 3:
        return None

    c = price_data[-1]
    p = price_data[-2]
    p2 = price_data[-3]

    if c > p > p2:
        return "buy"
    elif c < p < p2:
        return "sell"

    return None

# ================= CORE =================
def on_price_update(price):
    global current_trade, last_trade_time, last_bias_trade

    price_data.append(price)
    if len(price_data) > 50:
        price_data.pop(0)

    log(f"📡 Price: {price}")

    structure = get_structure()
    if not structure:
        return

    htf = bias.get(symbol)
    if not htf:
        return

    log(f"HTF: {htf} | Structure: {structure}")

    now = time.time()

    # ================= ENTRY =================
    if not current_trade and (now - last_trade_time > COOLDOWN):

        if htf == last_bias_trade:
            log("⛔ Already traded this trend")
            return

        decision = None
        trade_type = None

        if len(price_data) < 5:
            return

        p1, p2, p3, p4, p5 = price_data[-1], price_data[-2], price_data[-3], price_data[-4], price_data[-5]

        # -------- SCALP --------
        for z in reversed(zones[-5:]):
            if abs(price - z["price"]) < price * ZONE_TOLERANCE:

                if htf == "buy" and structure == "up" and "bullish" in z["type"]:
                    if p5 > p4 > p3 and p1 > p2 and strong_candle() == "buy":
                        decision = "buy"
                        trade_type = "scalp"
                        log("🔵 SCALP BUY")
                        break

                elif htf == "sell" and structure == "down" and "bearish" in z["type"]:
                    if p5 < p4 < p3 and p1 < p2 and strong_candle() == "sell":
                        decision = "sell"
                        trade_type = "scalp"
                        log("🔵 SCALP SELL")
                        break

        # -------- RUNNER --------
        if not decision:

            if htf == "buy" and structure == "up":
                if p5 > p4 > p3 and p1 > p2 and strong_candle() == "buy":
                    decision = "buy"
                    trade_type = "runner"
                    log("🔴 RUNNER BUY")

            elif htf == "sell" and structure == "down":
                if p5 < p4 < p3 and p1 < p2 and strong_candle() == "sell":
                    decision = "sell"
                    trade_type = "runner"
                    log("🔴 RUNNER SELL")

        if not decision:
            return

        risk = max(price * 0.001, 1)
        sl = price - risk if decision == "buy" else price + risk

        current_trade = {
            "side": decision,
            "entry": price,
            "sl": sl,
            "type": trade_type,
            "display_time": time.strftime('%H:%M:%S'),
            "timestamp": time.time(),
            "be_moved": False
        }

        last_trade_time = now
        last_bias_trade = htf

        log(f"🚀 {decision.upper()} [{trade_type}] @ {price}")

    # ================= EXIT =================
    if current_trade:
        side = current_trade["side"]
        entry = current_trade["entry"]
        sl = current_trade["sl"]
        trade_type = current_trade["type"]

        risk = max(abs(entry - sl), 1)
        r = (price - entry)/risk if side=="buy" else (entry - price)/risk

        # SCALP
        if trade_type == "scalp":
            tp = entry + risk*1.5 if side=="buy" else entry - risk*1.5

            if (side=="buy" and price >= tp) or (side=="sell" and price <= tp):
                current_trade["result"]="win"
                current_trade["pnl"]=1.5
                trade_history.append(current_trade)
                log("✅ SCALP TP")
                current_trade=None

            elif (side=="buy" and price <= sl) or (side=="sell" and price >= sl):
                current_trade["result"]="loss"
                current_trade["pnl"]=-1
                trade_history.append(current_trade)
                log("❌ SCALP SL")
                current_trade=None

        # RUNNER
        elif trade_type == "runner":

            if r >= 1.5 and not current_trade["be_moved"]:
                current_trade["sl"] = entry
                current_trade["be_moved"] = True
                log("🔒 BE moved")

            if r >= 2:
                if side=="buy":
                    new_sl = price - risk
                    if new_sl > current_trade["sl"]:
                        current_trade["sl"] = new_sl
                        log("📈 Trail BUY")
                else:
                    new_sl = price + risk
                    if new_sl < current_trade["sl"]:
                        current_trade["sl"] = new_sl
                        log("📉 Trail SELL")

            if (side=="buy" and price <= current_trade["sl"]) or (side=="sell" and price >= current_trade["sl"]):
                pnl = round(r,2)
                current_trade["result"]="win" if pnl>0 else "loss"
                current_trade["pnl"]=pnl
                trade_history.append(current_trade)
                log(f"EXIT RUNNER {pnl}R")
                current_trade=None

# ================= LOOP =================
def price_loop():
    while True:
        try:
            price = get_price()
            if price:
                on_price_update(price)
            else:
                log("❌ ALL APIS FAILED")
        except Exception as e:
            log(f"❌ CRITICAL: {e}")

        time.sleep(2)

threading.Thread(target=price_loop, daemon=True).start()

# ================= WEBHOOK =================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    log(f"📩 {data}")

    price = float(data.get("price",0) or 0)
    signal = str(data.get("signal","")).lower()
    trend = str(data.get("trend","")).lower()
    tf = str(data.get("timeframe","")).lower()

    if tf == "htf":
        if "bullish" in signal:
            bias[symbol] = "buy"
            log("🎯 HTF BUY")
        elif "bearish" in signal:
            bias[symbol] = "sell"
            log("🎯 HTF SELL")

    if tf == "ltf":
        if "bullish" in trend:
            zones.append({"type":"bullish_zone","price":price})
            log("📍 Bullish Zone")
        elif "bearish" in trend:
            zones.append({"type":"bearish_zone","price":price})
            log("📍 Bearish Zone")

    return {"ok": True}

# ================= DASHBOARD =================
HTML = """
<html><head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0f172a;color:white">
<h2>BTC BOT FINAL</h2>
<p>Bias: {{bias}}</p>
<p>Active: {{trade}}</p>
<p>Trades: {{t}} | Winrate: {{wr}}% | PnL: {{pnl}}R</p>

<h3>Trades</h3>
{% for t in hist %}
<div>{{t.display_time}} | {{t.side}} | {{t.type}} | {{t.result}} | {{t.pnl}}R</div>
{% endfor %}

<h3>Logs</h3>
{% for l in logs %}
<div>{{l}}</div>
{% endfor %}
</body></html>
"""

@app.route('/dashboard')
def dash():
    t,wr,pnl = stats()
    return render_template_string(
        HTML,
        bias=bias,
        trade=current_trade,
        hist=reversed(trade_history[-20:]),
        logs=reversed(log_buffer),
        t=t, wr=wr, pnl=pnl
    )

@app.route('/')
def home():
    return {"status":"BOT RUNNING FINAL"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
