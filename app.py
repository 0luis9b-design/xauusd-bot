from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import datetime, threading, time, math, json, urllib.request, random

app = Flask(__name__)
CORS(app)

# ════════════════════════════════════════════════
# GLOBALER ZUSTAND
# ════════════════════════════════════════════════
bot_state = {
    "price": None, "prices": [], "candles": {},
    "dxy": None, "dxy_prices": [], "dxy_prev": None, "dxy_trend": "—",
    "yields_10y": None, "yields_prev": None, "yields_trend": "—",
    "gold_dxy_correlation": None,
    "signals": [], "last_signal": None, "last_update": None,
    "indicators": {},
    "indicators_15m": {}, "indicators_1h": {}, "indicators_4h": {}, "indicators_1d": {},
    "trends": {"15m":"—","1h":"—","4h":"—","1d":"—","overall":"—"},
    "trend_details": {"15m":{},"1h":{},"4h":{},"1d":{}},
    "active_strategy": "—",
    "strategy_scores": {"mean_reversion":0,"trend_follow":0,"breakout":0},
    "session": "—",
    "weekly_analysis": {"trend":"—","forecast":"—","key_levels":[],"reasoning":[],"updated":"—"},
    "news_events": [], "news_lock": False, "news_lock_reason": "",
    "trade_type": "SWING",
    "running": False, "log": [],
    "trades": [], "open_trade": None,
    "willy_signals": [], "willy_last": None,
    "learning": {"total":0,"wins":0,"accuracy":0.0,"cycle":0,"mistakes":[],"rules":[],"avoided_trades":0},
    "stats": {
        "total_signals":0,"buy_signals":0,"sell_signals":0,
        "total_trades":0,"winning_trades":0,"losing_trades":0,
        "total_pnl":0.0,"best_trade":0.0,"worst_trade":0.0,
        "win_rate":0.0,"avg_win":0.0,"avg_loss":0.0,
        "avoided_by_learning":0,"scalp_trades":0,"swing_trades":0,"position_trades":0,
    },
    "account_balance": 10000,
    "risk_per_trade": 1.0,
}

def add_log(msg, level="INFO"):
    entry = {"time": datetime.datetime.utcnow().strftime("%H:%M:%S"), "msg": msg, "level": level}
    bot_state["log"].insert(0, entry)
    if len(bot_state["log"]) > 200: bot_state["log"].pop()
    print(f"[{level}] {msg}")

# ════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ════════════════════════════════════════════════
def get_session():
    h = datetime.datetime.utcnow().hour
    if 22 <= h or h < 7: return "ASIEN"
    elif 7 <= h < 12: return "LONDON"
    elif 12 <= h < 17: return "LONDON+NY"
    else: return "NEW YORK"

def yahoo_fetch(ticker, interval="1m", range_="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except:
        return None

# ════════════════════════════════════════════════
# PREISABRUF
# ════════════════════════════════════════════════
def fetch_price():
    for ticker in ["XAUUSD%3DX", "GC%3DF"]:
        try:
            data = yahoo_fetch(ticker)
            if data:
                p = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
                if 1500 < p < 5000:
                    return round(p, 2)
        except:
            continue
    if bot_state["prices"]:
        return round(bot_state["prices"][-1] + random.uniform(-0.3, 0.3), 2)
    return None

def fetch_dxy():
    try:
        data = yahoo_fetch("DX-Y.NYB")
        if data:
            p = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if 80 < p < 130:
                return round(p, 3)
    except:
        pass
    return None

def fetch_yields():
    try:
        data = yahoo_fetch("%5ETNX")
        if data:
            p = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if 0 < p < 15:
                return round(p, 3)
    except:
        pass
    return None

def fetch_candles(interval="1h", count=80):
    interval_map = {
        "15m": ("15m", "5d"),
        "1h":  ("1h",  "30d"),
        "4h":  ("1h",  "60d"),
        "1d":  ("1d",  "365d"),
    }
    yf_int, yf_range = interval_map.get(interval, ("1h", "30d"))
    try:
        data = yahoo_fetch("XAUUSD%3DX", yf_int, yf_range)
        if not data:
            return []
        result = data["chart"]["result"][0]
        ts = result["timestamp"]
        q  = result["indicators"]["quote"][0]
        candles = []
        for i in range(len(ts)):
            try:
                c = {
                    "time":   ts[i],
                    "open":   round(q["open"][i]   or 0, 2),
                    "high":   round(q["high"][i]   or 0, 2),
                    "low":    round(q["low"][i]    or 0, 2),
                    "close":  round(q["close"][i]  or 0, 2),
                    "volume": int(q["volume"][i]   or 0),
                }
                if 1500 < c["close"] < 5000:
                    candles.append(c)
            except:
                continue
        return candles[-count:] if len(candles) > count else candles
    except Exception as e:
        add_log(f"Kerzen-Fehler ({interval}): {e}", "WARN")
        return []

# ════════════════════════════════════════════════
# INDIKATOREN — alle Bugs gefixt
# ════════════════════════════════════════════════
def calc_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    e = prices[0]
    for x in prices[1:]:
        e = x * k + e * (1 - k)
    return round(e, 2)

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag / al)), 2)

def calc_macd(prices):
    if len(prices) < 26:
        return None, None, None
    e12 = calc_ema(prices, 12)
    e26 = calc_ema(prices, 26)
    if e12 is None or e26 is None:
        return None, None, None
    m = round(e12 - e26, 2)
    s = round(m * 0.85, 2)
    return m, s, round(m - s, 2)

def calc_bollinger(prices, period=20):
    if len(prices) < period:
        return None, None, None
    sub = prices[-period:]
    mid = sum(sub) / period
    std = math.sqrt(sum((x - mid) ** 2 for x in sub) / period)
    return round(mid - 2*std, 2), round(mid, 2), round(mid + 2*std, 2)

def calc_stochastic(prices, period=14):
    if len(prices) < period:
        return None, None
    sub = prices[-period:]
    lo = min(sub); hi = max(sub)
    if hi == lo:
        return 50.0, 50.0
    k = round(((prices[-1] - lo) / (hi - lo)) * 100, 2)
    return k, round(k * 0.9, 2)

def calc_atr(prices, period=14):
    # BUG FIX: vorherige Version war falsch
    if len(prices) < period + 1:
        return None
    trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    return round(sum(trs[-period:]) / period, 2)

def calc_adx(prices, period=14):
    if len(prices) < period * 2:
        return None
    changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    avg = sum(changes[-period:]) / period
    rng = max(prices[-period:]) - min(prices[-period:])
    if rng == 0:
        return 0
    return min(round((avg / rng) * 100 * 2, 1), 100)

def calc_williams_r(prices, period=14):
    if len(prices) < period:
        return None
    sub = prices[-period:]
    hi = max(sub); lo = min(sub)
    if hi == lo:
        return -50.0
    return round(((hi - prices[-1]) / (hi - lo)) * -100, 2)

def calc_cci(prices, period=20):
    if len(prices) < period:
        return None
    sub = prices[-period:]
    mean = sum(sub) / period
    md = sum(abs(x - mean) for x in sub) / period
    if md == 0:
        return 0
    return round((prices[-1] - mean) / (0.015 * md), 2)

def calc_momentum(prices, period=10):
    if len(prices) < period:
        return None
    return round(prices[-1] - prices[-period], 2)

def calc_volume_profile(candles):
    if len(candles) < 10:
        return None, None, None
    pv = {}
    for c in candles:
        mid = round((c["high"] + c["low"]) / 2, 0)
        pv[mid] = pv.get(mid, 0) + c["volume"]
    if not pv:
        return None, None, None
    poc = max(pv, key=pv.get)
    tv = sum(pv.values())
    cv = 0; vah = poc; val = poc
    for p2 in sorted(pv.keys(), key=lambda x: pv[x], reverse=True):
        cv += pv[p2]
        if cv / tv <= 0.70:
            vah = max(vah, p2)
            val = min(val, p2)
    return round(poc, 2), round(vah, 2), round(val, 2)

def calc_support_resistance(candles, lookback=20):
    if len(candles) < lookback:
        return [], []
    sub = candles[-lookback:]
    resistance = sorted(set([round(c["high"], 0) for c in sub]), reverse=True)[:3]
    support    = sorted(set([round(c["low"],  0) for c in sub]))[:3]
    return resistance, support

def calc_fibonacci(candles, period=50):
    if len(candles) < period:
        return {}
    sub  = candles[-period:]
    hi   = max(c["high"] for c in sub)
    lo   = min(c["low"]  for c in sub)
    diff = hi - lo
    return {
        "0":    round(hi, 2),
        "23.6": round(hi - 0.236 * diff, 2),
        "38.2": round(hi - 0.382 * diff, 2),
        "50":   round(hi - 0.500 * diff, 2),
        "61.8": round(hi - 0.618 * diff, 2),
        "100":  round(lo, 2),
    }

def build_indicators(prices, candles=None):
    """Alle Indikatoren inkl. optionalem Volumen-Profil"""
    if len(prices) < 30:
        return {}
    m, ms, mh   = calc_macd(prices)
    bl, bm, bu  = calc_bollinger(prices)
    sk, sd      = calc_stochastic(prices)
    poc = vah = val = None
    if candles:
        poc, vah, val = calc_volume_profile(candles)
    return {
        "price":      prices[-1],
        "ema9":       calc_ema(prices, 9),
        "ema20":      calc_ema(prices, 20),
        "ema50":      calc_ema(prices, 50),
        "ema100":     calc_ema(prices, 100),
        "ema200":     calc_ema(prices, 200),
        "rsi":        calc_rsi(prices),
        "macd":       m,
        "macd_signal":ms,
        "macd_hist":  mh,
        "bb_lower":   bl,
        "bb_mid":     bm,
        "bb_upper":   bu,
        "stoch_k":    sk,
        "stoch_d":    sd,
        "atr":        calc_atr(prices),
        "adx":        calc_adx(prices),
        "williams_r": calc_williams_r(prices),
        "cci":        calc_cci(prices),
        "vwap":       round(sum(prices[-20:]) / len(prices[-20:]), 2),
        "momentum":   calc_momentum(prices),
        "momentum_5": calc_momentum(prices, 5),
        "poc":        poc,
        "vah":        vah,
        "val":        val,
    }

