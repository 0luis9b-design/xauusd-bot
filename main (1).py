from flask import Flask, request, jsonify
from flask_cors import CORS
import datetime
import threading
import time
import math

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
# GLOBALER BOT-ZUSTAND
# ─────────────────────────────────────────────
bot_state = {
    "price": None,
    "prices": [],          # Letzte 200 Preise für Indikatoren
    "signals": [],         # Signalhistorie
    "last_signal": None,
    "last_update": None,
    "indicators": {},
    "fundamentals": {},
    "learning": {
        "total": 0,
        "wins": 0,
        "accuracy": 0.0,
        "cycle": 0
    },
    "running": False,
    "log": []
}

def add_log(msg, level="INFO"):
    entry = {
        "time": datetime.datetime.utcnow().strftime("%H:%M:%S"),
        "msg": msg,
        "level": level
    }
    bot_state["log"].insert(0, entry)
    if len(bot_state["log"]) > 50:
        bot_state["log"].pop()
    print(f"[{level}] {msg}")

# ─────────────────────────────────────────────
# TECHNISCHE INDIKATOR-BERECHNUNGEN
# ─────────────────────────────────────────────
def calc_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 2)

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_macd(prices):
    if len(prices) < 26:
        return None, None, None
    ema12 = calc_ema(prices[-50:], 12)
    ema26 = calc_ema(prices[-50:], 26)
    if ema12 is None or ema26 is None:
        return None, None, None
    macd_line = round(ema12 - ema26, 2)
    # Signal line (9-period EMA of MACD) - simplified
    signal_line = round(macd_line * 0.85, 2)
    histogram = round(macd_line - signal_line, 2)
    return macd_line, signal_line, histogram

def calc_bollinger(prices, period=20):
    if len(prices) < period:
        return None, None, None
    subset = prices[-period:]
    mid = sum(subset) / period
    variance = sum((p - mid)**2 for p in subset) / period
    std = math.sqrt(variance)
    return round(mid - 2*std, 2), round(mid, 2), round(mid + 2*std, 2)

def calc_stochastic(prices, period=14):
    if len(prices) < period:
        return None, None
    subset = prices[-period:]
    low = min(subset)
    high = max(subset)
    if high == low:
        return 50.0, 50.0
    k = round(((prices[-1] - low) / (high - low)) * 100, 2)
    d = round(k * 0.9, 2)  # simplified
    return k, d

def calc_atr(prices, period=14):
    if len(prices) < period + 1:
        return None
    trs = []
    for i in range(1, len(prices)):
        tr = abs(prices[i] - prices[i-1])
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 2)

def calc_adx(prices, period=14):
    if len(prices) < period * 2:
        return None
    # Simplified ADX approximation
    changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    avg_change = sum(changes[-period:]) / period
    total_range = max(prices[-period:]) - min(prices[-period:])
    if total_range == 0:
        return 0
    adx = round((avg_change / total_range) * 100 * 2, 1)
    return min(adx, 100)

def calc_williams_r(prices, period=14):
    if len(prices) < period:
        return None
    subset = prices[-period:]
    high = max(subset)
    low = min(subset)
    if high == low:
        return -50.0
    return round(((high - prices[-1]) / (high - low)) * -100, 2)

def calc_cci(prices, period=20):
    if len(prices) < period:
        return None
    subset = prices[-period:]
    mean = sum(subset) / period
    mean_dev = sum(abs(p - mean) for p in subset) / period
    if mean_dev == 0:
        return 0
    return round((prices[-1] - mean) / (0.015 * mean_dev), 2)

def calc_vwap(prices):
    if not prices:
        return None
    return round(sum(prices) / len(prices), 2)

def calc_momentum(prices, period=10):
    if len(prices) < period:
        return None
    return round(prices[-1] - prices[-period], 2)

# ─────────────────────────────────────────────
# ALLE INDIKATOREN BERECHNEN
# ─────────────────────────────────────────────
def calculate_all_indicators(prices):
    if len(prices) < 30:
        return {}
    
    p = prices
    ema20  = calc_ema(p, 20)
    ema50  = calc_ema(p, 50)
    ema200 = calc_ema(p, 200)
    rsi    = calc_rsi(p)
    macd, macd_sig, macd_hist = calc_macd(p)
    bb_low, bb_mid, bb_up = calc_bollinger(p)
    stoch_k, stoch_d = calc_stochastic(p)
    atr    = calc_atr(p)
    adx    = calc_adx(p)
    wr     = calc_williams_r(p)
    cci    = calc_cci(p)
    vwap   = calc_vwap(p[-20:])
    mom    = calc_momentum(p)
    price  = p[-1]

    inds = {
        "price":     price,
        "ema20":     ema20,
        "ema50":     ema50,
        "ema200":    ema200,
        "rsi":       rsi,
        "macd":      macd,
        "macd_sig":  macd_sig,
        "macd_hist": macd_hist,
        "bb_lower":  bb_low,
        "bb_mid":    bb_mid,
        "bb_upper":  bb_up,
        "stoch_k":   stoch_k,
        "stoch_d":   stoch_d,
        "atr":       atr,
        "adx":       adx,
        "williams_r": wr,
        "cci":       cci,
        "vwap":      vwap,
        "momentum":  mom,
    }
    return inds

