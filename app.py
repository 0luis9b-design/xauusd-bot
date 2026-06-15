from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import datetime, threading, time, math, json, statistics

app = Flask(__name__)
CORS(app)

bot_state = {
    "price": None, "prices": [], "candles": {},
    "signals": [], "last_signal": None, "last_update": None,
    "indicators": {}, "indicators_15m": {}, "indicators_1h": {}, "indicators_4h": {},
    "trends": {"15m": "UNBEKANNT", "1h": "UNBEKANNT", "4h": "UNBEKANNT", "overall": "UNBEKANNT"},
    "running": False, "log": [],
    "trades": [], "open_trade": None,
    "willy_signals": [], "willy_last": None,
    "learning": {
        "total": 0, "wins": 0, "accuracy": 0.0, "cycle": 0,
        "mistakes": [], "rules": [], "avoided_trades": 0,
    },
    "stats": {
        "total_signals": 0, "buy_signals": 0, "sell_signals": 0,
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
        "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "avoided_by_learning": 0,
    },
}

def add_log(msg, level="INFO"):
    entry = {"time": datetime.datetime.utcnow().strftime("%H:%M:%S"), "msg": msg, "level": level}
    bot_state["log"].insert(0, entry)
    if len(bot_state["log"]) > 150: bot_state["log"].pop()
    print(f"[{level}] {msg}")

# ── KERZEN & PREIS ───────────────────────────
def fetch_candles(interval="1h", count=60):
    import urllib.request
    interval_map = {"15m": ("15m","5d"), "1h": ("1h","30d"), "4h": ("1h","60d")}
    yf_interval, yf_range = interval_map.get(interval, ("1h","30d"))
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX?interval={yf_interval}&range={yf_range}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        ohlcv = result["indicators"]["quote"][0]
        candles = []
        for i in range(len(timestamps)):
            try:
                c = {
                    "time": timestamps[i],
                    "open": round(ohlcv["open"][i] or 0, 2),
                    "high": round(ohlcv["high"][i] or 0, 2),
                    "low":  round(ohlcv["low"][i] or 0, 2),
                    "close":round(ohlcv["close"][i] or 0, 2),
                    "volume": int(ohlcv["volume"][i] or 0),
                }
                if 1500 < c["close"] < 5000:
                    candles.append(c)
            except: continue
        return candles[-count:] if len(candles) > count else candles
    except Exception as e:
        add_log(f"Kerzen-Fehler ({interval}): {e}", "WARN")
        return []

def fetch_price():
    import urllib.request
    sources = [
        "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX?interval=1m&range=1d",
        "https://query2.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX?interval=1m&range=1d",
        "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1m&range=1d",
    ]
    for url in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
                price = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
                if 1500 < price < 5000:
                    return price
        except: continue
    if bot_state["prices"]:
        import random
        return round(bot_state["prices"][-1] + random.uniform(-0.3, 0.3), 2)
    return None

# ── INDIKATOREN ──────────────────────────────
def calc_ema(prices, period):
    if len(prices) < period: return None
    k = 2.0/(period+1); ema = prices[0]
    for p in prices[1:]: ema = p*k + ema*(1-k)
    return round(ema, 2)

def calc_rsi(prices, period=14):
    if len(prices) < period+1: return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i]-prices[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains[-period:])/period
    al = sum(losses[-period:])/period
    if al == 0: return 100.0
    return round(100-(100/(1+ag/al)), 2)

def calc_macd(prices):
    if len(prices) < 26: return None, None, None
    e12 = calc_ema(prices, 12); e26 = calc_ema(prices, 26)
    if not e12 or not e26: return None, None, None
    m = round(e12-e26, 2); s = round(m*0.85, 2)
    return m, s, round(m-s, 2)

def calc_bollinger(prices, period=20):
    if len(prices) < period: return None, None, None
    sub = prices[-period:]; mid = sum(sub)/period
    std = math.sqrt(sum((p-mid)**2 for p in sub)/period)
    return round(mid-2*std,2), round(mid,2), round(mid+2*std,2)

def calc_stochastic(prices, period=14):
    if len(prices) < period: return None, None
    sub = prices[-period:]; lo = min(sub); hi = max(sub)
    if hi == lo: return 50.0, 50.0
    k = round(((prices[-1]-lo)/(hi-lo))*100, 2)
    return k, round(k*0.9, 2)

def calc_atr(prices, period=14):
    if len(prices) < period+1: return None
    trs = [abs(prices[i]-prices[i-1]) for i in range(1, len(prices))]
    return round(sum(trs[-period:])/period, 2)

def calc_adx(prices, period=14):
    if len(prices) < period*2: return None
    changes = [abs(prices[i]-prices[i-1]) for i in range(1, len(prices))]
    avg = sum(changes[-period:])/period
    rng = max(prices[-period:])-min(prices[-period:])
    if rng == 0: return 0
    return min(round((avg/rng)*100*2, 1), 100)

def calc_williams_r(prices, period=14):
    if len(prices) < period: return None
    sub = prices[-period:]; hi = max(sub); lo = min(sub)
    if hi == lo: return -50.0
    return round(((hi-prices[-1])/(hi-lo))*-100, 2)

def calc_cci(prices, period=20):
    if len(prices) < period: return None
    sub = prices[-period:]; mean = sum(sub)/period
    md = sum(abs(p-mean) for p in sub)/period
    if md == 0: return 0
    return round((prices[-1]-mean)/(0.015*md), 2)

def calc_momentum(prices, period=10):
    if len(prices) < period: return None
    return round(prices[-1]-prices[-period], 2)

def calc_volume_profile(candles):
    if len(candles) < 10: return None, None, None
    price_vol = {}
    for c in candles:
        mid = round((c["high"]+c["low"])/2, 0)
        price_vol[mid] = price_vol.get(mid, 0) + c["volume"]
    if not price_vol: return None, None, None
    poc = max(price_vol, key=price_vol.get)
    total_vol = sum(price_vol.values())
    vah = poc; val = poc; cum_vol = 0
    for p in sorted(price_vol.keys(), key=lambda x: price_vol[x], reverse=True):
        cum_vol += price_vol[p]
        if cum_vol/total_vol <= 0.70:
            vah = max(vah, p); val = min(val, p)
    return round(poc,2), round(vah,2), round(val,2)