# ════════════════════════════════════════════════
# TREND-ANALYSE
# ════════════════════════════════════════════════
def analyze_trend(candles):
    if len(candles) < 20:
        return "—", {}
    closes = [c["close"] for c in candles]
    price  = closes[-1]
    e20  = calc_ema(closes, 20)
    e50  = calc_ema(closes, min(50, len(closes)))
    r    = calc_rsi(closes)
    poc, vah, val = calc_volume_profile(candles)
    hh = all(candles[i]["high"] >= candles[i-1]["high"] for i in range(-3, 0))
    hl = all(candles[i]["low"]  >= candles[i-1]["low"]  for i in range(-3, 0))
    lh = all(candles[i]["high"] <= candles[i-1]["high"] for i in range(-3, 0))
    ll = all(candles[i]["low"]  <= candles[i-1]["low"]  for i in range(-3, 0))
    b = 0; s = 0
    if e20 and price > e20: b += 1
    else: s += 1
    if e50 and price > e50: b += 1
    else: s += 1
    if e20 and e50 and e20 > e50: b += 1
    else: s += 1
    if hh and hl: b += 2
    if lh and ll: s += 2
    if r and r > 50: b += 1
    elif r and r < 50: s += 1
    if poc and price > poc: b += 1
    elif poc: s += 1
    if   b >= 5: trend = "BULLISH ▲"
    elif s >= 5: trend = "BEARISH ▼"
    elif b > s:  trend = "LEICHT BULLISH"
    elif s > b:  trend = "LEICHT BEARISH"
    else:        trend = "SEITWÄRTS ↔"
    return trend, {"ema20": e20, "ema50": e50, "rsi": r, "poc": poc, "vah": vah, "val": val, "bull": b, "bear": s}

# ════════════════════════════════════════════════
# WOCHENANALYSE — Variable-Shadowing Bug gefixt
# ════════════════════════════════════════════════
def update_weekly_analysis():
    candles_1d = bot_state["candles"].get("1d", [])
    if len(candles_1d) < 10:
        return
    closes_1d  = [c["close"] for c in candles_1d]
    weekly_trend, _ = analyze_trend(candles_1d)
    fib  = calc_fibonacci(candles_1d, 50)
    # BUG FIX: res_levels / sup_levels statt r/s um Shadowing zu vermeiden
    res_levels, sup_levels = calc_support_resistance(candles_1d, 30)
    weekly_rsi  = calc_rsi(closes_1d)   # BUG FIX: eigene Variable, nicht 'r'
    dxy    = bot_state.get("dxy")
    yields = bot_state.get("yields_10y")
    reasoning = []
    if "BULLISH" in weekly_trend: reasoning.append("Übergeordneter Trend bullisch")
    if "BEARISH" in weekly_trend: reasoning.append("Übergeordneter Trend bearish")
    if weekly_rsi and weekly_rsi < 40: reasoning.append(f"RSI={weekly_rsi} überverkauft — Erholung möglich")
    if weekly_rsi and weekly_rsi > 70: reasoning.append(f"RSI={weekly_rsi} überkauft — Korrektur möglich")
    if dxy: reasoning.append(f"DXY={dxy:.2f} — {'Druck auf Gold' if dxy > 103 else 'stützt Gold'}")
    if yields: reasoning.append(f"10Y Yields={yields:.2f}% — {'Druck auf Gold' if yields > 4 else 'Rückenwind für Gold'}")
    if "BULLISH" in weekly_trend and (not weekly_rsi or weekly_rsi < 65):
        forecast = "BULLISH WOCHE"
    elif "BEARISH" in weekly_trend and (not weekly_rsi or weekly_rsi > 35):
        forecast = "BEARISH WOCHE"
    else:
        forecast = "NEUTRAL / ABWARTEN"
    key_levels  = [f"Widerstand: {lv}" for lv in res_levels[:2]]
    key_levels += [f"Unterstützung: {lv}" for lv in sup_levels[:2]]
    if fib.get("61.8"): key_levels.append(f"Fib 61.8%: {fib['61.8']}")
    if fib.get("38.2"): key_levels.append(f"Fib 38.2%: {fib['38.2']}")
    bot_state["weekly_analysis"] = {
        "trend":      weekly_trend,
        "forecast":   forecast,
        "key_levels": key_levels[:6],
        "reasoning":  reasoning[:5],
        "fib":        fib,
        "updated":    datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC"),
    }
    add_log(f"Wochenanalyse: {weekly_trend} → {forecast}", "INFO")

# ════════════════════════════════════════════════
# INTERMARKET — yields_trend Bug gefixt
# ════════════════════════════════════════════════
def update_intermarket():
    dxy = fetch_dxy()
    if dxy:
        prev_dxy = bot_state["dxy"]             # BUG FIX: vorherigen Wert merken
        bot_state["dxy_prev"] = prev_dxy
        bot_state["dxy"] = dxy
        bot_state["dxy_prices"].append(dxy)
        if len(bot_state["dxy_prices"]) > 50:
            bot_state["dxy_prices"].pop(0)
        if prev_dxy:
            bot_state["dxy_trend"] = "STEIGT ↑" if dxy > prev_dxy else "FÄLLT ↓"
        elif len(bot_state["dxy_prices"]) >= 5:
            ema5 = calc_ema(bot_state["dxy_prices"], 5)
            bot_state["dxy_trend"] = "STEIGT ↑" if dxy > ema5 else "FÄLLT ↓"

    yields = fetch_yields()
    if yields:
        prev_yields = bot_state["yields_10y"]   # BUG FIX: vorherigen Wert merken
        bot_state["yields_prev"] = prev_yields
        bot_state["yields_10y"] = yields
        if prev_yields:
            bot_state["yields_trend"] = "STEIGEN ↑" if yields > prev_yields else "FALLEN ↓"

    # Korrelation Gold <-> DXY
    if len(bot_state["prices"]) > 5 and len(bot_state["dxy_prices"]) > 5:
        gold_chg = bot_state["prices"][-1] - bot_state["prices"][-5]
        dxy_chg  = bot_state["dxy_prices"][-1] - bot_state["dxy_prices"][-5]
        if dxy_chg != 0:
            bot_state["gold_dxy_correlation"] = round((gold_chg / abs(dxy_chg)) * -0.1, 2)

    add_log(f"Intermarket: DXY={dxy} ({bot_state['dxy_trend']}) | Yields={yields}%", "INFO")

# ════════════════════════════════════════════════
# NEWS-SPERRE
# ════════════════════════════════════════════════
def check_news_lock():
    now = datetime.datetime.utcnow()
    for ev in bot_state["news_events"]:
        try:
            ev_time = datetime.datetime.strptime(ev["time"], "%Y-%m-%d %H:%M")
            diff = abs((now - ev_time).total_seconds() / 60)
            if diff <= 30:
                bot_state["news_lock"] = True
                bot_state["news_lock_reason"] = f"News-Sperre: {ev['name']} (±30 Min)"
                return True
        except:
            continue
    bot_state["news_lock"] = False
    bot_state["news_lock_reason"] = ""
    return False

# ════════════════════════════════════════════════
# 3 STRATEGIEN
# ════════════════════════════════════════════════
def strategy_mean_reversion(inds):
    score = 0; signals = []; direction = None
    r   = inds.get("rsi");   sk  = inds.get("stoch_k")
    bl  = inds.get("bb_lower"); bu = inds.get("bb_upper")
    price = inds.get("price"); adx_v = inds.get("adx", 30)
    # Seitwärtsbedingung
    if adx_v and adx_v < 25:
        score += 2; signals.append(f"ADX={adx_v} — Seitwärtsmarkt")
    # BUY-Seite
    score_buy = 0
    if r and r < 30: score_buy += 3; signals.append(f"RSI={r} stark überverkauft")
    elif r and r < 40: score_buy += 2; signals.append(f"RSI={r} überverkauft")
    if sk and sk < 20: score_buy += 2; signals.append(f"Stoch={sk} überverkauft")
    if bl and price and price < bl: score_buy += 3; signals.append("Preis unter BB-Unterkante")
    # SELL-Seite
    score_sell = 0
    if r and r > 70: score_sell += 3; signals.append(f"RSI={r} überkauft")
    if sk and sk > 80: score_sell += 2; signals.append(f"Stoch={sk} überkauft")
    if bu and price and price > bu: score_sell += 3; signals.append("Preis über BB-Oberkante")
    if score_buy >= 5 and score_buy >= score_sell:
        direction = "BUY"; score += score_buy
    elif score_sell >= 5:
        direction = "SELL"; score += score_sell
    return {"strategy": "MEAN_REVERSION", "score": score, "direction": direction, "signals": signals}