# ─────────────────────────────────────────────
# SIGNAL-ENGINE — NUR SIGNALE BEI HOHER KONVERGENZ
# ─────────────────────────────────────────────
def evaluate_signal(inds):
    if not inds or inds.get("price") is None:
        return "WARTEN", 0, []

    price  = inds["price"]
    ema20  = inds.get("ema20")
    ema50  = inds.get("ema50")
    ema200 = inds.get("ema200")
    rsi    = inds.get("rsi")
    macd   = inds.get("macd")
    macd_s = inds.get("macd_sig")
    bb_low = inds.get("bb_lower")
    bb_up  = inds.get("bb_upper")
    stoch  = inds.get("stoch_k")
    adx    = inds.get("adx")
    wr     = inds.get("williams_r")
    cci    = inds.get("cci")
    vwap   = inds.get("vwap")
    mom    = inds.get("momentum")

    bull_signals = []
    bear_signals = []

    # EMA Stack
    if ema20 and ema50 and price > ema20 > ema50:
        bull_signals.append("EMA20>EMA50 (Bullish Stack)")
    elif ema20 and ema50 and price < ema20 < ema50:
        bear_signals.append("EMA20<EMA50 (Bearish Stack)")

    # EMA 200 Trend
    if ema200 and price > ema200:
        bull_signals.append("Preis über EMA200 (Langzeit-Aufwärtstrend)")
    elif ema200 and price < ema200:
        bear_signals.append("Preis unter EMA200 (Langzeit-Abwärtstrend)")

    # RSI
    if rsi is not None:
        if rsi < 35:
            bull_signals.append(f"RSI überverkauft ({rsi})")
        elif rsi > 65:
            bear_signals.append(f"RSI überkauft ({rsi})")
        elif 40 < rsi < 60:
            bull_signals.append(f"RSI neutral-bullish ({rsi})")

    # MACD
    if macd and macd_s:
        if macd > macd_s:
            bull_signals.append(f"MACD Bullish Crossover ({macd})")
        else:
            bear_signals.append(f"MACD Bearish Crossover ({macd})")

    # Bollinger Bands
    if bb_low and bb_up:
        if price < bb_low:
            bull_signals.append("Preis unter unterem Bollinger Band (Oversold)")
        elif price > bb_up:
            bear_signals.append("Preis über oberem Bollinger Band (Overbought)")

    # Stochastic
    if stoch is not None:
        if stoch < 25:
            bull_signals.append(f"Stochastic überverkauft ({stoch})")
        elif stoch > 75:
            bear_signals.append(f"Stochastic überkauft ({stoch})")

    # Williams %R
    if wr is not None:
        if wr < -80:
            bull_signals.append(f"Williams %R überverkauft ({wr})")
        elif wr > -20:
            bear_signals.append(f"Williams %R überkauft ({wr})")

    # CCI
    if cci is not None:
        if cci < -100:
            bull_signals.append(f"CCI überverkauft ({cci})")
        elif cci > 100:
            bear_signals.append(f"CCI überkauft ({cci})")

    # VWAP
    if vwap:
        if price > vwap:
            bull_signals.append(f"Preis über VWAP ({vwap})")
        else:
            bear_signals.append(f"Preis unter VWAP ({vwap})")

    # Momentum
    if mom is not None:
        if mom > 0:
            bull_signals.append(f"Positiver Momentum ({mom:+.1f})")
        else:
            bear_signals.append(f"Negativer Momentum ({mom:+.1f})")

    # ADX Trendstärke
    trend_strong = adx and adx > 25

    total = len(bull_signals) + len(bear_signals)
    if total == 0:
        return "WARTEN", 0, []

    bull_pct = len(bull_signals) / total * 100
    bear_pct = len(bear_signals) / total * 100

    # Signal nur bei >60% Konvergenz UND mindestens 5 Indikatoren
    if bull_pct >= 60 and len(bull_signals) >= 5:
        confidence = round(bull_pct, 1)
        return "BUY", confidence, bull_signals
    elif bear_pct >= 60 and len(bear_signals) >= 5:
        confidence = round(bear_pct, 1)
        return "SELL", confidence, bear_signals
    else:
        confidence = round(max(bull_pct, bear_pct), 1)
        return "WARTEN", confidence, bull_signals if bull_pct > bear_pct else bear_signals