def calculate_indicators(prices):
    if len(prices) < 30: return {}
    p = prices
    m, ms, mh = calc_macd(p)
    bbl, bbm, bbu = calc_bollinger(p)
    sk, sd = calc_stochastic(p)
    return {
        "price": p[-1],
        "ema20": calc_ema(p,20), "ema50": calc_ema(p,50), "ema200": calc_ema(p,200),
        "rsi": calc_rsi(p), "macd": m, "macd_signal": ms, "macd_hist": mh,
        "bb_lower": bbl, "bb_mid": bbm, "bb_upper": bbu,
        "stoch_k": sk, "stoch_d": sd,
        "atr": calc_atr(p), "adx": calc_adx(p),
        "williams_r": calc_williams_r(p), "cci": calc_cci(p),
        "vwap": round(sum(p[-20:])/len(p[-20:]), 2),
        "momentum": calc_momentum(p),
    }

# ── TREND-ANALYSE ────────────────────────────
def analyze_trend(candles, tf_name):
    if len(candles) < 20: return "UNBEKANNT", {}
    closes = [c["close"] for c in candles]
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, min(50, len(closes)))
    rsi = calc_rsi(closes)
    price = closes[-1]
    hh = all(candles[i]["high"] >= candles[i-1]["high"] for i in range(-3,0))
    hl = all(candles[i]["low"]  >= candles[i-1]["low"]  for i in range(-3,0))
    lh = all(candles[i]["high"] <= candles[i-1]["high"] for i in range(-3,0))
    ll = all(candles[i]["low"]  <= candles[i-1]["low"]  for i in range(-3,0))
    poc, vah, val = calc_volume_profile(candles)
    bull = 0; bear = 0
    if ema20 and price > ema20: bull += 1
    else: bear += 1
    if ema50 and price > ema50: bull += 1
    else: bear += 1
    if ema20 and ema50 and ema20 > ema50: bull += 1
    else: bear += 1
    if hh and hl: bull += 2
    if lh and ll: bear += 2
    if rsi and rsi > 50: bull += 1
    elif rsi and rsi < 50: bear += 1
    if bull >= 4: trend = "BULLISH ▲"
    elif bear >= 4: trend = "BEARISH ▼"
    elif bull > bear: trend = "LEICHT BULLISH"
    elif bear > bull: trend = "LEICHT BEARISH"
    else: trend = "SEITWÄRTS ↔"
    return trend, {"ema20": ema20, "ema50": ema50, "rsi": rsi, "poc": poc, "vah": vah, "val": val, "bull": bull, "bear": bear}

# ── LERNMODUL ────────────────────────────────
def analyze_failed_trade(trade, inds):
    mistakes = []
    if not inds: return mistakes
    direction = trade.get("direction")
    rsi = inds.get("rsi"); adx = inds.get("adx")
    macd = inds.get("macd"); ms = inds.get("macd_signal")
    trend_4h = bot_state["trends"].get("4h","")
    if direction == "BUY":
        if rsi and rsi > 60: mistakes.append({"rule":"BUY_HIGH_RSI","desc":f"BUY bei RSI={rsi} (überkauft)","avoid":"Kein BUY wenn RSI > 60"})
        if adx and adx < 20: mistakes.append({"rule":"BUY_WEAK_TREND","desc":f"BUY bei ADX={adx} (Trend zu schwach)","avoid":"Kein BUY wenn ADX < 20"})
        if "BEARISH" in trend_4h: mistakes.append({"rule":"BUY_AGAINST_TREND","desc":"BUY gegen 4H Bearish-Trend","avoid":"Kein BUY wenn 4H = BEARISH"})
        if macd and ms and macd < ms: mistakes.append({"rule":"BUY_BEARISH_MACD","desc":"BUY bei Bearish MACD","avoid":"Kein BUY wenn MACD < Signal"})
    elif direction == "SELL":
        if rsi and rsi < 40: mistakes.append({"rule":"SELL_LOW_RSI","desc":f"SELL bei RSI={rsi} (überverkauft)","avoid":"Kein SELL wenn RSI < 40"})
        if adx and adx < 20: mistakes.append({"rule":"SELL_WEAK_TREND","desc":f"SELL bei ADX={adx} (Trend zu schwach)","avoid":"Kein SELL wenn ADX < 20"})
        if "BULLISH" in trend_4h: mistakes.append({"rule":"SELL_AGAINST_TREND","desc":"SELL gegen 4H Bullish-Trend","avoid":"Kein SELL wenn 4H = BULLISH"})
    return mistakes

def update_learning_rules(mistakes):
    rules = bot_state["learning"]["rules"]
    for m in mistakes:
        existing = next((r for r in rules if r["rule"] == m["rule"]), None)
        if existing:
            existing["count"] += 1
            existing["last_seen"] = datetime.datetime.utcnow().strftime("%d.%m %H:%M")
        else:
            rules.insert(0, {"rule":m["rule"],"desc":m["desc"],"avoid":m["avoid"],"count":1,"last_seen":datetime.datetime.utcnow().strftime("%d.%m %H:%M")})
    if len(rules) > 20: rules.pop()
    add_log(f"Lernmodul: {len(mistakes)} Regeln aktualisiert", "LEARN")

def check_learning_rules(signal, inds):
    violated = []
    rules = bot_state["learning"]["rules"]
    rsi = inds.get("rsi"); adx = inds.get("adx")
    macd = inds.get("macd"); ms = inds.get("macd_signal")
    trend_4h = bot_state["trends"].get("4h","")
    for rule in rules:
        if rule["count"] < 2: continue
        r = rule["rule"]
        if r=="BUY_HIGH_RSI" and signal=="BUY" and rsi and rsi>60: violated.append(rule["avoid"])
        elif r=="BUY_WEAK_TREND" and signal=="BUY" and adx and adx<20: violated.append(rule["avoid"])
        elif r=="BUY_AGAINST_TREND" and signal=="BUY" and "BEARISH" in trend_4h: violated.append(rule["avoid"])
        elif r=="BUY_BEARISH_MACD" and signal=="BUY" and macd and ms and macd<ms: violated.append(rule["avoid"])
        elif r=="SELL_LOW_RSI" and signal=="SELL" and rsi and rsi<40: violated.append(rule["avoid"])
        elif r=="SELL_WEAK_TREND" and signal=="SELL" and adx and adx<20: violated.append(rule["avoid"])
        elif r=="SELL_AGAINST_TREND" and signal=="SELL" and "BULLISH" in trend_4h: violated.append(rule["avoid"])
    return violated

