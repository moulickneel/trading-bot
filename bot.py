from flask import Flask, request, jsonify
import time

app = Flask(__name__)

# =========================
# STATE STORAGE
# =========================
bias = {}  # HTF bias memory
last_signal = {}
open_trade = None

# =========================
# CONFIG
# =========================
RISK_REWARD = 2
MOMENTUM_THRESHOLD = 0.6   # adaptive feel
COOLDOWN = 60  # seconds between trades

last_trade_time = 0

# =========================
# HELPERS
# =========================

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def strong_momentum(price, prev_price):
    if prev_price is None:
        return False
    move = abs(price - prev_price)
    return move > (price * 0.001)  # adaptive threshold

def detect_trend(price, prev_price):
    if prev_price is None:
        return None
    if price > prev_price:
        return "up"
    elif price < prev_price:
        return "down"
    return None

# =========================
# ROUTES
# =========================

@app.route('/')
def home():
    return jsonify({
        "bias": bias,
        "open_trade": open_trade,
        "status": "AGGRESSIVE BOT RUNNING"
    })

# =========================
# WEBHOOK (TradingView signals)
# =========================

@app.route('/webhook', methods=['POST'])
def webhook():
    global bias, last_signal

    data = request.json
    log(f"📩 Webhook received: {data}")

    symbol = data.get("symbol")
    signal = data.get("signal", "").lower()
    trend = data.get("trend", "")
    timeframe = data.get("timeframe", "")

    if timeframe == "HTF":
        if "bullish" in signal or trend == "bullish":
            bias[symbol] = "buy"
            log(f"✅ HTF bias set to BUY for {symbol}")
        elif "bearish" in signal or trend == "bearish":
            bias[symbol] = "sell"
            log(f"✅ HTF bias set to SELL for {symbol}")

    if timeframe == "LTF":
        last_signal[symbol] = signal
        log(f"📊 LTF signal stored: {signal}")

    return jsonify({"status": "received"})

# =========================
# PRICE UPDATE (heartbeat)
# =========================

price_store = {}

@app.route('/update_price', methods=['POST'])
def update_price():
    global open_trade, last_trade_time

    data = request.json
    symbol = data.get("symbol")
    price = float(data.get("price"))

    prev_price = price_store.get(symbol)
    price_store[symbol] = price

    log(f"\n--- AUTO ENTRY CHECK: {symbol} @ {price} ---")

    # =========================
    # CONDITIONS
    # =========================

    htf = bias.get(symbol)
    ltf = last_signal.get(symbol)

    momentum = strong_momentum(price, prev_price)
    trend = detect_trend(price, prev_price)

    log(f"HTF bias: {htf}")
    log(f"LTF signal: {ltf}")
    log(f"Momentum: {momentum}")
    log(f"Trend: {trend}")

    # =========================
    # TRADE LOGIC (AGGRESSIVE)
    # =========================

    current_time = time.time()

    if open_trade is None and htf:
        if current_time - last_trade_time < COOLDOWN:
            log("⏳ Cooldown active")
            return jsonify({"status": "cooldown"})

        decision = None

        # ✅ MOMENTUM OVERRIDE ENTRY
        if momentum:
            if htf == "buy" and trend != "down":
                decision = "buy"
                log("⚡ Momentum override BUY")
            elif htf == "sell" and trend != "up":
                decision = "sell"
                log("⚡ Momentum override SELL")

        # ✅ FALLBACK TO LTF SIGNAL
        elif ltf:
            if htf == "buy" and "bullish" in ltf:
                decision = "buy"
                log("📈 LTF confirmation BUY")
            elif htf == "sell" and "bearish" in ltf:
                decision = "sell"
                log("📉 LTF confirmation SELL")

        # =========================
        # EXECUTE TRADE
        # =========================
        if decision:
            sl = price * 0.995 if decision == "buy" else price * 1.005
            tp = price + (price - sl) * RISK_REWARD if decision == "buy" else price - (sl - price) * RISK_REWARD

            open_trade = {
                "symbol": symbol,
                "side": decision,
                "entry": price,
                "sl": sl,
                "tp": tp
            }

            last_trade_time = current_time

            log(f"🚀 TRADE TAKEN: {decision.upper()}")
            log(f"Entry: {price} | SL: {sl} | TP: {tp}")

    # =========================
    # TRADE MANAGEMENT
    # =========================

    if open_trade:
        side = open_trade["side"]
        sl = open_trade["sl"]
        tp = open_trade["tp"]

        if side == "buy":
            if price <= sl:
                log("❌ STOP LOSS HIT")
                open_trade = None
            elif price >= tp:
                log("✅ TAKE PROFIT HIT")
                open_trade = None

        elif side == "sell":
            if price >= sl:
                log("❌ STOP LOSS HIT")
                open_trade = None
            elif price <= tp:
                log("✅ TAKE PROFIT HIT")
                open_trade = None

    return jsonify({"status": "checked"})