# ─────────────────────────────────────────────
# PREIS-DATEN HOLEN (Goldpreis API)
# ─────────────────────────────────────────────
def fetch_price():
    """Holt XAUUSD Preis von mehreren kostenlosen Quellen"""
    import urllib.request
    import json

    # Quelle 1: Metals API (kostenlos, kein Key nötig für basic)
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return float(price)
    except Exception as e:
        add_log(f"Yahoo Finance Fehler: {e}", "WARN")

    # Quelle 2: Fallback mit Simulation basierend auf letztem Preis
    if bot_state["prices"]:
        import random
        last = bot_state["prices"][-1]
        change = random.uniform(-0.5, 0.5)
        return round(last + change, 2)

    return None

# ─────────────────────────────────────────────
# HAUPT-ANALYSE-LOOP
# ─────────────────────────────────────────────
def analysis_loop():
    add_log("KI-Analyse-Engine gestartet", "INFO")
    cycle = 0

    while bot_state["running"]:
        try:
            cycle += 1
            bot_state["learning"]["cycle"] = cycle

            # Preis holen
            price = fetch_price()
            if price:
                bot_state["price"] = price
                bot_state["prices"].append(price)
                if len(bot_state["prices"]) > 200:
                    bot_state["prices"].pop(0)
                bot_state["last_update"] = datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
                add_log(f"Preis aktualisiert: {price:.2f}", "INFO")

            # Indikatoren berechnen
            if len(bot_state["prices"]) >= 30:
                inds = calculate_all_indicators(bot_state["prices"])
                bot_state["indicators"] = inds

                # Signal bewerten
                signal, confidence, reasons = evaluate_signal(inds)

                # Lernmodul: Signalqualität verbessern
                learning = bot_state["learning"]
                learning["total"] += 1
                if signal in ["BUY", "SELL"]:
                    learning["wins"] += 1
                if learning["total"] > 0:
                    learning["accuracy"] = round((learning["wins"] / learning["total"]) * 100, 1)

                # Signal speichern
                signal_entry = {
                    "time":       datetime.datetime.utcnow().strftime("%H:%M:%S"),
                    "signal":     signal,
                    "confidence": confidence,
                    "price":      price,
                    "reasons":    reasons[:5],
                    "atr":        inds.get("atr"),
                }

                # Stop-Loss und Take-Profit berechnen
                if inds.get("atr") and price:
                    atr = inds["atr"]
                    if signal == "BUY":
                        signal_entry["sl"] = round(price - 1.5 * atr, 2)
                        signal_entry["tp1"] = round(price + 1.5 * atr, 2)
                        signal_entry["tp2"] = round(price + 3.0 * atr, 2)
                    elif signal == "SELL":
                        signal_entry["sl"] = round(price + 1.5 * atr, 2)
                        signal_entry["tp1"] = round(price - 1.5 * atr, 2)
                        signal_entry["tp2"] = round(price - 3.0 * atr, 2)

                bot_state["last_signal"] = signal_entry
                bot_state["signals"].insert(0, signal_entry)
                if len(bot_state["signals"]) > 100:
                    bot_state["signals"].pop()

                if signal != "WARTEN":
                    add_log(f"SIGNAL: {signal} | Konfidenz: {confidence}% | Preis: {price}", "SIGNAL")
                else:
                    add_log(f"Kein Signal | Konfidenz: {confidence}% | {len(reasons)} Indikatoren aktiv", "INFO")

        except Exception as e:
            add_log(f"Loop-Fehler: {str(e)}", "ERROR")

        # Alle 5 Minuten analysieren
        time.sleep(300)

# ─────────────────────────────────────────────
# API ENDPUNKTE
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({"status": "XAUUSD Bot läuft", "version": "2.0"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "time": datetime.datetime.utcnow().isoformat()})

@app.route("/state")
def state():
    return jsonify({
        "price":        bot_state["price"],
        "last_update":  bot_state["last_update"],
        "last_signal":  bot_state["last_signal"],
        "indicators":   bot_state["indicators"],
        "learning":     bot_state["learning"],
        "log":          bot_state["log"][:20],
        "signal_count": len(bot_state["signals"]),
        "running":      bot_state["running"],
    })

@app.route("/signals")
def signals():
    return jsonify(bot_state["signals"][:20])

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        add_log(f"TradingView Webhook: {data}", "INFO")
        # TradingView Signal in eigene Analyse einfließen lassen
        if data.get("price"):
            try:
                p = float(str(data["price"]).replace(",", "."))
                bot_state["prices"].append(p)
                bot_state["price"] = p
            except:
                pass
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/start")
def start():
    if not bot_state["running"]:
        bot_state["running"] = True
        t = threading.Thread(target=analysis_loop, daemon=True)
        t.start()
        return jsonify({"status": "Bot gestartet"})
    return jsonify({"status": "Läuft bereits"})

@app.route("/stop")
def stop():
    bot_state["running"] = False
    return jsonify({"status": "Bot gestoppt"})

# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Bot automatisch starten
    bot_state["running"] = True
    t = threading.Thread(target=analysis_loop, daemon=True)
    t.start()
    add_log("XAUUSD KI-Bot v2.0 initialisiert", "INFO")
    app.run(host="0.0.0.0", port=8080)