# ── SIGNAL ENGINE ────────────────────────────
def evaluate_signal(inds):
    if not inds or not inds.get("price"): return "WARTEN", 0, [], []
    price=inds["price"]; bull=[]; bear=[]
    e20=inds.get("ema20"); e50=inds.get("ema50"); e200=inds.get("ema200")
    rsi=inds.get("rsi"); macd=inds.get("macd"); ms=inds.get("macd_signal")
    bbl=inds.get("bb_lower"); bbu=inds.get("bb_upper")
    sk=inds.get("stoch_k"); wr=inds.get("williams_r")
    cci=inds.get("cci"); vwap=inds.get("vwap")
    mom=inds.get("momentum"); adx=inds.get("adx")
    if adx and adx < 20: return "WARTEN", 0, [], []
    if e20 and e50:
        if price>e20>e50: bull.append(f"EMA20({e20})>EMA50({e50}) Bullish Stack")
        elif price<e20<e50: bear.append(f"EMA20({e20})<EMA50({e50}) Bearish Stack")
    if e200:
        if price>e200: bull.append(f"Preis über EMA200({e200})")
        else: bear.append(f"Preis unter EMA200({e200})")
    if rsi is not None:
        if rsi<35: bull.append(f"RSI={rsi} Überverkauft")
        elif rsi>65: bear.append(f"RSI={rsi} Überkauft")
        elif 40<rsi<60: bull.append(f"RSI={rsi} Neutral-Bullish")
    if macd and ms:
        if macd>ms: bull.append(f"MACD Bullish ({macd})")
        else: bear.append(f"MACD Bearish ({macd})")
    if bbl and bbu:
        if price<bbl: bull.append("Unter BB-Unterkante Oversold")
        elif price>bbu: bear.append("Über BB-Oberkante Overbought")
    if sk is not None:
        if sk<25: bull.append(f"Stochastic K={sk} Überverkauft")
        elif sk>75: bear.append(f"Stochastic K={sk} Überkauft")
    if wr is not None:
        if wr<-80: bull.append(f"Williams %R={wr} Überverkauft")
        elif wr>-20: bear.append(f"Williams %R={wr} Überkauft")
    if cci is not None:
        if cci<-100: bull.append(f"CCI={cci} Überverkauft")
        elif cci>100: bear.append(f"CCI={cci} Überkauft")
    if vwap:
        if price>vwap: bull.append(f"Preis über VWAP({vwap})")
        else: bear.append(f"Preis unter VWAP({vwap})")
    if mom is not None:
        if mom>0: bull.append(f"Momentum={mom:+.1f} Positiv")
        else: bear.append(f"Momentum={mom:+.1f} Negativ")
    t15=bot_state["trends"].get("15m",""); t1h=bot_state["trends"].get("1h",""); t4h=bot_state["trends"].get("4h","")
    tf_bull = sum(1 for t in [t15,t1h,t4h] if "BULLISH" in t)
    tf_bear = sum(1 for t in [t15,t1h,t4h] if "BEARISH" in t)
    if tf_bull >= 2: bull.append(f"Multi-TF: {tf_bull}/3 Timeframes Bullish")
    if tf_bear >= 2: bear.append(f"Multi-TF: {tf_bear}/3 Timeframes Bearish")
    willy = bot_state.get("willy_last")
    if willy:
        wt = willy.get("signal_type","")
        if "BUY" in wt: bull.append(f"⭐ WillyAlgoTrader: {wt} ({willy.get('timeframe','')})")
        elif "SELL" in wt: bear.append(f"⭐ WillyAlgoTrader: {wt} ({willy.get('timeframe','')})")
    total = len(bull)+len(bear)
    if total == 0: return "WARTEN", 0, [], []
    bp = len(bull)/total*100; sp = len(bear)/total*100
    if bp>=65 and len(bull)>=6: return "BUY", round(bp,1), bull, bear
    elif sp>=65 and len(bear)>=6: return "SELL", round(sp,1), bear, bull
    return "WARTEN", round(max(bp,sp),1), bull, bear

# ── TRADE TRACKING ───────────────────────────
def open_trade(signal, price, sl, tp1, tp2, inds_snapshot):
    bot_state["open_trade"] = {
        "direction":signal,"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,
        "open_time":datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "status":"OPEN","inds_at_entry":inds_snapshot,
        "willy_confirmed":bot_state["willy_last"] is not None,
    }
    add_log(f"Trade geöffnet: {signal} @ {price} SL:{sl} TP1:{tp1} TP2:{tp2}", "TRADE")

def check_trade(price):
    t = bot_state["open_trade"]
    if not t: return
    result=None; pnl=0
    if t["direction"]=="BUY":
        if price<=t["sl"]: result="LOSS"; pnl=round(t["sl"]-t["entry"],2)
        elif price>=t["tp2"]: result="WIN"; pnl=round(t["tp2"]-t["entry"],2)
        elif price>=t["tp1"]: result="WIN"; pnl=round(t["tp1"]-t["entry"],2)
    elif t["direction"]=="SELL":
        if price>=t["sl"]: result="LOSS"; pnl=round(t["entry"]-t["sl"],2)
        elif price<=t["tp2"]: result="WIN"; pnl=round(t["entry"]-t["tp2"],2)
        elif price<=t["tp1"]: result="WIN"; pnl=round(t["entry"]-t["tp1"],2)
    if result:
        t["close_price"]=price; t["pnl"]=pnl; t["result"]=result
        t["close_time"]=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"); t["status"]="CLOSED"
        bot_state["trades"].insert(0,{k:v for k,v in t.items() if k!="inds_at_entry"})
        if len(bot_state["trades"])>200: bot_state["trades"].pop()
        if result=="LOSS":
            mistakes = analyze_failed_trade(t, t.get("inds_at_entry",{}))
            if mistakes:
                bot_state["learning"]["mistakes"].insert(0,{"time":datetime.datetime.utcnow().strftime("%d.%m %H:%M"),"trade":f"{t['direction']} @ {t['entry']}","mistakes":mistakes})
                if len(bot_state["learning"]["mistakes"])>30: bot_state["learning"]["mistakes"].pop()
                update_learning_rules(mistakes)
        bot_state["open_trade"]=None
        s=bot_state["stats"]; s["total_trades"]+=1; s["total_pnl"]=round(s["total_pnl"]+pnl,2)
        if result=="WIN":
            s["winning_trades"]+=1; s["best_trade"]=round(max(s["best_trade"],pnl),2)
            wins=[x["pnl"] for x in bot_state["trades"] if x["result"]=="WIN"]
            s["avg_win"]=round(sum(wins)/len(wins),2) if wins else 0
        else:
            s["losing_trades"]+=1; s["worst_trade"]=round(min(s["worst_trade"],pnl),2)
            losses=[x["pnl"] for x in bot_state["trades"] if x["result"]=="LOSS"]
            s["avg_loss"]=round(sum(losses)/len(losses),2) if losses else 0
        s["win_rate"]=round(s["winning_trades"]/s["total_trades"]*100,1)
        add_log(f"Trade geschlossen: {result} P&L:{pnl:+.2f} Pkt", "TRADE")