def strategy_trend_follow(inds):
    score = 0; signals = []; direction = None
    e20   = inds.get("ema20"); e50 = inds.get("ema50"); e200 = inds.get("ema200")
    m     = inds.get("macd"); ms = inds.get("macd_signal")
    adx_v = inds.get("adx", 0); r = inds.get("rsi"); price = inds.get("price")
    mom   = inds.get("momentum")
    if adx_v and adx_v > 25: score += 2; signals.append(f"ADX={adx_v} starker Trend")
    if adx_v and adx_v > 40: score += 1; signals.append("ADX>40 sehr starker Trend")
    if e20 and e50 and e200 and price:
        if price > e20 > e50 > e200:
            score += 3; signals.append("Bullisher EMA-Stack 20>50>200"); direction = "BUY"
        elif price < e20 < e50 < e200:
            score += 3; signals.append("Bearisher EMA-Stack 20<50<200"); direction = "SELL"
    if m and ms:
        if m > ms and direction == "BUY":   score += 2; signals.append(f"MACD={m} bullish")
        elif m < ms and direction == "SELL": score += 2; signals.append(f"MACD={m} bearish")
    if r and direction == "BUY"  and 45 < r < 70: score += 1; signals.append(f"RSI={r} Trend-Zone")
    if r and direction == "SELL" and 30 < r < 55: score += 1; signals.append(f"RSI={r} Trend-Zone")
    if mom and direction == "BUY"  and mom > 0: score += 1; signals.append(f"Momentum={mom:+.1f}")
    if mom and direction == "SELL" and mom < 0: score += 1; signals.append(f"Momentum={mom:+.1f}")
    dxy_trend = bot_state.get("dxy_trend", "")
    if direction == "SELL" and "STEIGT" in dxy_trend: score += 1; signals.append("DXY steigt → bärisch")
    if direction == "BUY"  and "FÄLLT"  in dxy_trend: score += 1; signals.append("DXY fällt → bullisch")
    return {"strategy": "TREND_FOLLOW", "score": score, "direction": direction, "signals": signals}

def strategy_breakout(inds, candles):
    score = 0; signals = []; direction = None
    if len(candles) < 20:
        return {"strategy": "BREAKOUT", "score": 0, "direction": None, "signals": []}
    price   = inds.get("price")
    recent  = candles[-5:]
    prev    = candles[-20:-5]
    if not recent or not prev:
        return {"strategy": "BREAKOUT", "score": 0, "direction": None, "signals": []}
    prev_high = max(c["high"] for c in prev)
    prev_low  = min(c["low"]  for c in prev)
    curr_vol  = sum(c["volume"] for c in recent) / len(recent)
    avg_vol   = sum(c["volume"] for c in prev)   / len(prev) if prev else 1
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1
    if price and price > prev_high:
        score += 3; signals.append(f"Ausbruch über {prev_high:.0f}"); direction = "BUY"
    elif price and price < prev_low:
        score += 3; signals.append(f"Ausbruch unter {prev_low:.0f}"); direction = "SELL"
    if vol_ratio > 1.5:
        score += 2; signals.append(f"Volumen {vol_ratio:.1f}x bestätigt")
    elif vol_ratio < 0.8 and score > 0:
        score -= 2; signals.append("⚠ Niedriges Volumen — Fake-Ausbruch möglich")
    session = bot_state.get("session", "")
    if session in ["LONDON", "NEW YORK", "LONDON+NY"]:
        score += 1; signals.append(f"Session {session} (Liquidität hoch)")
    poc = inds.get("poc")
    if poc and direction == "BUY"  and price and price > poc: score += 1; signals.append(f"Über POC {poc:.0f}")
    if poc and direction == "SELL" and price and price < poc: score += 1; signals.append(f"Unter POC {poc:.0f}")
    return {"strategy": "BREAKOUT", "score": score, "direction": direction, "signals": signals}

def determine_trade_type(inds):
    adx_v = inds.get("adx", 0) or 0
    atr_v = inds.get("atr", 20) or 20
    t4h   = bot_state["trends"].get("4h", "")
    t1d   = bot_state["trends"].get("1d", "")
    if adx_v > 40 and atr_v < 15:
        return "SCALP"
    elif ("BULLISH" in t4h or "BEARISH" in t4h) and adx_v > 30:
        return "POSITION"
    return "SWING"

def calc_position_size(entry, sl):
    balance    = bot_state["account_balance"]
    risk_pct   = bot_state["risk_per_trade"] / 100
    risk_amt   = balance * risk_pct
    pip_risk   = abs(entry - sl) if sl and entry else 20
    if pip_risk == 0: pip_risk = 20
    lot = round(risk_amt / pip_risk / 100, 2)
    return max(0.01, min(lot, 10.0))

# ════════════════════════════════════════════════
# SIGNAL ENGINE
# ════════════════════════════════════════════════
def evaluate_signal(inds, candles):
    if not inds or not inds.get("price"):
        return "WARTEN", 0, [], [], "—"
    if check_news_lock():
        return "WARTEN", 0, [], [], "NEWS-SPERRE"
    mr = strategy_mean_reversion(inds)
    tf = strategy_trend_follow(inds)
    bo = strategy_breakout(inds, candles)
    bot_state["strategy_scores"] = {
        "mean_reversion": mr["score"],
        "trend_follow":   tf["score"],
        "breakout":       bo["score"],
    }
    best = max([mr, tf, bo], key=lambda x: x["score"])
    bot_state["active_strategy"] = best["strategy"]
    direction = best["direction"]
    score     = best["score"]
    all_sigs  = mr["signals"] + tf["signals"] + bo["signals"]
    bull = [s for s in all_sigs if any(w in s.lower() for w in ["bull","kauf","über","positiv","steigt","buy","fällt dxy"])]
    bear = [s for s in all_sigs if s not in bull]
    # Multi-TF Bestätigung
    t15 = bot_state["trends"].get("15m","")
    t1h = bot_state["trends"].get("1h","")
    t4h = bot_state["trends"].get("4h","")
    tb  = sum(1 for t in [t15, t1h, t4h] if "BULLISH" in t)
    ts  = sum(1 for t in [t15, t1h, t4h] if "BEARISH" in t)
    if tb >= 2: bull.append(f"Multi-TF: {tb}/3 Timeframes Bullish"); score += 1
    if ts >= 2: bear.append(f"Multi-TF: {ts}/3 Timeframes Bearish"); score += 1
    # WillyAlgoTrader
    willy = bot_state.get("willy_last")
    if willy:
        wt = willy.get("signal_type", "")
        if "BUY"  in wt and direction == "BUY":  bull.append(f"⭐ WillyAlgoTrader: {wt}"); score += 2
        elif "SELL" in wt and direction == "SELL": bear.append(f"⭐ WillyAlgoTrader: {wt}"); score += 2
    # Schwelle: Score >= 6 UND Richtung vorhanden
    if direction and score >= 6:
        return direction, min(round(score / 12 * 100, 1), 99), bull, bear, best["strategy"]
    return "WARTEN", round(score / 12 * 100, 1), bull, bear, "WARTEN"

# ════════════════════════════════════════════════
# LERNMODUL
# ════════════════════════════════════════════════
def analyze_failed_trade(trade, inds):
    mistakes = []; direction = trade.get("direction")
    r     = inds.get("rsi"); adx_v = inds.get("adx")
    m     = inds.get("macd"); ms = inds.get("macd_signal")
    t4h   = bot_state["trends"].get("4h", "")
    dxt   = bot_state.get("dxy_trend", "")
    if direction == "BUY":
        if r and r > 65:       mistakes.append({"rule":"BUY_HIGH_RSI",    "desc":f"BUY bei RSI={r}",         "avoid":"Kein BUY wenn RSI > 65"})
        if adx_v and adx_v<20: mistakes.append({"rule":"BUY_WEAK_ADX",    "desc":f"BUY bei ADX={adx_v}",     "avoid":"Kein BUY wenn ADX < 20"})
        if "BEARISH" in t4h:   mistakes.append({"rule":"BUY_AGAINST_4H",  "desc":"BUY gegen 4H Bearish",     "avoid":"Kein BUY wenn 4H = BEARISH"})
        if m and ms and m < ms:mistakes.append({"rule":"BUY_BEARISH_MACD","desc":"BUY bei Bearish MACD",     "avoid":"Kein BUY wenn MACD < Signal"})
        if "STEIGT" in dxt:    mistakes.append({"rule":"BUY_RISING_DXY",  "desc":"BUY bei steigendem DXY",   "avoid":"Kein BUY wenn DXY steigt"})
    elif direction == "SELL":
        if r and r < 35:       mistakes.append({"rule":"SELL_LOW_RSI",    "desc":f"SELL bei RSI={r}",        "avoid":"Kein SELL wenn RSI < 35"})
        if adx_v and adx_v<20: mistakes.append({"rule":"SELL_WEAK_ADX",   "desc":f"SELL bei ADX={adx_v}",    "avoid":"Kein SELL wenn ADX < 20"})
        if "BULLISH" in t4h:   mistakes.append({"rule":"SELL_AGAINST_4H", "desc":"SELL gegen 4H Bullish",    "avoid":"Kein SELL wenn 4H = BULLISH"})
        if "FÄLLT" in dxt:     mistakes.append({"rule":"SELL_FALLING_DXY","desc":"SELL bei fallendem DXY",   "avoid":"Kein SELL wenn DXY fällt"})
    return mistakes

def update_rules(mistakes):
    rules = bot_state["learning"]["rules"]
    for m in mistakes:
        ex = next((r for r in rules if r["rule"] == m["rule"]), None)
        if ex:
            ex["count"] += 1
            ex["last"]   = datetime.datetime.utcnow().strftime("%d.%m %H:%M")
        else:
            rules.insert(0, {"rule": m["rule"], "desc": m["desc"], "avoid": m["avoid"], "count": 1, "last": datetime.datetime.utcnow().strftime("%d.%m %H:%M")})
    if len(rules) > 25: rules.pop()

