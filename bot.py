from flask import Flask, request, jsonify
import time

app = Flask(__name__)

print("🔥 STABLE AGGRESSIVE BOT LOADED 🔥", flush=True)

# =========================
# STATE
# =========================
bias = {}
last_signal = {}
price_store = {}
current_trade = None
last_trade_time = 0

# =========================
# CONFIG
# =========================
COOLDOWN = 60
RR = 2

# =========================
# HELPERS
# =========================

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

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

# =========================
# ROUTES
# =========================

@app.route('/')
def home():
    return jsonify({
        "status": "BOT RUNNING",
        "bias": bias,
        "trade": current_trade
    })

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

    if not symbol:
        return jsonify({"error": "no symbol"}), 400

    # HTF bias
    if timeframe == "HTF":
        if "bullish" in signal or trend == "bullish":
            bias[symbol] = "buy"
            log(f"🎯 Bias BUY set for {symbol}")
        elif "bearish" in signal or trend == "bearish":
            bias[symbol] = "sell"
            log(f"🎯 Bias SELL set for {symbol}")

    # LTF memory
    if timeframe == "LTF":
        last_signal[symbol] = signal
        log(f"📊 LTF stored: {signal}")

    return jsonify({"ok": True})

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
        return jsonify({"error": "bad data"}), 400

    try:
        price = float(price)
    except:
        return jsonify({"error": "invalid price"}), 400

    prev = price_store.get(symbol)
    price_store[symbol] = price

    log(f"\n--- {symbol} @ {price} ---")

    htf = bias.get(symbol)
    ltf = last_signal.get(symbol)

    momentum = strong_momentum(price, prev)
    trend = get_trend(price, prev)

    log(f"HTF: {htf}")
    log(f"LTF: {ltf}")
    log(f"Momentum: {momentum}")
    log(f"Trend: {trend}")

    now = time.time()

    # =========================
    # ENTRY
    # =========================
    if current_trade is None and htf:

        if now - last_trade_time < COOLDOWN:
            log("⏳ Cooldown")
            return jsonify({"status": "cooldown"})

        decision = None

        # 🔥 MOMENTUM FIRST
        if momentum:
            if htf == "buy" and trend != "down":
                decision = "buy"
                log("⚡ Momentum BUY")
            elif htf == "sell" and trend != "up":
                decision = "sell"
                log("⚡ Momentum SELL")

        # fallback
        elif ltf:
            if htf == "buy" and "bullish" in ltf:
                decision = "buy"
                log("📈 LTF BUY")
            elif htf == "sell" and "bearish" in ltf:
                decision = "sell"
                log("📉 LTF SELL")

        if decision:
            sl = price * 0.995 if decision == "buy" else price * 1.005
            tp = price + (price - sl) * RR if decision == "buy" else price - (sl - price) * RR

            current_trade = {
                "symbol": symbol,
                "side": decision,
                "entry": price,
                "sl": sl,
                "tp": tp
            }

            last_trade_time = now

            log(f"🚀 TRADE: {decision.upper()} @ {price}")
            log(f"SL: {sl} | TP: {tp}")

    # =========================
    # MANAGEMENT
    # =========================
    if current_trade:
        side = current_trade["side"]
        sl = current_trade["sl"]
        tp = current_trade["tp"]

        if side == "buy":
            if price <= sl:
                log("❌ SL HIT")
                current_trade = None
            elif price >= tp:
                log("✅ TP HIT")
                current_trade = None

        if side == "sell":
            if price >= sl:
                log("❌ SL HIT")
                current_trade = None
            elif price <= tp:
                log("✅ TP HIT")
                current_trade = None

    return jsonify({"ok": True})