# ── ANALYSE LOOP ─────────────────────────────
def analysis_loop():
    add_log("KI-Analyse-Engine v2.2 gestartet ✓", "INFO")
    cycle=0; candle_refresh=0
    while bot_state["running"]:
        try:
            cycle+=1; bot_state["learning"]["cycle"]=cycle; candle_refresh+=1
            if candle_refresh >= 3 or cycle == 1:
                candle_refresh=0
                for tf in ["15m","1h","4h"]:
                    candles = fetch_candles(tf, 60)
                    if candles:
                        bot_state["candles"][tf]=candles
                        trend, details = analyze_trend(candles, tf)
                        bot_state["trends"][tf]=trend
                        closes=[c["close"] for c in candles]
                        bot_state[f"indicators_{tf}"]=calculate_indicators(closes)
                        add_log(f"TF {tf}: {trend}", "INFO")
                trends=[bot_state["trends"].get(t,"") for t in ["15m","1h","4h"]]
                bc=sum(1 for t in trends if "BULLISH" in t)
                sc=sum(1 for t in trends if "BEARISH" in t)
                bot_state["trends"]["overall"]="BULLISH ▲" if bc>=2 else "BEARISH ▼" if sc>=2 else "MIXED ↔"

            price = fetch_price()
            if price:
                bot_state["price"]=price
                bot_state["prices"].append(price)
                if len(bot_state["prices"])>200: bot_state["prices"].pop(0)
                bot_state["last_update"]=datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
                check_trade(price)
                if len(bot_state["prices"])>=30:
                    inds=calculate_indicators(bot_state["prices"])
                    bot_state["indicators"]=inds
                    sig,conf,reasons,counter=evaluate_signal(inds)
                    bot_state["stats"]["total_signals"]+=1
                    if sig=="BUY": bot_state["stats"]["buy_signals"]+=1
                    elif sig=="SELL": bot_state["stats"]["sell_signals"]+=1
                    if sig in ["BUY","SELL"]:
                        violations=check_learning_rules(sig,inds)
                        if violations:
                            bot_state["stats"]["avoided_by_learning"]+=1
                            bot_state["learning"]["avoided_trades"]+=1
                            add_log(f"Signal {sig} ABGELEHNT: {violations[0]}", "LEARN")
                            sig="WARTEN"; conf=0
                    atr=inds.get("atr",15)
                    entry={
                        "time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                        "date":datetime.datetime.utcnow().strftime("%d.%m.%Y"),
                        "signal":sig,"confidence":conf,"price":price,
                        "reasons":reasons,"counter_reasons":counter,"atr":atr,
                        "sl":round(price-1.5*atr,2) if sig=="BUY" else round(price+1.5*atr,2) if sig=="SELL" else None,
                        "tp1":round(price+1.5*atr,2) if sig=="BUY" else round(price-1.5*atr,2) if sig=="SELL" else None,
                        "tp2":round(price+3.0*atr,2) if sig=="BUY" else round(price-3.0*atr,2) if sig=="SELL" else None,
                        "willy_confirmed":bot_state["willy_last"] is not None,
                        "trend_15m":bot_state["trends"].get("15m",""),
                        "trend_1h":bot_state["trends"].get("1h",""),
                        "trend_4h":bot_state["trends"].get("4h",""),
                    }
                    bot_state["last_signal"]=entry
                    bot_state["signals"].insert(0,entry)
                    if len(bot_state["signals"])>200: bot_state["signals"].pop()
                    if sig!="WARTEN" and not bot_state["open_trade"]:
                        open_trade(sig,price,entry["sl"],entry["tp1"],entry["tp2"],dict(inds))
                    bot_state["learning"]["total"]+=1
                    if sig in ["BUY","SELL"]: bot_state["learning"]["wins"]+=1
                    t2=bot_state["learning"]["total"]
                    bot_state["learning"]["accuracy"]=round(bot_state["learning"]["wins"]/t2*100,1) if t2>0 else 0
                    lvl="SIGNAL" if sig!="WARTEN" else "INFO"
                    add_log(f"{sig} | Konfidenz:{conf}% | Preis:{price} | Trend:{bot_state['trends']['overall']}", lvl)
                else:
                    add_log(f"Preis:{price} | Sammle Daten ({len(bot_state['prices'])}/30)", "INFO")
        except Exception as e:
            add_log(f"Loop-Fehler: {str(e)}", "ERROR")
        time.sleep(300)