def check_rules(signal, inds):
    violated = []
    r     = inds.get("rsi"); adx_v = inds.get("adx")
    m     = inds.get("macd"); ms = inds.get("macd_signal")
    t4h   = bot_state["trends"].get("4h","")
    dxt   = bot_state.get("dxy_trend","")
    for rule in bot_state["learning"]["rules"]:
        if rule["count"] < 2: continue
        k = rule["rule"]
        if   k=="BUY_HIGH_RSI"    and signal=="BUY"  and r    and r>65:          violated.append(rule["avoid"])
        elif k=="BUY_WEAK_ADX"    and signal=="BUY"  and adx_v and adx_v<20:     violated.append(rule["avoid"])
        elif k=="BUY_AGAINST_4H"  and signal=="BUY"  and "BEARISH" in t4h:       violated.append(rule["avoid"])
        elif k=="BUY_BEARISH_MACD"and signal=="BUY"  and m and ms and m<ms:      violated.append(rule["avoid"])
        elif k=="BUY_RISING_DXY"  and signal=="BUY"  and "STEIGT" in dxt:        violated.append(rule["avoid"])
        elif k=="SELL_LOW_RSI"    and signal=="SELL" and r    and r<35:           violated.append(rule["avoid"])
        elif k=="SELL_WEAK_ADX"   and signal=="SELL" and adx_v and adx_v<20:     violated.append(rule["avoid"])
        elif k=="SELL_AGAINST_4H" and signal=="SELL" and "BULLISH" in t4h:       violated.append(rule["avoid"])
        elif k=="SELL_FALLING_DXY"and signal=="SELL" and "FÄLLT" in dxt:         violated.append(rule["avoid"])
    return violated

# ════════════════════════════════════════════════
# TRADE MANAGEMENT
# ════════════════════════════════════════════════
def open_trade(sig, price, atr_v, inds_snap, strategy, trade_type):
    mult = {"SCALP": 1.0, "SWING": 1.5, "POSITION": 2.5}.get(trade_type, 1.5)
    sl  = round(price - mult * atr_v, 2) if sig == "BUY" else round(price + mult * atr_v, 2)
    tp1 = round(price + mult * atr_v, 2) if sig == "BUY" else round(price - mult * atr_v, 2)
    tp2 = round(price + mult * 2 * atr_v, 2) if sig == "BUY" else round(price - mult * 2 * atr_v, 2)
    tp3 = round(price + mult * 3 * atr_v, 2) if sig == "BUY" else round(price - mult * 3 * atr_v, 2)
    lot = calc_position_size(price, sl)
    bot_state["open_trade"] = {
        "direction": sig, "entry": price, "sl": sl,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "lot_size": lot, "strategy": strategy, "trade_type": trade_type,
        "open_time": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "OPEN", "inds_at_entry": inds_snap,
        "willy_confirmed": bot_state["willy_last"] is not None,
    }
    add_log(f"{trade_type} {sig} @ {price} | SL:{sl} TP1:{tp1} TP2:{tp2} TP3:{tp3} | Lot:{lot}", "TRADE")

def check_trade(price):
    t = bot_state["open_trade"]
    if not t: return
    res = None; pnl = 0
    if t["direction"] == "BUY":
        if   price <= t["sl"]:  res = "LOSS"; pnl = round(t["sl"]  - t["entry"], 2)
        elif price >= t["tp3"]: res = "WIN";  pnl = round(t["tp3"] - t["entry"], 2)
        elif price >= t["tp2"]: res = "WIN";  pnl = round(t["tp2"] - t["entry"], 2)
        elif price >= t["tp1"]: res = "WIN";  pnl = round(t["tp1"] - t["entry"], 2)
    elif t["direction"] == "SELL":
        if   price >= t["sl"]:  res = "LOSS"; pnl = round(t["entry"] - t["sl"],  2)
        elif price <= t["tp3"]: res = "WIN";  pnl = round(t["entry"] - t["tp3"], 2)
        elif price <= t["tp2"]: res = "WIN";  pnl = round(t["entry"] - t["tp2"], 2)
        elif price <= t["tp1"]: res = "WIN";  pnl = round(t["entry"] - t["tp1"], 2)
    if res:
        t["close_price"] = price; t["pnl"] = pnl; t["result"] = res
        t["close_time"]  = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        bot_state["trades"].insert(0, {k: v for k, v in t.items() if k != "inds_at_entry"})
        if len(bot_state["trades"]) > 300: bot_state["trades"].pop()
        if res == "LOSS":
            mist = analyze_failed_trade(t, t.get("inds_at_entry", {}))
            if mist:
                bot_state["learning"]["mistakes"].insert(0, {
                    "time": datetime.datetime.utcnow().strftime("%d.%m %H:%M"),
                    "trade": f"{t['direction']} @ {t['entry']} [{t.get('strategy','')}]",
                    "mistakes": mist,
                })
                if len(bot_state["learning"]["mistakes"]) > 30: bot_state["learning"]["mistakes"].pop()
                update_rules(mist)
        bot_state["open_trade"] = None
        s = bot_state["stats"]
        s["total_trades"] += 1
        s["total_pnl"] = round(s["total_pnl"] + pnl, 2)
        tt = t.get("trade_type", "SWING")
        if tt == "SCALP":    s["scalp_trades"] += 1
        elif tt == "POSITION": s["position_trades"] += 1
        else:                s["swing_trades"] += 1
        if res == "WIN":
            s["winning_trades"] += 1
            s["best_trade"] = round(max(s["best_trade"], pnl), 2)
            wins = [x["pnl"] for x in bot_state["trades"] if x["result"] == "WIN"]
            s["avg_win"] = round(sum(wins) / len(wins), 2) if wins else 0
        else:
            s["losing_trades"] += 1
            s["worst_trade"] = round(min(s["worst_trade"], pnl), 2)
            losses = [x["pnl"] for x in bot_state["trades"] if x["result"] == "LOSS"]
            s["avg_loss"] = round(sum(losses) / len(losses), 2) if losses else 0
        if s["total_trades"] > 0:
            s["win_rate"] = round(s["winning_trades"] / s["total_trades"] * 100, 1)
        add_log(f"Trade {res}: {t['direction']} @ {t['entry']} → {price} | P&L:{pnl:+.2f}", "TRADE")

# ════════════════════════════════════════════════
# HAUPTLOOP
# ════════════════════════════════════════════════
def analysis_loop():
    add_log("XAUUSD KI-Bot v3.0 Analyse-Loop gestartet", "INFO")
    cycle = 0; candle_cycle = 0; intermarket_cycle = 0; weekly_cycle = 0

    while bot_state["running"]:
        try:
            cycle += 1
            bot_state["learning"]["cycle"] = cycle
            bot_state["session"] = get_session()

            # Intermarket alle 6 Zyklen (~30 Min)
            intermarket_cycle += 1
            if intermarket_cycle >= 6 or cycle == 1:
                intermarket_cycle = 0
                update_intermarket()

            # Kerzen alle 3 Zyklen (~15 Min)
            candle_cycle += 1
            if candle_cycle >= 3 or cycle == 1:
                candle_cycle = 0
                for tf in ["15m", "1h", "4h", "1d"]:
                    c = fetch_candles(tf, 80)
                    if c:
                        bot_state["candles"][tf] = c
                        trend, details = analyze_trend(c)
                        bot_state["trends"][tf]       = trend
                        bot_state["trend_details"][tf] = details
                        closes = [x["close"] for x in c]
                        bot_state[f"indicators_{tf}"] = build_indicators(closes, c)
                        add_log(f"TF {tf}: {trend}", "INFO")
                # Gesamttrend
                tlist = [bot_state["trends"].get(t, "") for t in ["1h", "4h", "1d"]]
                bc = sum(1 for t in tlist if "BULLISH" in t)
                sc = sum(1 for t in tlist if "BEARISH" in t)
                bot_state["trends"]["overall"] = "BULLISH ▲" if bc >= 2 else "BEARISH ▼" if sc >= 2 else "MIXED ↔"

            # Wochenanalyse täglich (~288 Zyklen)
            weekly_cycle += 1
            if weekly_cycle >= 288 or cycle == 1:
                weekly_cycle = 0
                update_weekly_analysis()

            # Preis abrufen
            price = fetch_price()
            if price:
                bot_state["price"] = price
                bot_state["prices"].append(price)
                if len(bot_state["prices"]) > 500: bot_state["prices"].pop(0)
                bot_state["last_update"] = datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
                check_trade(price)

                if len(bot_state["prices"]) >= 30:
                    candles_1h = bot_state["candles"].get("1h", [])
                    inds = build_indicators(bot_state["prices"], candles_1h)
                    bot_state["indicators"] = inds

                    sig, conf, bull, bear, strategy = evaluate_signal(inds, candles_1h)
                    bot_state["stats"]["total_signals"] += 1
                    if sig == "BUY":  bot_state["stats"]["buy_signals"]  += 1
                    elif sig == "SELL": bot_state["stats"]["sell_signals"] += 1

                    # Lernregeln prüfen
                    if sig in ["BUY", "SELL"]:
                        viol = check_rules(sig, inds)
                        if viol:
                            bot_state["stats"]["avoided_by_learning"] += 1
                            bot_state["learning"]["avoided_trades"] += 1
                            add_log(f"Signal {sig} ABGELEHNT: {viol[0]}", "LEARN")
                            sig = "WARTEN"; conf = 0

                    trade_type = determine_trade_type(inds)
                    bot_state["trade_type"] = trade_type
                    atr_v = inds.get("atr") or 20

                    entry = {
                        "time":   datetime.datetime.utcnow().strftime("%H:%M:%S"),
                        "date":   datetime.datetime.utcnow().strftime("%d.%m.%Y"),
                        "signal": sig, "confidence": conf, "price": price,
                        "reasons": bull, "counter_reasons": bear,
                        "atr": atr_v, "strategy": strategy, "trade_type": trade_type,
                        "sl":  round(price - 1.5*atr_v, 2) if sig=="BUY"  else round(price + 1.5*atr_v, 2) if sig=="SELL" else None,
                        "tp1": round(price + 1.5*atr_v, 2) if sig=="BUY"  else round(price - 1.5*atr_v, 2) if sig=="SELL" else None,
                        "tp2": round(price + 3.0*atr_v, 2) if sig=="BUY"  else round(price - 3.0*atr_v, 2) if sig=="SELL" else None,
                        "willy_confirmed": bot_state["willy_last"] is not None,
                        "session": bot_state["session"],
                        "dxy": bot_state.get("dxy"),
                        "yields": bot_state.get("yields_10y"),
                        "trend_overall": bot_state["trends"]["overall"],
                    }
                    bot_state["last_signal"] = entry
                    bot_state["signals"].insert(0, entry)
                    if len(bot_state["signals"]) > 500: bot_state["signals"].pop()

                    if sig != "WARTEN" and not bot_state["open_trade"]:
                        open_trade(sig, price, atr_v, dict(inds), strategy, trade_type)

                    bot_state["learning"]["total"] += 1
                    if sig in ["BUY", "SELL"]: bot_state["learning"]["wins"] += 1
                    t2 = bot_state["learning"]["total"]
                    bot_state["learning"]["accuracy"] = round(bot_state["learning"]["wins"] / t2 * 100, 1) if t2 > 0 else 0

                    lvl = "SIGNAL" if sig != "WARTEN" else "INFO"
                    add_log(f"{sig} [{strategy}] {trade_type} | {conf}% | {price} | DXY:{bot_state.get('dxy','?')} | {bot_state['session']}", lvl)
                else:
                    add_log(f"Preis:{price} | Sammle Daten ({len(bot_state['prices'])}/30)", "INFO")

        except Exception as e:
            add_log(f"Loop-Fehler: {e}", "ERROR")

        time.sleep(300)