# ── DASHBOARD ────────────────────────────────
DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD KI-Bot v2.2</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0e1a;color:#e0e6f0;font-family:'Courier New',monospace;padding:12px}
.hdr{background:#111827;border:1px solid #1e3a5f;border-radius:8px;padding:10px 14px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.logo{font-size:15px;font-weight:700;color:#f59e0b;letter-spacing:2px}
.sub{font-size:9px;color:#6b7280;letter-spacing:1px}
.badges{display:flex;gap:5px;flex-wrap:wrap}
.b{padding:2px 8px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:1px}
.bg{background:#052e16;color:#4ade80;border:1px solid #166534}
.bb{background:#0c1a3a;color:#60a5fa;border:1px solid #1e3a5f}
.ba{background:#1c1000;color:#f59e0b;border:1px solid #78350f}
.br{background:#1c0a0a;color:#f87171;border:1px solid #7f1d1d}
.bp{background:#1a0a2e;color:#c084fc;border:1px solid #6b21a8}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.pn{background:#111827;border:1px solid #1e2d45;border-radius:8px;padding:12px}
.pt{font-size:9px;color:#6b7280;letter-spacing:2px;margin-bottom:8px;display:flex;align-items:center;gap:5px}
.dot{width:6px;height:6px;border-radius:50%}
.dg{background:#4ade80;box-shadow:0 0 5px #4ade80}.da{background:#f59e0b;box-shadow:0 0 5px #f59e0b}
.db{background:#60a5fa;box-shadow:0 0 5px #60a5fa}.dp{background:#c084fc;box-shadow:0 0 5px #c084fc}
.big{font-size:22px;font-weight:700;letter-spacing:2px}
.pos{color:#4ade80}.neg{color:#f87171}.neu{color:#94a3b8}.amr{color:#f59e0b}.pur{color:#c084fc}
.sm{text-align:center}.sv{font-size:16px;font-weight:700}.sl2{font-size:8px;color:#6b7280;letter-spacing:1px;margin-top:2px}
.ir{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #1a2236;font-size:10px}
.ir:last-child{border-bottom:none}.in{color:#6b7280}
.pb{background:#1e2d45;border-radius:4px;height:5px;margin:3px 0;overflow:hidden}
.pf{height:100%;border-radius:4px;transition:width .5s}
.fg{background:linear-gradient(90deg,#166534,#4ade80)}
.le{font-size:9px;padding:2px 0;border-bottom:1px solid #1a2236;line-height:1.5}
.pulse{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.blink{animation:blink 1s infinite}@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
table{width:100%;border-collapse:collapse;font-size:9px}
th{color:#6b7280;font-weight:700;padding:3px 5px;border-bottom:1px solid #1e2d45;text-align:left;letter-spacing:1px}
td{padding:3px 5px;border-bottom:1px solid #1a2236}
.sbox{padding:10px;border-radius:6px;border:1px solid;margin-bottom:4px}
.sbuy{background:#052e16;border-color:#166534}.ssell{background:#1c0a0a;border-color:#7f1d1d}.swait{background:#1c1000;border-color:#78350f}
.tb{color:#4ade80;font-weight:700}.ts{color:#f87171;font-weight:700}.tn{color:#94a3b8;font-weight:700}
</style>
</head>
<body>
<div class="hdr">
  <div><div class="logo">⚡ XAUUSD KI-BOT v2.2</div><div class="sub">LERNMODUL · MULTI-TIMEFRAME · VOLUMEN-PROFIL · WILLYALGOTRADER</div></div>
  <div class="badges">
    <span class="b bg"><span class="blink">●</span> LIVE</span>
    <span class="b bb" id="clk">--:--:--</span>
    <span class="b ba" id="last-upd">Warte...</span>
    <span class="b bp" id="willy-status">WILLY: —</span>
  </div>
</div>

<div class="g4">
  <div class="pn"><div class="pt"><span class="dot da"></span>XAUUSD PREIS</div>
    <div class="big amr" id="price">—</div>
    <div style="font-size:10px;margin-top:4px;color:#6b7280">ATR: <span id="atr" class="amr">—</span> &nbsp; ADX: <span id="adx" class="amr">—</span></div>
    <div style="font-size:10px;margin-top:3px" id="overall-trend">Trend: —</div>
  </div>
  <div class="pn"><div class="pt"><span class="dot dg pulse"></span>SIGNAL</div>
    <div id="sig-box" class="sbox swait">
      <div style="font-size:13px;font-weight:700;letter-spacing:2px" id="sig-t">WARTEN</div>
      <div style="font-size:9px;color:#94a3b8;margin-top:3px" id="sig-c">Warte auf Konvergenz...</div>
      <div style="font-size:9px;margin-top:3px" id="sig-levels"></div>
    </div>
  </div>
  <div class="pn"><div class="pt"><span class="dot db"></span>WIN RATE</div>
    <div class="big pos" id="winrate">—</div>
    <div class="pb"><div class="pf fg" id="wr-bar" style="width:0%"></div></div>
    <div style="font-size:9px;color:#6b7280;margin-top:3px"><span id="wins">0</span>W / <span id="losses">0</span>L / <span id="total-t">0</span> Trades</div>
    <div style="font-size:9px;margin-top:3px;color:#c084fc">Lernregel-Vermeidungen: <span id="avoided">0</span></div>
  </div>
  <div class="pn"><div class="pt"><span class="dot dg"></span>GESAMT P&L</div>
    <div class="big" id="total-pnl">+0.00 Pkt</div>
    <div style="font-size:9px;margin-top:3px;color:#6b7280">Best: <span id="best" class="pos">—</span> &nbsp; Worst: <span id="worst" class="neg">—</span></div>
    <div style="font-size:9px;margin-top:2px;color:#6b7280">Ø Win: <span id="avg-win" class="pos">—</span> &nbsp; Ø Loss: <span id="avg-loss" class="neg">—</span></div>
  </div>
</div>

<!-- TREND PANEL -->
<div class="pn" style="margin-bottom:10px">
  <div class="pt"><span class="dot da pulse"></span>MULTI-TIMEFRAME TREND — 15MIN · 1H · 4H</div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
    <div class="sm">
      <div style="font-size:10px;color:#6b7280;margin-bottom:5px;letter-spacing:1px">15 MIN</div>
      <div class="sv" id="trend-15m">—</div>
      <div style="font-size:9px;color:#6b7280;margin-top:5px">EMA20: <span id="t15-e20">—</span></div>
      <div style="font-size:9px;color:#6b7280">RSI: <span id="t15-rsi">—</span></div>
      <div style="font-size:9px;color:#6b7280">Vol.POC: <span id="t15-poc" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:10px;color:#6b7280;margin-bottom:5px;letter-spacing:1px">1 STUNDE</div>
      <div class="sv" id="trend-1h">—</div>
      <div style="font-size:9px;color:#6b7280;margin-top:5px">EMA20: <span id="t1h-e20">—</span></div>
      <div style="font-size:9px;color:#6b7280">RSI: <span id="t1h-rsi">—</span></div>
      <div style="font-size:9px;color:#6b7280">Vol.POC: <span id="t1h-poc" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:10px;color:#6b7280;margin-bottom:5px;letter-spacing:1px">4 STUNDEN</div>
      <div class="sv" id="trend-4h">—</div>
      <div style="font-size:9px;color:#6b7280;margin-top:5px">EMA20: <span id="t4h-e20">—</span></div>
      <div style="font-size:9px;color:#6b7280">RSI: <span id="t4h-rsi">—</span></div>
      <div style="font-size:9px;color:#6b7280">Vol.POC: <span id="t4h-poc" class="amr">—</span></div>
    </div>
    <div class="sm">
      <div style="font-size:10px;color:#6b7280;margin-bottom:5px;letter-spacing:1px">GESAMTTREND</div>
      <div class="sv" id="trend-overall">—</div>
      <div style="font-size:9px;color:#6b7280;margin-top:5px">15m: <span id="tf-15m-s">—</span></div>
      <div style="font-size:9px;color:#6b7280">1h: <span id="tf-1h-s">—</span></div>
      <div style="font-size:9px;color:#6b7280">4h: <span id="tf-4h-s">—</span></div>
    </div>
  </div>
</div>

<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>INDIKATOREN — LIVE</div>
    <div class="ir"><span class="in">EMA 20 / 50 / 200</span><span id="emas" class="neu">—</span></div>
    <div class="ir"><span class="in">RSI (14)</span><span id="rsi" class="neu">—</span></div>
    <div class="ir"><span class="in">MACD / Signal</span><span id="macd" class="neu">—</span></div>
    <div class="ir"><span class="in">BB Oben / Mitte / Unten</span><span id="bb" class="neu">—</span></div>
    <div class="ir"><span class="in">Stochastic K</span><span id="stoch" class="neu">—</span></div>
    <div class="ir"><span class="in">Williams %R</span><span id="wr2" class="neu">—</span></div>
    <div class="ir"><span class="in">CCI (20)</span><span id="cci" class="neu">—</span></div>
    <div class="ir"><span class="in">VWAP</span><span id="vwap" class="neu">—</span></div>
    <div class="ir"><span class="in">Momentum</span><span id="mom" class="neu">—</span></div>
    <div class="ir"><span class="in">ATR / ADX</span><span id="atr-adx" class="neu">—</span></div>
    <div style="border-top:1px solid #1e2d45;margin-top:8px;padding-top:8px">
      <div class="pt"><span class="dot db"></span>OFFENER TRADE</div>
      <div id="open-trade" style="font-size:10px;color:#94a3b8">Kein offener Trade</div>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>SIGNAL-BEGRÜNDUNG</div>
    <div style="font-size:9px;color:#4ade80;margin-bottom:3px">✅ BULLISH SIGNALE</div>
    <div id="bull-reasons" style="font-size:9px;color:#4ade80;line-height:1.8;min-height:50px">Warte...</div>
    <div style="font-size:9px;color:#f87171;margin:6px 0 3px">❌ BEARISH SIGNALE</div>
    <div id="bear-reasons" style="font-size:9px;color:#f87171;line-height:1.8;min-height:50px">Warte...</div>
  </div>
</div>

<!-- WillyAlgoTrader -->
<div class="pn" style="margin-bottom:10px">
  <div class="pt"><span class="dot dp pulse"></span>WILLYALGOTRADER — EXTERNE SIGNALE</div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px">
    <div class="sm"><div class="sv pur" id="w-signal">—</div><div class="sl2">SIGNAL</div></div>
    <div class="sm"><div class="sv neu" id="w-tf">—</div><div class="sl2">TIMEFRAME</div></div>
    <div class="sm"><div class="sv neu" id="w-score">—</div><div class="sl2">SCORE</div></div>
    <div class="sm"><div class="sv neu" id="w-time">—</div><div class="sl2">ZEIT</div></div>
    <div class="sm"><div class="sv amr" id="w-count">0</div><div class="sl2">TOTAL SIGNALS</div></div>
  </div>
  <div style="font-size:9px;color:#6b7280;margin-top:6px" id="w-tps">Entry: — | TP1: — | TP2: — | TP3: —</div>
</div>

<!-- Lernmodul -->
<div class="pn" style="margin-bottom:10px">
  <div class="pt"><span class="dot dp"></span>LERNMODUL — BOT LERNT AUS FEHLERN</div>
  <div class="g2" style="margin-bottom:0">
    <div>
      <div style="font-size:9px;color:#6b7280;margin-bottom:5px;letter-spacing:1px">⚡ AKTIVE LERNREGELN (ab 2x Fehler)</div>
      <div id="learn-rules" style="font-size:9px;line-height:1.9;color:#c084fc">Noch keine Regeln gelernt...</div>
    </div>
    <div>
      <div style="font-size:9px;color:#6b7280;margin-bottom:5px;letter-spacing:1px">🔍 LETZTE FEHLER-ANALYSEN</div>
      <div id="learn-mistakes" style="font-size:9px;line-height:1.9;color:#f87171">Noch keine Fehler analysiert...</div>
    </div>
  </div>
</div>

<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>TRADE HISTORIE & P&L</div>
    <div style="overflow-y:auto;max-height:180px">
    <table>
      <thead><tr><th>ZEIT</th><th>DIR</th><th>ENTRY</th><th>CLOSE</th><th>P&L</th><th>⭐</th><th>RESULT</th></tr></thead>
      <tbody id="trades-body"><tr><td colspan="7" style="color:#6b7280;text-align:center;padding:8px">Noch keine Trades</td></tr></tbody>
    </table>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db pulse"></span>BOT LOG — ECHTZEIT</div>
    <div id="log-box" style="max-height:220px;overflow-y:auto"></div>
  </div>
</div>

<script>
function fmt(v){return(v===null||v===undefined)?'—':v}
function tc(t){return t&&t.includes('BULLISH')?'tb':t&&t.includes('BEARISH')?'ts':'tn'}

async function refresh(){
  try{
    const [sr,tr]=await Promise.all([fetch('/state'),fetch('/trades')]);
    const d=await sr.json(); const trades=await tr.json();
    const i=d.indicators||{}; const s=d.stats||{};
    const sig=d.last_signal||{}; const w=d.willy_last||null;
    const trends=d.trends||{}; const learn=d.learning||{};
    const t15d=d.indicators_15m||{}; const t1hd=d.indicators_1h||{}; const t4hd=d.indicators_4h||{};

    document.getElementById('clk').textContent=new Date().toUTCString().slice(17,25)+' UTC';
    document.getElementById('last-upd').textContent=d.last_update||'Warte...';

    const p=d.price;
    if(p) document.getElementById('price').textContent=p.toFixed(2);
    document.getElementById('atr').textContent=fmt(i.atr);
    document.getElementById('adx').textContent=fmt(i.adx);
    document.getElementById('atr-adx').textContent=`${fmt(i.atr)} / ${fmt(i.adx)}`;

    const ov=trends.overall||'—';
    const otEl=document.getElementById('overall-trend');
    otEl.textContent='Trend: '+ov; otEl.className=tc(ov);

    const st=sig.signal||'WARTEN';
    document.getElementById('sig-box').className='sbox '+(st==='BUY'?'sbuy':st==='SELL'?'ssell':'swait');
    document.getElementById('sig-t').textContent=st+(sig.willy_confirmed?' ⭐':'');
    document.getElementById('sig-t').style.color=st==='BUY'?'#4ade80':st==='SELL'?'#f87171':'#f59e0b';
    document.getElementById('sig-c').textContent=sig.confidence?`Konfidenz: ${sig.confidence}% | Preis: ${sig.price}`:'Warte auf Konvergenz...';
    document.getElementById('sig-levels').innerHTML=sig.sl?`<span style="color:#f87171">SL:${sig.sl}</span> <span style="color:#4ade80">TP1:${sig.tp1} TP2:${sig.tp2}</span>`:'';

    document.getElementById('winrate').textContent=s.win_rate?s.win_rate+'%':'—';
    document.getElementById('winrate').className='big '+(s.win_rate>=50?'pos':'neg');
    document.getElementById('wr-bar').style.width=(s.win_rate||0)+'%';
    document.getElementById('wins').textContent=s.winning_trades||0;
    document.getElementById('losses').textContent=s.losing_trades||0;
    document.getElementById('total-t').textContent=s.total_trades||0;
    document.getElementById('avoided').textContent=s.avoided_by_learning||0;
    const pnl=s.total_pnl||0;
    const pnlEl=document.getElementById('total-pnl');
    pnlEl.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+' Pkt';
    pnlEl.className='big '+(pnl>=0?'pos':'neg');
    document.getElementById('best').textContent=(s.best_trade||0).toFixed(2);
    document.getElementById('worst').textContent=(s.worst_trade||0).toFixed(2);
    document.getElementById('avg-win').textContent=s.avg_win?'+'+s.avg_win:'—';
    document.getElementById('avg-loss').textContent=s.avg_loss||'—';

    // Trend Panel
    const tfData=[['15m','trend-15m','t15-e20','t15-rsi','t15-poc',t15d,'tf-15m-s'],
                  ['1h','trend-1h','t1h-e20','t1h-rsi','t1h-poc',t1hd,'tf-1h-s'],
                  ['4h','trend-4h','t4h-e20','t4h-rsi','t4h-poc',t4hd,'tf-4h-s']];
    for(const[tf,tid,eid,rid,pid,tdi,sid2] of tfData){
      const tv=trends[tf]||'—';
      const el=document.getElementById(tid); el.textContent=tv; el.className='sv '+tc(tv);
      document.getElementById(eid).textContent=fmt(tdi.ema20);
      document.getElementById(rid).textContent=fmt(tdi.rsi);
      if(document.getElementById(pid)) document.getElementById(pid).textContent=fmt(tdi.poc||'—');
      const sel=document.getElementById(sid2); if(sel){sel.textContent=tv;sel.className=tc(tv);}
    }
    const ovEl=document.getElementById('trend-overall'); ovEl.textContent=ov; ovEl.className='sv '+tc(ov);

    // Indikatoren
    document.getElementById('emas').textContent=`${fmt(i.ema20)} / ${fmt(i.ema50)} / ${fmt(i.ema200)}`;
    document.getElementById('emas').className=i.ema20&&p&&i.ema20<p?'pos':'neg';
    const rsiEl=document.getElementById('rsi'); rsiEl.textContent=fmt(i.rsi);
    rsiEl.className=i.rsi<35?'pos':i.rsi>65?'neg':'neu';
    document.getElementById('macd').textContent=`${fmt(i.macd)} / ${fmt(i.macd_signal)}`;
    document.getElementById('macd').className=i.macd&&i.macd>0?'pos':'neg';
    document.getElementById('bb').textContent=`${fmt(i.bb_upper)} / ${fmt(i.bb_mid)} / ${fmt(i.bb_lower)}`;
    const skEl=document.getElementById('stoch'); skEl.textContent=fmt(i.stoch_k);
    skEl.className=i.stoch_k<25?'pos':i.stoch_k>75?'neg':'neu';
    const wrEl=document.getElementById('wr2'); wrEl.textContent=fmt(i.williams_r);
    wrEl.className=i.williams_r<-80?'pos':i.williams_r>-20?'neg':'neu';
    const cciEl=document.getElementById('cci'); cciEl.textContent=fmt(i.cci);
    cciEl.className=i.cci<-100?'pos':i.cci>100?'neg':'neu';
    const vpEl=document.getElementById('vwap'); vpEl.textContent=fmt(i.vwap);
    vpEl.className=i.vwap&&p&&p>i.vwap?'pos':'neg';
    const momEl=document.getElementById('mom'); momEl.textContent=fmt(i.momentum);
    momEl.className=i.momentum&&i.momentum>0?'pos':'neg';

    const br=sig.reasons||[]; const cr=sig.counter_reasons||[];
    document.getElementById('bull-reasons').innerHTML=br.length?br.map(r=>`✓ ${r}`).join('<br>'):'<span style="color:#374151">—</span>';
    document.getElementById('bear-reasons').innerHTML=cr.length?cr.map(r=>`✗ ${r}`).join('<br>'):'<span style="color:#374151">—</span>';

    const ot=d.open_trade;
    if(ot){
      const upnl=ot.direction==='BUY'?(p||0)-ot.entry:ot.entry-(p||0);
      document.getElementById('open-trade').innerHTML=
        `<span class="${ot.direction==='BUY'?'pos':'neg'}">${ot.direction}</span> @ ${ot.entry} | SL:${ot.sl} | TP1:${ot.tp1} | TP2:${ot.tp2}<br>
         Unrealisiert: <span class="${upnl>=0?'pos':'neg'}">${upnl>=0?'+':''}${upnl.toFixed(2)} Pkt</span>`;
    } else document.getElementById('open-trade').textContent='Kein offener Trade';

    if(w){
      const wdir=w.signal_type||'—';
      const wsEl=document.getElementById('w-signal'); wsEl.textContent=wdir;
      wsEl.className='sv '+(wdir.includes('BUY')?'pos':wdir.includes('SELL')?'neg':'pur');
      document.getElementById('w-tf').textContent=w.timeframe||'—';
      document.getElementById('w-score').textContent=w.score||'—';
      document.getElementById('w-time').textContent=w.time||'—';
      document.getElementById('willy-status').textContent='WILLY: '+wdir;
      document.getElementById('willy-status').className='b '+(wdir.includes('BUY')?'bg':wdir.includes('SELL')?'br':'bp');
      document.getElementById('w-tps').textContent=`Entry:${w.entry||'—'} | TP1:${w.tp1||'—'} | TP2:${w.tp2||'—'} | TP3:${w.tp3||'—'}`;
    }
    document.getElementById('w-count').textContent=d.willy_signals_count||0;

    const rules=learn.rules||[];
    document.getElementById('learn-rules').innerHTML=rules.length?
      rules.slice(0,6).map(r=>`⚡ [${r.count}x] ${r.avoid}`).join('<br>'):
      'Noch keine Regeln gelernt...';
    const mist=learn.mistakes||[];
    document.getElementById('learn-mistakes').innerHTML=mist.length?
      mist.slice(0,4).map(m=>`📍 ${m.time} — ${m.trade}<br>${m.mistakes.map(x=>`&nbsp;&nbsp;→ ${x.desc}`).join('<br>')}`).join('<br>'):
      'Noch keine Fehler analysiert...';

    const tbody=document.getElementById('trades-body');
    if(trades.length){
      tbody.innerHTML=trades.slice(0,15).map(t=>
        `<tr><td>${(t.close_time||'').slice(11,16)}</td>
        <td class="${t.direction==='BUY'?'pos':'neg'}">${t.direction}</td>
        <td>${t.entry}</td><td>${t.close_price||'—'}</td>
        <td class="${t.pnl>=0?'pos':'neg'}">${t.pnl>=0?'+':''}${t.pnl}</td>
        <td>${t.willy_confirmed?'⭐':'—'}</td>
        <td class="${t.result==='WIN'?'pos':'neg'}">${t.result}</td></tr>`).join('');
    }

    const lc={SIGNAL:'#f59e0b',TRADE:'#4ade80',ERROR:'#f87171',WARN:'#f59e0b',LEARN:'#c084fc'};
    document.getElementById('log-box').innerHTML=(d.log||[]).map(l=>
      `<div class="le" style="color:${lc[l.level]||'#60a5fa'}">
        <span style="color:#374151">${l.time}</span> [${l.level}] ${l.msg}</div>`).join('');
  }catch(e){console.error(e)}
  setTimeout(refresh,10000);
}
refresh();
setInterval(()=>{document.getElementById('clk').textContent=new Date().toUTCString().slice(17,25)+' UTC';},1000);
</script>
</body></html>"""

# ── API ROUTEN ───────────────────────────────
@app.route("/")
def dashboard(): return render_template_string(DASHBOARD)

@app.route("/state")
def state():
    return jsonify({
        "price":bot_state["price"],"last_update":bot_state["last_update"],
        "last_signal":bot_state["last_signal"],"indicators":bot_state["indicators"],
        "indicators_15m":bot_state["indicators_15m"],
        "indicators_1h":bot_state["indicators_1h"],
        "indicators_4h":bot_state["indicators_4h"],
        "trends":bot_state["trends"],
        "learning":bot_state["learning"],
        "log":bot_state["log"][:40],
        "stats":bot_state["stats"],
        "open_trade":bot_state["open_trade"],
        "running":bot_state["running"],
        "willy_last":bot_state["willy_last"],
        "willy_signals_count":len(bot_state["willy_signals"]),
    })

@app.route("/trades")
def trades(): return jsonify(bot_state["trades"])

@app.route("/signals")
def signals(): return jsonify(bot_state["signals"][:50])

@app.route("/learning")
def learning_route(): return jsonify(bot_state["learning"])

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data=request.get_json(force=True)
        add_log(f"Webhook: {data}","INFO")
        sig_type=data.get("signal","").upper()
        tf=data.get("timeframe","—")
        price_raw=data.get("price") or data.get("close")
        if price_raw:
            try:
                p=float(str(price_raw).replace(",","."))
                if 1500<p<5000: bot_state["prices"].append(p); bot_state["price"]=p
            except: pass
        if sig_type:
            we={"signal_type":sig_type,"timeframe":tf,"score":data.get("score","—"),
                "entry":data.get("entry") or price_raw,
                "tp1":data.get("tp1"),"tp2":data.get("tp2"),"tp3":data.get("tp3"),
                "sl":data.get("sl"),
                "time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                "date":datetime.datetime.utcnow().strftime("%d.%m.%Y")}
            bot_state["willy_last"]=we
            bot_state["willy_signals"].insert(0,we)
            if len(bot_state["willy_signals"])>100: bot_state["willy_signals"].pop()
            add_log(f"⭐ WillyAlgoTrader: {sig_type} | TF:{tf}","SIGNAL")
        return jsonify({"status":"ok"}),200
    except Exception as e:
        add_log(f"Webhook Fehler: {e}","ERROR")
        return jsonify({"status":"error","message":str(e)}),400

@app.route("/health")
def health(): return jsonify({"status":"healthy","version":"2.2","time":datetime.datetime.utcnow().isoformat()})

@app.route("/start")
def start():
    if not bot_state["running"]:
        bot_state["running"]=True
        threading.Thread(target=analysis_loop,daemon=True).start()
        return jsonify({"status":"Bot gestartet"})
    return jsonify({"status":"Läuft bereits"})

@app.route("/stop")
def stop():
    bot_state["running"]=False
    return jsonify({"status":"Bot gestoppt"})

if __name__=="__main__":
    bot_state["running"]=True
    threading.Thread(target=analysis_loop,daemon=True).start()
    add_log("XAUUSD KI-Bot v2.2 gestartet","INFO")
    app.run(host="0.0.0.0",port=8080)