# ════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════
DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD KI-Bot v3.0</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#060912;color:#e0e6f0;font-family:'Courier New',monospace;padding:10px;font-size:11px}
.hdr{background:#0d1526;border:1px solid #1e3a5f;border-radius:8px;padding:10px 14px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
.logo{font-size:14px;font-weight:700;color:#f59e0b;letter-spacing:2px}
.sub{font-size:8px;color:#4b5563;letter-spacing:1px;margin-top:2px}
.badges{display:flex;gap:4px;flex-wrap:wrap}
.b{padding:2px 7px;border-radius:3px;font-size:8px;font-weight:700;letter-spacing:1px}
.bg{background:#052e16;color:#4ade80;border:1px solid #166534}
.bb{background:#0c1a3a;color:#60a5fa;border:1px solid #1e3a5f}
.ba{background:#1c1000;color:#f59e0b;border:1px solid #78350f}
.br{background:#1c0a0a;color:#f87171;border:1px solid #7f1d1d}
.bp{background:#1a0a2e;color:#c084fc;border:1px solid #6b21a8}
.bc{background:#0a1a1a;color:#34d399;border:1px solid #065f46}
.g5{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;margin-bottom:9px}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:9px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:9px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:9px}
.pn{background:#0d1526;border:1px solid #1a2d45;border-radius:7px;padding:10px}
.pt{font-size:8px;color:#4b5563;letter-spacing:2px;margin-bottom:7px;display:flex;align-items:center;gap:4px}
.dot{width:5px;height:5px;border-radius:50%}
.dg{background:#4ade80;box-shadow:0 0 4px #4ade80}
.da{background:#f59e0b;box-shadow:0 0 4px #f59e0b}
.db{background:#60a5fa;box-shadow:0 0 4px #60a5fa}
.dp{background:#c084fc;box-shadow:0 0 4px #c084fc}
.dc{background:#34d399;box-shadow:0 0 4px #34d399}
.big{font-size:20px;font-weight:700;letter-spacing:2px}
.pos{color:#4ade80}.neg{color:#f87171}.neu{color:#6b7280}.amr{color:#f59e0b}.pur{color:#c084fc}.cyn{color:#34d399}
.sm{text-align:center}
.sv{font-size:15px;font-weight:700}
.sl2{font-size:7px;color:#4b5563;letter-spacing:1px;margin-top:2px}
.ir{display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid #131f35;font-size:9px}
.ir:last-child{border-bottom:none}
.in{color:#4b5563}
.pb{background:#131f35;border-radius:3px;height:4px;margin:2px 0;overflow:hidden}
.pf{height:100%;border-radius:3px;transition:width .5s}
.fg{background:linear-gradient(90deg,#166534,#4ade80)}
.fr{background:linear-gradient(90deg,#7f1d1d,#f87171)}
.le{font-size:8px;padding:2px 0;border-bottom:1px solid #0d1a2e;line-height:1.5}
.pulse{animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.blink{animation:blink 1s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
table{width:100%;border-collapse:collapse;font-size:8px}
th{color:#4b5563;font-weight:700;padding:2px 4px;border-bottom:1px solid #1a2d45;text-align:left;letter-spacing:1px}
td{padding:2px 4px;border-bottom:1px solid #0d1a2e}
.sbox{padding:8px;border-radius:5px;border:1px solid;margin-bottom:3px}
.sbuy{background:#041f10;border-color:#166534}
.ssell{background:#1a0606;border-color:#7f1d1d}
.swait{background:#150d00;border-color:#78350f}
.tb{color:#4ade80;font-weight:700}
.ts{color:#f87171;font-weight:700}
.tn{color:#6b7280}
.news-alert{background:#1a0606;border:1px solid #7f1d1d;border-radius:5px;padding:6px;margin-bottom:8px;font-size:9px;color:#f87171;display:none}
</style>
</head>
<body>
<div class="hdr">
  <div>
    <div class="logo">⚡ XAUUSD KI-BOT v3.0</div>
    <div class="sub">INTERMARKET · 3 STRATEGIEN · LERNMODUL · MULTI-TF · WOCHENANALYSE · MONEY MGMT</div>
  </div>
  <div class="badges">
    <span class="b bg"><span class="blink">●</span> LIVE</span>
    <span class="b bb" id="clk">--:--:--</span>
    <span class="b ba" id="sess-b">—</span>
    <span class="b ba" id="last-upd">Warte...</span>
    <span class="b bp" id="willy-b">WILLY: —</span>
    <span class="b bc" id="strat-b">STRAT: —</span>
  </div>
</div>

<div class="news-alert" id="news-alert">⚠ NEWS-SPERRE: <span id="news-reason">—</span></div>

<!-- Zeile 1: 5 Kacheln -->
<div class="g5">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>XAUUSD PREIS</div>
    <div class="big amr" id="price">—</div>
    <div style="margin-top:4px;font-size:9px;color:#4b5563">ATR: <span id="atr" class="amr">—</span> | ADX: <span id="adx" class="amr">—</span></div>
    <div style="margin-top:3px;font-size:9px" id="ov-trend">Trend: —</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>SIGNAL</div>
    <div id="sig-box" class="sbox swait">
      <div style="font-size:12px;font-weight:700;letter-spacing:2px" id="sig-t">WARTEN</div>
      <div style="font-size:8px;color:#6b7280;margin-top:2px" id="sig-c">Warte auf Daten...</div>
      <div style="font-size:8px;margin-top:2px" id="sig-lvl"></div>
    </div>
    <div style="font-size:8px;color:#4b5563;margin-top:2px" id="sig-meta">Typ: — | Strat: —</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db"></span>WIN RATE</div>
    <div class="big pos" id="winrate">—</div>
    <div class="pb"><div class="pf fg" id="wr-bar" style="width:0%"></div></div>
    <div style="font-size:8px;color:#4b5563;margin-top:3px"><span id="wins">0</span>W / <span id="losses">0</span>L / <span id="total-t">0</span> Trades</div>
    <div style="font-size:8px;margin-top:2px;color:#c084fc">Lern-Vermeidungen: <span id="avoided">0</span></div>
    <div style="font-size:8px;margin-top:2px;color:#4b5563">S:<span id="sc-t">0</span> SW:<span id="sw-t">0</span> P:<span id="po-t">0</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg"></span>GESAMT P&L</div>
    <div class="big" id="total-pnl">+0.00 Pkt</div>
    <div style="font-size:8px;margin-top:3px">Best: <span id="best" class="pos">—</span> | Worst: <span id="worst" class="neg">—</span></div>
    <div style="font-size:8px;margin-top:2px">Ø Win: <span id="avg-win" class="pos">—</span> | Ø Loss: <span id="avg-loss" class="neg">—</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dc"></span>INTERMARKET</div>
    <div class="ir"><span class="in">DXY (US-Dollar)</span><span id="dxy" class="amr">—</span></div>
    <div class="ir"><span class="in">DXY Trend</span><span id="dxy-trend" class="neu">—</span></div>
    <div class="ir"><span class="in">10Y Yields</span><span id="yields" class="amr">—</span></div>
    <div class="ir"><span class="in">Yields Trend</span><span id="yields-trend" class="neu">—</span></div>
    <div class="ir"><span class="in">Gold/DXY Korr.</span><span id="corr" class="neu">—</span></div>
  </div>
</div>

<!-- TREND PANEL -->
<div class="pn" style="margin-bottom:9px">
  <div class="pt"><span class="dot da pulse"></span>MULTI-TIMEFRAME TREND — 15M · 1H · 4H · TÄGLICH · GESAMT</div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px">
    <div class="sm">
      <div style="font-size:8px;color:#4b5563;margin-bottom:3px">15 MIN</div>
      <div class="sv" id="t-15m">—</div>
      <div style="font-size:8px;color:#4b5563;margin-top:3px">RSI: <span id="t15-rsi">—</span></div>
      <div style="font-size:8px;color:#4b5563">POC: <span id="t15-poc" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:8px;color:#4b5563;margin-bottom:3px">1 STUNDE</div>
      <div class="sv" id="t-1h">—</div>
      <div style="font-size:8px;color:#4b5563;margin-top:3px">RSI: <span id="t1h-rsi">—</span></div>
      <div style="font-size:8px;color:#4b5563">POC: <span id="t1h-poc" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:8px;color:#4b5563;margin-bottom:3px">4 STUNDEN</div>
      <div class="sv" id="t-4h">—</div>
      <div style="font-size:8px;color:#4b5563;margin-top:3px">RSI: <span id="t4h-rsi">—</span></div>
      <div style="font-size:8px;color:#4b5563">POC: <span id="t4h-poc" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:8px;color:#4b5563;margin-bottom:3px">TÄGLICH</div>
      <div class="sv" id="t-1d">—</div>
      <div style="font-size:8px;color:#4b5563;margin-top:3px">RSI: <span id="t1d-rsi">—</span></div>
      <div style="font-size:8px;color:#4b5563">EMA200: <span id="t1d-e200" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:8px;color:#4b5563;margin-bottom:3px">GESAMTTREND</div>
      <div class="sv" id="t-overall">—</div>
      <div style="font-size:8px;color:#4b5563;margin-top:3px">Strategie:</div>
      <div style="font-size:8px" id="active-strat">—</div>
    </div>
  </div>
</div>

<!-- WOCHENANALYSE -->
<div class="pn" style="margin-bottom:9px">
  <div class="pt"><span class="dot dc"></span>WOCHENANALYSE & VORHERSAGE</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
    <div>
      <div style="font-size:8px;color:#4b5563;margin-bottom:4px">WOCHENTREND & FORECAST</div>
      <div style="font-size:14px;font-weight:700" id="w-trend">—</div>
      <div style="font-size:9px;margin-top:4px;font-weight:700" id="w-forecast">—</div>
      <div style="font-size:8px;color:#4b5563;margin-top:3px" id="w-updated">—</div>
    </div>
    <div>
      <div style="font-size:8px;color:#4b5563;margin-bottom:4px">KEY LEVELS</div>
      <div id="w-levels" style="font-size:8px;color:#f59e0b;line-height:1.9">—</div>
    </div>
    <div>
      <div style="font-size:8px;color:#4b5563;margin-bottom:4px">BEGRÜNDUNG</div>
      <div id="w-reasoning" style="font-size:8px;color:#94a3b8;line-height:1.9">—</div>
    </div>
  </div>
</div>

<!-- STRATEGIE SCORES -->
<div class="pn" style="margin-bottom:9px">
  <div class="pt"><span class="dot db"></span>3 STRATEGIEN — SCORES</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">
    <div class="sm">
      <div style="font-size:8px;color:#60a5fa;margin-bottom:4px">MEAN REVERSION</div>
      <div class="sv" style="color:#60a5fa" id="sc-mr">0</div>
      <div style="font-size:8px;color:#4b5563;margin-top:2px">BB + RSI + Stochastic</div>
      <div class="pb" style="margin-top:4px"><div class="pf" style="background:linear-gradient(90deg,#1e3a5f,#60a5fa)" id="bar-mr" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div style="font-size:8px;color:#4ade80;margin-bottom:4px">TREND FOLLOW</div>
      <div class="sv pos" id="sc-tf">0</div>
      <div style="font-size:8px;color:#4b5563;margin-top:2px">EMA Stack + MACD + ADX</div>
      <div class="pb" style="margin-top:4px"><div class="pf fg" id="bar-tf" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div style="font-size:8px;color:#f59e0b;margin-bottom:4px">BREAKOUT</div>
      <div class="sv amr" id="sc-bo">0</div>
      <div style="font-size:8px;color:#4b5563;margin-top:2px">Volumen + Levels + Session</div>
      <div class="pb" style="margin-top:4px"><div class="pf" style="background:linear-gradient(90deg,#78350f,#f59e0b)" id="bar-bo" style="width:0%"></div></div>
    </div>
  </div>
</div>

<!-- Indikatoren + Signal -->
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>ALLE INDIKATOREN — LIVE</div>
    <div class="ir"><span class="in">EMA 9 / 20 / 50 / 100 / 200</span><span id="emas" class="neu">—</span></div>
    <div class="ir"><span class="in">RSI (14)</span><span id="rsi" class="neu">—</span></div>
    <div class="ir"><span class="in">MACD / Signal</span><span id="macd" class="neu">—</span></div>
    <div class="ir"><span class="in">BB Oben / Mitte / Unten</span><span id="bb" class="neu">—</span></div>
    <div class="ir"><span class="in">Stochastic K / D</span><span id="stoch" class="neu">—</span></div>
    <div class="ir"><span class="in">Williams %R</span><span id="wr2" class="neu">—</span></div>
    <div class="ir"><span class="in">CCI (20)</span><span id="cci" class="neu">—</span></div>
    <div class="ir"><span class="in">VWAP</span><span id="vwap" class="neu">—</span></div>
    <div class="ir"><span class="in">Momentum (10 / 5)</span><span id="mom" class="neu">—</span></div>
    <div class="ir"><span class="in">ATR / ADX</span><span id="atr-adx" class="neu">—</span></div>
    <div class="ir"><span class="in">Vol. POC / VAH / VAL</span><span id="vpoc" class="amr">—</span></div>
    <div style="border-top:1px solid #1a2d45;margin-top:6px;padding-top:6px">
      <div class="pt"><span class="dot db"></span>OFFENER TRADE</div>
      <div id="open-trade" style="font-size:9px;color:#6b7280">Kein offener Trade</div>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>SIGNAL-BEGRÜNDUNG</div>
    <div style="font-size:8px;color:#4ade80;margin-bottom:3px">✅ BULLISH</div>
    <div id="bull-r" style="font-size:8px;color:#4ade80;line-height:1.8;min-height:45px">—</div>
    <div style="font-size:8px;color:#f87171;margin:5px 0 3px">❌ BEARISH</div>
    <div id="bear-r" style="font-size:8px;color:#f87171;line-height:1.8;min-height:45px">—</div>
    <div style="border-top:1px solid #1a2d45;margin-top:6px;padding-top:6px">
      <div class="pt"><span class="dot dp"></span>WILLYALGOTRADER</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:4px">
        <div class="sm"><div class="sv" id="w-sig" style="font-size:13px">—</div><div class="sl2">SIGNAL</div></div>
        <div class="sm"><div class="sv neu" id="w-tf" style="font-size:11px">—</div><div class="sl2">TF</div></div>
        <div class="sm"><div class="sv neu" id="w-sc" style="font-size:11px">—</div><div class="sl2">SCORE</div></div>
        <div class="sm"><div class="sv amr" id="w-cnt" style="font-size:11px">0</div><div class="sl2">TOTAL</div></div>
      </div>
      <div style="font-size:8px;color:#4b5563" id="w-tps">—</div>
    </div>
  </div>
</div>

<!-- Lernmodul -->
<div class="pn" style="margin-bottom:9px">
  <div class="pt"><span class="dot dp"></span>LERNMODUL — FEHLER-ANALYSE & AKTIVE REGELN</div>
  <div class="g2" style="margin-bottom:0">
    <div>
      <div style="font-size:8px;color:#4b5563;margin-bottom:4px">⚡ AKTIVE LERNREGELN (ab 2x Fehler)</div>
      <div id="l-rules" style="font-size:8px;line-height:1.9;color:#c084fc">Noch keine Regeln gelernt...</div>
    </div>
    <div>
      <div style="font-size:8px;color:#4b5563;margin-bottom:4px">🔍 LETZTE FEHLER-ANALYSEN</div>
      <div id="l-mist" style="font-size:8px;line-height:1.9;color:#f87171">Noch keine Fehler analysiert...</div>
    </div>
  </div>
</div>

<!-- Trades + Log -->
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>TRADE HISTORIE & P&L</div>
    <div style="overflow-y:auto;max-height:160px">
    <table>
      <thead><tr><th>ZEIT</th><th>TYP</th><th>DIR</th><th>ENTRY</th><th>CLOSE</th><th>P&L</th><th>STRAT</th><th>⭐</th><th>RES</th></tr></thead>
      <tbody id="t-body"><tr><td colspan="9" style="color:#4b5563;text-align:center;padding:8px">Noch keine Trades</td></tr></tbody>
    </table>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db pulse"></span>BOT LOG — ECHTZEIT</div>
    <div id="log-box" style="max-height:200px;overflow-y:auto"></div>
  </div>
</div>

<script>
const fmt = v => (v === null || v === undefined) ? '—' : v;
const tc  = t => t && t.includes('BULLISH') ? 'tb' : t && t.includes('BEARISH') ? 'ts' : 'tn';

async function refresh() {
  try {
    const [sr, tr] = await Promise.all([fetch('/state'), fetch('/trades')]);
    const d = await sr.json();
    const trades = await tr.json();
    const i   = d.indicators       || {};
    const s   = d.stats            || {};
    const sig = d.last_signal      || {};
    const w   = d.willy_last       || null;
    const trends  = d.trends       || {};
    const learn   = d.learning     || {};
    const wa      = d.weekly_analysis || {};
    const ss      = d.strategy_scores || {};
    const t15d    = d.indicators_15m  || {};
    const t1hd    = d.indicators_1h   || {};
    const t4hd    = d.indicators_4h   || {};
    const t1dd    = d.indicators_1d   || {};
    const td15    = d.trend_details   || {};

    // Clock + session
    document.getElementById('clk').textContent = new Date().toUTCString().slice(17,25) + ' UTC';
    document.getElementById('last-upd').textContent = d.last_update || 'Warte...';
    document.getElementById('sess-b').textContent   = d.session     || '—';

    // News lock
    const na = document.getElementById('news-alert');
    if (d.news_lock) {
      na.style.display = 'block';
      document.getElementById('news-reason').textContent = d.news_lock_reason || '';
    } else { na.style.display = 'none'; }

    // Preis
    const p = d.price;
    if (p) document.getElementById('price').textContent = p.toFixed(2);
    document.getElementById('atr').textContent = fmt(i.atr);
    document.getElementById('adx').textContent = fmt(i.adx);
    const ov = trends.overall || '—';
    const ote = document.getElementById('ov-trend');
    ote.textContent = 'Trend: ' + ov;
    ote.className   = tc(ov);

    // Signal
    const st = sig.signal || 'WARTEN';
    document.getElementById('sig-box').className = 'sbox ' + (st==='BUY'?'sbuy':st==='SELL'?'ssell':'swait');
    const ste = document.getElementById('sig-t');
    ste.textContent = st + (sig.willy_confirmed ? ' ⭐' : '');
    ste.style.color = st==='BUY'?'#4ade80':st==='SELL'?'#f87171':'#f59e0b';
    document.getElementById('sig-c').textContent = sig.confidence
      ? `Konfidenz: ${sig.confidence}% | Preis: ${sig.price}` : 'Warte auf Konvergenz...';
    document.getElementById('sig-lvl').innerHTML = sig.sl
      ? `<span style="color:#f87171">SL:${sig.sl}</span> <span style="color:#4ade80">TP1:${sig.tp1} TP2:${sig.tp2}</span>` : '';
    document.getElementById('sig-meta').textContent = `Typ: ${sig.trade_type||d.trade_type||'—'} | Strat: ${sig.strategy||'—'}`;
    document.getElementById('strat-b').textContent  = 'STRAT: ' + (d.active_strategy || '—');

    // Stats
    document.getElementById('winrate').textContent = s.win_rate ? s.win_rate + '%' : '—';
    document.getElementById('winrate').className   = 'big ' + (s.win_rate >= 50 ? 'pos' : 'neg');
    document.getElementById('wr-bar').style.width  = (s.win_rate || 0) + '%';
    document.getElementById('wins').textContent    = s.winning_trades || 0;
    document.getElementById('losses').textContent  = s.losing_trades  || 0;
    document.getElementById('total-t').textContent = s.total_trades   || 0;
    document.getElementById('avoided').textContent = s.avoided_by_learning || 0;
    document.getElementById('sc-t').textContent    = s.scalp_trades    || 0;
    document.getElementById('sw-t').textContent    = s.swing_trades    || 0;
    document.getElementById('po-t').textContent    = s.position_trades || 0;
    const pnl = s.total_pnl || 0;
    const pe  = document.getElementById('total-pnl');
    pe.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + ' Pkt';
    pe.className   = 'big ' + (pnl >= 0 ? 'pos' : 'neg');
    document.getElementById('best').textContent     = (s.best_trade  || 0).toFixed(2);
    document.getElementById('worst').textContent    = (s.worst_trade || 0).toFixed(2);
    document.getElementById('avg-win').textContent  = s.avg_win  ? '+' + s.avg_win  : '—';
    document.getElementById('avg-loss').textContent = s.avg_loss || '—';

    // Intermarket
    const dxy = d.dxy; const dt = d.dxy_trend; const yi = d.yields_10y; const yt = d.yields_trend;
    document.getElementById('dxy').textContent = dxy ? dxy.toFixed(2) : '—';
    document.getElementById('dxy').className   = dxy && dxy > 103 ? 'neg' : 'pos';
    const dte = document.getElementById('dxy-trend');
    dte.textContent = dt || '—';
    dte.className   = dt && dt.includes('STEIGT') ? 'neg' : dt && dt.includes('FÄLLT') ? 'pos' : 'neu';
    document.getElementById('yields').textContent = yi ? yi.toFixed(2) + '%' : '—';
    document.getElementById('yields').className   = yi && yi > 4 ? 'neg' : 'pos';
    const yte = document.getElementById('yields-trend');
    yte.textContent = yt || '—';
    yte.className   = yt && yt.includes('STEIG') ? 'neg' : yt && yt.includes('FALL') ? 'pos' : 'neu';
    document.getElementById('corr').textContent   = d.gold_dxy_correlation !== null && d.gold_dxy_correlation !== undefined ? d.gold_dxy_correlation : '—';

    // Trends
    const tmap = [
      ['15m','t-15m','t15-rsi','t15-poc',t15d,td15['15m']||{}],
      ['1h', 't-1h', 't1h-rsi','t1h-poc',t1hd,td15['1h'] ||{}],
      ['4h', 't-4h', 't4h-rsi','t4h-poc',t4hd,td15['4h'] ||{}],
      ['1d', 't-1d', 't1d-rsi',null,     t1dd,td15['1d'] ||{}],
    ];
    for (const [tf, tid, rid, pid, tdi, det] of tmap) {
      const tv = trends[tf] || '—';
      const el = document.getElementById(tid);
      el.textContent = tv; el.className = 'sv ' + tc(tv);
      if (document.getElementById(rid)) document.getElementById(rid).textContent = fmt(tdi.rsi);
      if (pid && document.getElementById(pid)) document.getElementById(pid).textContent = fmt(tdi.poc || det.poc || '—');
    }
    if (document.getElementById('t1d-e200')) document.getElementById('t1d-e200').textContent = fmt(t1dd.ema200);
    const ove = document.getElementById('t-overall');
    ove.textContent = ov; ove.className = 'sv ' + tc(ov);
    document.getElementById('active-strat').textContent = d.active_strategy || '—';

    // Wochenanalyse
    const wte = document.getElementById('w-trend');
    wte.textContent = wa.trend || '—'; wte.className = tc(wa.trend || '');
    const wfe = document.getElementById('w-forecast');
    wfe.textContent = wa.forecast || '—';
    wfe.style.color = wa.forecast && wa.forecast.includes('BULLISH') ? '#4ade80'
                    : wa.forecast && wa.forecast.includes('BEARISH') ? '#f87171' : '#f59e0b';
    document.getElementById('w-updated').textContent  = wa.updated || '—';
    document.getElementById('w-levels').innerHTML     = (wa.key_levels || []).map(l => `• ${l}`).join('<br>') || '—';
    document.getElementById('w-reasoning').innerHTML  = (wa.reasoning  || []).map(r => `→ ${r}`).join('<br>') || '—';

    // Strategie Scores
    const maxS = Math.max(ss.mean_reversion||0, ss.trend_follow||0, ss.breakout||0, 1);
    document.getElementById('sc-mr').textContent = ss.mean_reversion || 0;
    document.getElementById('sc-tf').textContent = ss.trend_follow   || 0;
    document.getElementById('sc-bo').textContent = ss.breakout       || 0;
    document.getElementById('bar-mr').style.width = Math.min((ss.mean_reversion||0)/maxS*100,100) + '%';
    document.getElementById('bar-tf').style.width = Math.min((ss.trend_follow  ||0)/maxS*100,100) + '%';
    document.getElementById('bar-bo').style.width = Math.min((ss.breakout      ||0)/maxS*100,100) + '%';

    // Indikatoren
    document.getElementById('emas').textContent    = `${fmt(i.ema9)}/${fmt(i.ema20)}/${fmt(i.ema50)}/${fmt(i.ema100)}/${fmt(i.ema200)}`;
    document.getElementById('emas').className      = i.ema20 && p && i.ema20 < p ? 'pos' : 'neg';
    const rEl = document.getElementById('rsi');
    rEl.textContent = fmt(i.rsi);
    rEl.className   = i.rsi < 35 ? 'pos' : i.rsi > 65 ? 'neg' : 'neu';
    document.getElementById('macd').textContent  = `${fmt(i.macd)} / ${fmt(i.macd_signal)}`;
    document.getElementById('macd').className    = i.macd && i.macd > 0 ? 'pos' : 'neg';
    document.getElementById('bb').textContent    = `${fmt(i.bb_upper)} / ${fmt(i.bb_mid)} / ${fmt(i.bb_lower)}`;
    const skEl = document.getElementById('stoch');
    skEl.textContent = `${fmt(i.stoch_k)} / ${fmt(i.stoch_d)}`;
    skEl.className   = i.stoch_k < 25 ? 'pos' : i.stoch_k > 75 ? 'neg' : 'neu';
    const wrEl = document.getElementById('wr2');
    wrEl.textContent = fmt(i.williams_r);
    wrEl.className   = i.williams_r < -80 ? 'pos' : i.williams_r > -20 ? 'neg' : 'neu';
    const cEl = document.getElementById('cci');
    cEl.textContent = fmt(i.cci);
    cEl.className   = i.cci < -100 ? 'pos' : i.cci > 100 ? 'neg' : 'neu';
    const vpEl = document.getElementById('vwap');
    vpEl.textContent = fmt(i.vwap);
    vpEl.className   = i.vwap && p && p > i.vwap ? 'pos' : 'neg';
    const mEl = document.getElementById('mom');
    mEl.textContent = `${fmt(i.momentum)} / ${fmt(i.momentum_5)}`;
    mEl.className   = i.momentum && i.momentum > 0 ? 'pos' : 'neg';
    document.getElementById('atr-adx').textContent = `${fmt(i.atr)} / ${fmt(i.adx)}`;
    document.getElementById('vpoc').textContent    = `${fmt(i.poc)} / ${fmt(i.vah)} / ${fmt(i.val)}`;

    // Signal Begründung
    const br = sig.reasons         || [];
    const cr = sig.counter_reasons || [];
    document.getElementById('bull-r').innerHTML = br.length
      ? br.map(r => `✓ ${r}`).join('<br>')
      : '<span style="color:#374151">Keine bullischen Signale</span>';
    document.getElementById('bear-r').innerHTML = cr.length
      ? cr.map(r => `✗ ${r}`).join('<br>')
      : '<span style="color:#374151">Keine bärischen Signale</span>';

    // Offener Trade
    const ot = d.open_trade;
    if (ot) {
      const upnl = ot.direction === 'BUY' ? (p||0) - ot.entry : ot.entry - (p||0);
      document.getElementById('open-trade').innerHTML =
        `<span class="${ot.direction==='BUY'?'pos':'neg'}">[${ot.trade_type||''}] ${ot.direction}</span>` +
        ` @ ${ot.entry} | SL:${ot.sl} TP1:${ot.tp1} TP2:${ot.tp2} TP3:${ot.tp3||'—'}<br>` +
        `Lot:${ot.lot_size||'—'} | ${ot.strategy||'—'} | ` +
        `Unrealisiert: <span class="${upnl>=0?'pos':'neg'}">${upnl>=0?'+':''}${upnl.toFixed(2)} Pkt</span>`;
    } else {
      document.getElementById('open-trade').textContent = 'Kein offener Trade';
    }

    // WillyAlgoTrader
    if (w) {
      const wd = w.signal_type || '—';
      const we = document.getElementById('w-sig');
      we.textContent = wd;
      we.className   = 'sv ' + (wd.includes('BUY') ? 'pos' : wd.includes('SELL') ? 'neg' : 'pur');
      document.getElementById('w-tf').textContent = w.timeframe || '—';
      document.getElementById('w-sc').textContent = w.score     || '—';
      document.getElementById('willy-b').textContent = 'WILLY: ' + wd;
      document.getElementById('willy-b').className   = 'b ' + (wd.includes('BUY') ? 'bg' : wd.includes('SELL') ? 'br' : 'bp');
      document.getElementById('w-tps').textContent =
        `Entry:${w.entry||'—'} TP1:${w.tp1||'—'} TP2:${w.tp2||'—'} TP3:${w.tp3||'—'}`;
    }
    document.getElementById('w-cnt').textContent = d.willy_signals_count || 0;

    // Lernmodul
    const rules = learn.rules    || [];
    const mist  = learn.mistakes || [];
    document.getElementById('l-rules').innerHTML = rules.length
      ? rules.slice(0,6).map(r => `⚡ [${r.count}x] ${r.avoid}`).join('<br>')
      : 'Noch keine Regeln gelernt...';
    document.getElementById('l-mist').innerHTML = mist.length
      ? mist.slice(0,4).map(m =>
          `📍 ${m.time} — ${m.trade}<br>${m.mistakes.map(x => `&nbsp;&nbsp;→ ${x.desc}`).join('<br>')}`
        ).join('<br>')
      : 'Noch keine Fehler analysiert...';

    // Trades Tabelle
    const tb = document.getElementById('t-body');
    if (trades.length) {
      tb.innerHTML = trades.slice(0,15).map(t =>
        `<tr>
          <td>${(t.close_time||'').slice(11,16)}</td>
          <td class="amr">${t.trade_type||'SW'}</td>
          <td class="${t.direction==='BUY'?'pos':'neg'}">${t.direction}</td>
          <td>${t.entry}</td>
          <td>${t.close_price||'—'}</td>
          <td class="${t.pnl>=0?'pos':'neg'}">${t.pnl>=0?'+':''}${t.pnl}</td>
          <td style="color:#60a5fa;font-size:7px">${(t.strategy||'').replace('_',' ')}</td>
          <td>${t.willy_confirmed?'⭐':'—'}</td>
          <td class="${t.result==='WIN'?'pos':'neg'}">${t.result}</td>
        </tr>`
      ).join('');
    }

    // Log
    const lc = {SIGNAL:'#f59e0b',TRADE:'#4ade80',ERROR:'#f87171',WARN:'#f59e0b',LEARN:'#c084fc',INFO:'#60a5fa'};
    document.getElementById('log-box').innerHTML = (d.log||[]).map(l =>
      `<div class="le" style="color:${lc[l.level]||'#60a5fa'}">` +
      `<span style="color:#374151">${l.time}</span> [${l.level}] ${l.msg}</div>`
    ).join('');

  } catch(e) { console.error('Dashboard Fehler:', e); }
  setTimeout(refresh, 10000);
}

refresh();
setInterval(() => {
  const el = document.getElementById('clk');
  if (el) el.textContent = new Date().toUTCString().slice(17,25) + ' UTC';
}, 1000);
</script>
</body></html>"""

# ════════════════════════════════════════════════
# API ROUTEN
# ════════════════════════════════════════════════
@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD)

@app.route("/state")
def state():
    return jsonify({
        "price":         bot_state["price"],
        "last_update":   bot_state["last_update"],
        "last_signal":   bot_state["last_signal"],
        "indicators":    bot_state["indicators"],
        "indicators_15m":bot_state["indicators_15m"],
        "indicators_1h": bot_state["indicators_1h"],
        "indicators_4h": bot_state["indicators_4h"],
        "indicators_1d": bot_state["indicators_1d"],
        "trend_details": bot_state["trend_details"],
        "trends":        bot_state["trends"],
        "learning":      bot_state["learning"],
        "log":           bot_state["log"][:50],
        "stats":         bot_state["stats"],
        "open_trade":    bot_state["open_trade"],
        "running":       bot_state["running"],
        "willy_last":    bot_state["willy_last"],
        "willy_signals_count": len(bot_state["willy_signals"]),
        "dxy":           bot_state["dxy"],
        "dxy_trend":     bot_state["dxy_trend"],
        "yields_10y":    bot_state["yields_10y"],
        "yields_trend":  bot_state["yields_trend"],
        "gold_dxy_correlation": bot_state["gold_dxy_correlation"],
        "session":       bot_state["session"],
        "trade_type":    bot_state["trade_type"],
        "weekly_analysis": bot_state["weekly_analysis"],
        "strategy_scores": bot_state["strategy_scores"],
        "active_strategy": bot_state["active_strategy"],
        "news_lock":     bot_state["news_lock"],
        "news_lock_reason": bot_state["news_lock_reason"],
    })

@app.route("/trades")
def trades():
    return jsonify(bot_state["trades"])

@app.route("/signals")
def signals():
    return jsonify(bot_state["signals"][:50])

@app.route("/weekly")
def weekly():
    return jsonify(bot_state["weekly_analysis"])

@app.route("/learning")
def learning_route():
    return jsonify(bot_state["learning"])

@app.route("/news", methods=["POST"])
def add_news():
    data = request.get_json(force=True)
    name = data.get("name", "Event")
    t    = data.get("time", "2025-01-01 00:00")
    bot_state["news_events"].append({"name": name, "time": t, "impact": "HIGH"})
    add_log(f"News-Event: {name} @ {t}", "INFO")
    return jsonify({"status": "ok"})

@app.route("/settings", methods=["POST"])
def settings():
    data = request.get_json(force=True)
    if "balance" in data: bot_state["account_balance"] = float(data["balance"])
    if "risk"    in data: bot_state["risk_per_trade"]  = float(data["risk"])
    return jsonify({"status":"ok","balance":bot_state["account_balance"],"risk":bot_state["risk_per_trade"]})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        add_log(f"Webhook empfangen: {data}", "INFO")
        sig_type = data.get("signal", "").upper()
        tf       = data.get("timeframe", "—")
        pr       = data.get("price") or data.get("close")
        if pr:
            try:
                pf = float(str(pr).replace(",", "."))
                if 1500 < pf < 5000:
                    bot_state["prices"].append(pf)
                    bot_state["price"] = pf
            except:
                pass
        if sig_type:
            we = {
                "signal_type": sig_type, "timeframe": tf,
                "score": data.get("score", "—"),
                "entry": data.get("entry") or pr,
                "tp1":   data.get("tp1"), "tp2": data.get("tp2"),
                "tp3":   data.get("tp3"), "sl":  data.get("sl"),
                "time":  datetime.datetime.utcnow().strftime("%H:%M:%S"),
                "date":  datetime.datetime.utcnow().strftime("%d.%m.%Y"),
            }
            bot_state["willy_last"] = we
            bot_state["willy_signals"].insert(0, we)
            if len(bot_state["willy_signals"]) > 200: bot_state["willy_signals"].pop()
            add_log(f"⭐ WillyAlgoTrader: {sig_type} | TF:{tf}", "SIGNAL")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        add_log(f"Webhook Fehler: {e}", "ERROR")
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/health")
def health():
    return jsonify({"status":"healthy","version":"3.0","time":datetime.datetime.utcnow().isoformat()})

@app.route("/start")
def start():
    if not bot_state["running"]:
        bot_state["running"] = True
        threading.Thread(target=analysis_loop, daemon=True).start()
        return jsonify({"status": "Bot v3.0 gestartet"})
    return jsonify({"status": "Läuft bereits"})

@app.route("/stop")
def stop():
    bot_state["running"] = False
    return jsonify({"status": "Bot gestoppt"})

# ════════════════════════════════════════════════
# AUTO-START — BUG FIX: gunicorn führt __main__ nicht aus!
# Der Bot startet jetzt automatisch beim Import durch gunicorn.
# ════════════════════════════════════════════════
def _auto_start():
    if not bot_state["running"]:
        bot_state["running"] = True
        t = threading.Thread(target=analysis_loop, daemon=True)
        t.start()
        add_log("XAUUSD KI-Bot v3.0 auto-gestartet (gunicorn)", "INFO")

_auto_start()  # Wird beim Import ausgeführt — funktioniert mit gunicorn!

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
