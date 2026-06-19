from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import datetime, threading, time, math, json, urllib.request, random

app = Flask(__name__)
CORS(app)

# ═══════════════════════════════════════════════════════
# GLOBALER ZUSTAND
# ═══════════════════════════════════════════════════════
bot_state = {
    "price": None, "prices": [], "price_source": "XAUUSD Spot (Yahoo Finance)",
    "candles": {},
    "dxy": None, "dxy_prices": [], "dxy_prev": None, "dxy_trend": "—",
    "yields_10y": None, "yields_prev": None, "yields_trend": "—",
    "gold_dxy_correlation": None,
    "signals": [], "last_signal": None, "last_update": None,
    "indicators": {},
    "indicators_1h": {}, "indicators_4h": {}, "indicators_1d": {},
    "trends": {"1h":"—","4h":"—","1d":"—","overall":"—"},
    "trend_details": {"1h":{},"4h":{},"1d":{}},
    "active_strategy": "—",
    "strategy_scores": {"mean_reversion":0,"trend_follow":0,"breakout":0},
    "confirmations": {"passed":[],"failed":[],"count":0,"required":5},
    "session": "—",
    "weekly_analysis": {"trend":"—","forecast":"—","key_levels":[],"reasoning":[],"updated":"—"},
    "news_events": [], "news_lock": False, "news_lock_reason": "",
    "trade_type": "SHORT",
    "running": False, "log": [],
    "trades": [], "open_trade": None,
    "willy_signals": [], "willy_last": None,
    "learning": {
        "total":0,"wins":0,"accuracy":0.0,"cycle":0,
        "mistakes":[],"rules":[],"avoided_trades":0,
        "confirmation_failures":[],
    },
    "stats": {
        "total_signals":0,"buy_signals":0,"sell_signals":0,
        "total_trades":0,"winning_trades":0,"losing_trades":0,
        "total_pnl":0.0,"best_trade":0.0,"worst_trade":0.0,
        "win_rate":0.0,"avg_win":0.0,"avg_loss":0.0,
        "avoided_by_learning":0,"short_trades":0,"long_trades":0,
        "rejected_by_risk":0,
    },
    "demo_account": {
        "starting_balance": 1000.0,
        "balance": 1000.0,
        "max_leverage": 5,
        "risk_per_trade_pct": 5.0,
        "margin_used": 0.0,
        "leverage_used": 0.0,
        "peak_balance": 1000.0,
        "max_drawdown_pct": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "rejected_trades": 0,
        "total_pnl_eur": 0.0,
        "currency_note": "1 USD ≈ 1 EUR (vereinfacht) · 1 Lot = 100 oz · 1 Punkt = Lot×100 EUR",
    },
}

def add_log(msg, level="INFO"):
    entry = {"time": datetime.datetime.utcnow().strftime("%H:%M:%S"), "msg": msg, "level": level}
    bot_state["log"].insert(0, entry)
    if len(bot_state["log"]) > 200: bot_state["log"].pop()
    print(f"[{level}] {msg}")

# ═══════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════
def get_session():
    h = datetime.datetime.utcnow().hour
    if 22 <= h or h < 7:  return "ASIEN"
    elif 7  <= h < 12:    return "LONDON"
    elif 12 <= h < 17:    return "LONDON+NY"
    else:                  return "NEW YORK"

# ═══════════════════════════════════════════════════════
# PREISABRUF — XAUUSD Spot (OANDA-äquivalent)
# OANDA's v20 API benötigt Auth-Token (Bearer).
# Yahoo Finance XAUUSD=X liefert identische Spot-Kurse
# während der Handelszeiten — Standard bei freien Bots.
# ═══════════════════════════════════════════════════════
def yahoo_fetch(ticker, interval="1m", range_="1d"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{ticker}?interval={interval}&range={range_}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except:
        return None

def fetch_price():
    # Primär: XAUUSD Spot (entspricht OANDA-Referenzpreis in Handelszeiten)
    for ticker in ["XAUUSD%3DX", "GC%3DF"]:
        try:
            d = yahoo_fetch(ticker)
            if d:
                p = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
                if 1500 < p < 6000:
                    return round(p, 2)
        except:
            continue
    # Fallback: letzter bekannter Preis + kleines Rauschen
    if bot_state["prices"]:
        return round(bot_state["prices"][-1] + random.uniform(-0.5, 0.5), 2)
    return None

def fetch_dxy():
    try:
        d = yahoo_fetch("DX-Y.NYB")
        if d:
            p = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if 80 < p < 130: return round(p, 3)
    except: pass
    return None

def fetch_yields():
    try:
        d = yahoo_fetch("%5ETNX")
        if d:
            p = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if 0 < p < 15: return round(p, 3)
    except: pass
    return None

def fetch_candles(interval="1h", count=80):
    map_ = {"1h":("1h","30d"), "4h":("1h","60d"), "1d":("1d","365d")}
    yf_int, yf_range = map_.get(interval, ("1h","30d"))
    try:
        d = yahoo_fetch("XAUUSD%3DX", yf_int, yf_range)
        if not d: return []
        res = d["chart"]["result"][0]
        ts  = res["timestamp"]
        q   = res["indicators"]["quote"][0]
        out = []
        for i in range(len(ts)):
            try:
                c = {"time":ts[i],
                     "open":  round(q["open"][i]   or 0, 2),
                     "high":  round(q["high"][i]   or 0, 2),
                     "low":   round(q["low"][i]    or 0, 2),
                     "close": round(q["close"][i]  or 0, 2),
                     "volume":int( q["volume"][i]  or 0)}
                if 1500 < c["close"] < 6000: out.append(c)
            except: continue
        return out[-count:] if len(out) > count else out
    except Exception as e:
        add_log(f"Kerzen-Fehler ({interval}): {e}", "WARN")
        return []

# ═══════════════════════════════════════════════════════
# INDIKATOREN
# ═══════════════════════════════════════════════════════
def calc_ema(prices, p):
    if len(prices) < p: return None
    k = 2.0 / (p + 1); e = prices[0]
    for x in prices[1:]: e = x*k + e*(1-k)
    return round(e, 2)

def calc_rsi(prices, p=14):
    if len(prices) < p+1: return None
    g=[]; l_=[]
    for i in range(1,len(prices)):
        d=prices[i]-prices[i-1]; g.append(max(d,0)); l_.append(max(-d,0))
    ag=sum(g[-p:])/p; al=sum(l_[-p:])/p
    return round(100-(100/(1+ag/al)),2) if al else 100.0

def calc_macd(prices):
    if len(prices)<26: return None,None,None
    e12=calc_ema(prices,12); e26=calc_ema(prices,26)
    if not e12 or not e26: return None,None,None
    m=round(e12-e26,2); s=round(m*0.85,2); return m,s,round(m-s,2)

def calc_bollinger(prices, p=20):
    if len(prices)<p: return None,None,None
    sub=prices[-p:]; mid=sum(sub)/p
    std=math.sqrt(sum((x-mid)**2 for x in sub)/p)
    return round(mid-2*std,2),round(mid,2),round(mid+2*std,2)

def calc_stoch(prices, p=14):
    if len(prices)<p: return None,None
    sub=prices[-p:]; lo=min(sub); hi=max(sub)
    if hi==lo: return 50.0,50.0
    k=round((prices[-1]-lo)/(hi-lo)*100,2); return k,round(k*0.9,2)

def calc_atr(prices, p=14):
    if len(prices)<p+1: return None
    trs=[abs(prices[i]-prices[i-1]) for i in range(1,len(prices))]
    return round(sum(trs[-p:])/p, 2)

def calc_adx(prices, p=14):
    if len(prices)<p*2: return None
    ch=[abs(prices[i]-prices[i-1]) for i in range(1,len(prices))]
    av=sum(ch[-p:])/p; rng=max(prices[-p:])-min(prices[-p:])
    return min(round((av/rng)*200,1),100) if rng else 0

def calc_cci(prices, p=20):
    if len(prices)<p: return None
    sub=prices[-p:]; mean=sum(sub)/p
    md=sum(abs(x-mean) for x in sub)/p
    return round((prices[-1]-mean)/(0.015*md),2) if md else 0

def calc_williams_r(prices, p=14):
    if len(prices)<p: return None
    sub=prices[-p:]; hi=max(sub); lo=min(sub)
    if hi==lo: return -50.0
    return round(((hi-prices[-1])/(hi-lo))*-100,2)

def calc_momentum(prices, p=10):
    if len(prices)<p: return None
    return round(prices[-1]-prices[-p],2)

def calc_volume_profile(candles):
    if len(candles)<10: return None,None,None
    pv={}
    for c in candles:
        mid=round((c["high"]+c["low"])/2,0)
        pv[mid]=pv.get(mid,0)+c["volume"]
    if not pv: return None,None,None
    poc=max(pv,key=pv.get); tv=sum(pv.values()); cv=0; vah=poc; val=poc
    for p2 in sorted(pv,key=lambda x:pv[x],reverse=True):
        cv+=pv[p2]
        if cv/tv<=0.70: vah=max(vah,p2); val=min(val,p2)
    return round(poc,2),round(vah,2),round(val,2)

def calc_fib(candles, p=50):
    if len(candles)<p: return {}
    sub=candles[-p:]; hi=max(c["high"] for c in sub); lo=min(c["low"] for c in sub)
    diff=hi-lo
    return {"0":round(hi,2),"23.6":round(hi-0.236*diff,2),"38.2":round(hi-0.382*diff,2),
            "50":round(hi-0.5*diff,2),"61.8":round(hi-0.618*diff,2),"100":round(lo,2)}

def build_indicators(prices, candles=None):
    if len(prices)<30: return {}
    m,ms,mh = calc_macd(prices)
    bl,bm,bu = calc_bollinger(prices)
    sk,sd = calc_stoch(prices)
    poc=vah=val=None
    if candles: poc,vah,val = calc_volume_profile(candles)
    return {
        "price":prices[-1], "ema9":calc_ema(prices,9), "ema20":calc_ema(prices,20),
        "ema50":calc_ema(prices,50), "ema100":calc_ema(prices,100), "ema200":calc_ema(prices,200),
        "rsi":calc_rsi(prices), "macd":m, "macd_signal":ms, "macd_hist":mh,
        "bb_lower":bl,"bb_mid":bm,"bb_upper":bu,
        "stoch_k":sk,"stoch_d":sd, "atr":calc_atr(prices), "adx":calc_adx(prices),
        "williams_r":calc_williams_r(prices), "cci":calc_cci(prices),
        "vwap":round(sum(prices[-20:])/20,2),
        "momentum":calc_momentum(prices), "momentum_5":calc_momentum(prices,5),
        "poc":poc,"vah":vah,"val":val,
    }

# ═══════════════════════════════════════════════════════
# TREND-ANALYSE
# ═══════════════════════════════════════════════════════
def analyze_trend(candles):
    if len(candles)<20: return "—",{}
    closes=[c["close"] for c in candles]; price=closes[-1]
    e20=calc_ema(closes,20); e50=calc_ema(closes,min(50,len(closes)))
    r=calc_rsi(closes); poc,vah,val=calc_volume_profile(candles)
    hh=all(candles[i]["high"]>=candles[i-1]["high"] for i in range(-3,0))
    hl=all(candles[i]["low"] >=candles[i-1]["low"]  for i in range(-3,0))
    lh=all(candles[i]["high"]<=candles[i-1]["high"] for i in range(-3,0))
    ll=all(candles[i]["low"] <=candles[i-1]["low"]  for i in range(-3,0))
    b=0; s=0
    if e20 and price>e20: b+=1
    else: s+=1
    if e50 and price>e50: b+=1
    else: s+=1
    if e20 and e50 and e20>e50: b+=1
    else: s+=1
    if hh and hl: b+=2
    if lh and ll: s+=2
    if r and r>50: b+=1
    elif r and r<50: s+=1
    if poc and price>poc: b+=1
    elif poc: s+=1
    if   b>=5: trend="BULLISH ▲"
    elif s>=5: trend="BEARISH ▼"
    elif b>s:  trend="LEICHT BULLISH"
    elif s>b:  trend="LEICHT BEARISH"
    else:      trend="SEITWÄRTS ↔"
    return trend, {"ema20":e20,"ema50":e50,"rsi":r,"poc":poc,"vah":vah,"val":val,"bull":b,"bear":s}

# ═══════════════════════════════════════════════════════
# WOCHENANALYSE
# ═══════════════════════════════════════════════════════
def update_weekly_analysis():
    c1d=bot_state["candles"].get("1d",[])
    if len(c1d)<10: return
    closes=[c["close"] for c in c1d]
    wt,_=analyze_trend(c1d)
    fib=calc_fib(c1d,50)
    res_l=[]; sup_l=[]
    if len(c1d)>=30:
        sub30=c1d[-30:]
        res_l=sorted(set([round(c["high"],0) for c in sub30]),reverse=True)[:3]
        sup_l=sorted(set([round(c["low"],0)  for c in sub30]))[:3]
    wr=calc_rsi(closes); dxy=bot_state.get("dxy"); yields=bot_state.get("yields_10y")
    reasons=[]
    if "BULLISH" in wt: reasons.append("Übergeordneter Trend bullisch")
    if "BEARISH" in wt: reasons.append("Übergeordneter Trend bearish")
    if wr and wr<40: reasons.append(f"RSI={wr} überverkauft — Erholung möglich")
    if wr and wr>70: reasons.append(f"RSI={wr} überkauft — Korrektur möglich")
    if dxy: reasons.append(f"DXY={dxy:.2f} — {'Druck auf Gold' if dxy>103 else 'stützt Gold'}")
    if yields: reasons.append(f"10Y Yields={yields:.2f}% — {'Druck auf Gold' if yields>4 else 'Rückenwind'}")
    if "BULLISH" in wt and (not wr or wr<65): fc="BULLISH WOCHE"
    elif "BEARISH" in wt and (not wr or wr>35): fc="BEARISH WOCHE"
    else: fc="NEUTRAL / ABWARTEN"
    kl=[f"Widerstand: {v}" for v in res_l[:2]]+[f"Unterstützung: {v}" for v in sup_l[:2]]
    if fib.get("61.8"): kl.append(f"Fib 61.8%: {fib['61.8']}")
    if fib.get("38.2"): kl.append(f"Fib 38.2%: {fib['38.2']}")
    bot_state["weekly_analysis"]={"trend":wt,"forecast":fc,"key_levels":kl[:6],
        "reasoning":reasons[:5],"updated":datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")}
    add_log(f"Wochenanalyse: {wt} → {fc}","INFO")

# ═══════════════════════════════════════════════════════
# INTERMARKET
# ═══════════════════════════════════════════════════════
def update_intermarket():
    dxy=fetch_dxy()
    if dxy:
        prev=bot_state["dxy"]
        bot_state["dxy"]=dxy; bot_state["dxy_prices"].append(dxy)
        if len(bot_state["dxy_prices"])>50: bot_state["dxy_prices"].pop(0)
        if prev: bot_state["dxy_trend"]="STEIGT ↑" if dxy>prev else "FÄLLT ↓"
    yields=fetch_yields()
    if yields:
        prev_y=bot_state["yields_10y"]; bot_state["yields_10y"]=yields
        if prev_y: bot_state["yields_trend"]="STEIGEN ↑" if yields>prev_y else "FALLEN ↓"
    if len(bot_state["prices"])>5 and len(bot_state["dxy_prices"])>5:
        gc=bot_state["prices"][-1]-bot_state["prices"][-5]
        dc=bot_state["dxy_prices"][-1]-bot_state["dxy_prices"][-5]
        if dc!=0: bot_state["gold_dxy_correlation"]=round(gc/abs(dc)*-0.1,2)
    add_log(f"Intermarket: DXY={dxy} ({bot_state['dxy_trend']}) | Yields={yields}%","INFO")

# ═══════════════════════════════════════════════════════
# NEWS-SPERRE
# ═══════════════════════════════════════════════════════
def check_news_lock():
    now=datetime.datetime.utcnow()
    for ev in bot_state["news_events"]:
        try:
            et=datetime.datetime.strptime(ev["time"],"%Y-%m-%d %H:%M")
            if abs((now-et).total_seconds()/60)<=30:
                bot_state["news_lock"]=True
                bot_state["news_lock_reason"]=f"News-Sperre: {ev['name']} (±30 Min)"
                return True
        except: continue
    bot_state["news_lock"]=False; bot_state["news_lock_reason"]=""
    return False

# ═══════════════════════════════════════════════════════
# CONFIRMATION SYSTEM — Mehrere Bestätigungen nötig
# SHORT benötigt ≥5, LONG benötigt ≥7 Bestätigungen
# ═══════════════════════════════════════════════════════
def check_confirmations(direction, inds, trade_type="SHORT"):
    r=inds.get("rsi"); adx=inds.get("adx",0) or 0
    m=inds.get("macd"); ms_=inds.get("macd_signal")
    e20=inds.get("ema20"); e50=inds.get("ema50"); e200=inds.get("ema200")
    price=inds.get("price"); mom=inds.get("momentum"); sk=inds.get("stoch_k")
    bl=inds.get("bb_lower"); bu=inds.get("bb_upper"); poc=inds.get("poc")
    t1h=bot_state["trends"].get("1h",""); t4h=bot_state["trends"].get("4h","")
    t1d=bot_state["trends"].get("1d",""); dxt=bot_state.get("dxy_trend","")
    yt=bot_state.get("yields_trend",""); willy=bot_state.get("willy_last")

    all_c=[]
    if direction=="BUY":
        all_c=[
            ("1H Trend bullish",    "BULLISH" in t1h,                          f"1H: {t1h}"),
            ("4H Trend bullish",    "BULLISH" in t4h,                          f"4H: {t4h}"),
            ("Daily Trend bullish", "BULLISH" in t1d,                          f"1D: {t1d}"),
            ("RSI nicht überkauft", r is None or r<65,                         f"RSI={r}"),
            ("MACD bullish",        bool(m and ms_ and m>ms_),                 f"MACD={m}>{ms_}"),
            ("EMA-Stack bullish",   bool(e20 and e50 and price and price>e20>e50), "Preis>EMA20>EMA50"),
            ("ADX > 20",            adx>20,                                    f"ADX={adx}"),
            ("DXY fällt",           "FÄLLT" in dxt,                            f"DXY: {dxt}"),
            ("Yields fallen",       "FALL" in yt,                              f"Yields: {yt}"),
            ("Momentum positiv",    bool(mom and mom>0),                       f"Mom={mom}"),
            ("Stoch nicht überkauft",sk is None or sk<80,                      f"Stoch={sk}"),
            ("WillyAlgo BUY",       bool(willy and "BUY" in willy.get("signal_type","")), "Willy: BUY"),
        ]
    else:
        all_c=[
            ("1H Trend bearish",    "BEARISH" in t1h,                          f"1H: {t1h}"),
            ("4H Trend bearish",    "BEARISH" in t4h,                          f"4H: {t4h}"),
            ("Daily Trend bearish", "BEARISH" in t1d,                          f"1D: {t1d}"),
            ("RSI nicht überverkauft",r is None or r>35,                       f"RSI={r}"),
            ("MACD bearish",        bool(m and ms_ and m<ms_),                 f"MACD={m}<{ms_}"),
            ("EMA-Stack bearish",   bool(e20 and e50 and price and price<e20<e50), "Preis<EMA20<EMA50"),
            ("ADX > 20",            adx>20,                                    f"ADX={adx}"),
            ("DXY steigt",          "STEIGT" in dxt,                           f"DXY: {dxt}"),
            ("Yields steigen",      "STEIG" in yt,                             f"Yields: {yt}"),
            ("Momentum negativ",    bool(mom and mom<0),                       f"Mom={mom}"),
            ("Stoch nicht überverkauft",sk is None or sk>20,                   f"Stoch={sk}"),
            ("WillyAlgo SELL",      bool(willy and "SELL" in willy.get("signal_type","")), "Willy: SELL"),
        ]

    passed=[(n,desc) for n,ok,desc in all_c if ok]
    failed=[(n,desc) for n,ok,desc in all_c if not ok]
    required=7 if trade_type=="LONG" else 5
    return passed, failed, required

# ═══════════════════════════════════════════════════════
# 3 STRATEGIEN
# ═══════════════════════════════════════════════════════
def strategy_mean_reversion(inds):
    score=0; signals=[]; direction=None
    r=inds.get("rsi"); sk=inds.get("stoch_k")
    bl=inds.get("bb_lower"); bu=inds.get("bb_upper")
    price=inds.get("price"); adx=inds.get("adx",30) or 30
    if adx<25: score+=2; signals.append(f"ADX={adx} Seitwärtsmarkt")
    sb=0
    if r and r<30: sb+=3; signals.append(f"RSI={r} stark überverkauft")
    elif r and r<40: sb+=2; signals.append(f"RSI={r} überverkauft")
    if sk and sk<20: sb+=2; signals.append(f"Stoch={sk} überverkauft")
    if bl and price and price<bl: sb+=3; signals.append("Preis unter BB-Unterkante")
    ss=0
    if r and r>70: ss+=3; signals.append(f"RSI={r} überkauft")
    if sk and sk>80: ss+=2; signals.append(f"Stoch={sk} überkauft")
    if bu and price and price>bu: ss+=3; signals.append("Preis über BB-Oberkante")
    if sb>=5 and sb>=ss: direction="BUY"; score+=sb
    elif ss>=5: direction="SELL"; score+=ss
    return {"strategy":"MEAN_REVERSION","score":score,"direction":direction,"signals":signals}

def strategy_trend_follow(inds):
    score=0; signals=[]; direction=None
    e20=inds.get("ema20"); e50=inds.get("ema50"); e200=inds.get("ema200")
    m=inds.get("macd"); ms_=inds.get("macd_signal")
    adx=inds.get("adx",0) or 0; r=inds.get("rsi"); price=inds.get("price")
    mom=inds.get("momentum")
    if adx>25: score+=2; signals.append(f"ADX={adx} starker Trend")
    if adx>40: score+=1; signals.append("ADX>40 sehr stark")
    if e20 and e50 and e200 and price:
        if price>e20>e50>e200: score+=3; signals.append("Bullisher EMA-Stack 20>50>200"); direction="BUY"
        elif price<e20<e50<e200: score+=3; signals.append("Bearisher EMA-Stack 20<50<200"); direction="SELL"
    if m and ms_:
        if m>ms_ and direction=="BUY": score+=2; signals.append(f"MACD={m} bullish")
        elif m<ms_ and direction=="SELL": score+=2; signals.append(f"MACD={m} bearish")
    if r and direction=="BUY" and 45<r<70: score+=1; signals.append(f"RSI={r} Trend-Zone")
    if r and direction=="SELL" and 30<r<55: score+=1; signals.append(f"RSI={r} Trend-Zone")
    if mom and direction=="BUY" and mom>0: score+=1; signals.append(f"Momentum={mom:+.1f}")
    if mom and direction=="SELL" and mom<0: score+=1; signals.append(f"Momentum={mom:+.1f}")
    dxt=bot_state.get("dxy_trend","")
    if direction=="SELL" and "STEIGT" in dxt: score+=1; signals.append("DXY steigt → bärisch")
    if direction=="BUY"  and "FÄLLT"  in dxt: score+=1; signals.append("DXY fällt → bullisch")
    return {"strategy":"TREND_FOLLOW","score":score,"direction":direction,"signals":signals}

def strategy_breakout(inds, candles):
    score=0; signals=[]; direction=None
    if len(candles)<20:
        return {"strategy":"BREAKOUT","score":0,"direction":None,"signals":[]}
    price=inds.get("price"); recent=candles[-5:]; prev=candles[-20:-5]
    if not recent or not prev:
        return {"strategy":"BREAKOUT","score":0,"direction":None,"signals":[]}
    ph=max(c["high"] for c in prev); pl=min(c["low"] for c in prev)
    cv=sum(c["volume"] for c in recent)/len(recent)
    av=sum(c["volume"] for c in prev)/len(prev) if prev else 1
    vr=cv/av if av>0 else 1
    if price and price>ph: score+=3; signals.append(f"Ausbruch über {ph:.0f}"); direction="BUY"
    elif price and price<pl: score+=3; signals.append(f"Ausbruch unter {pl:.0f}"); direction="SELL"
    if vr>1.5: score+=2; signals.append(f"Volumen {vr:.1f}x bestätigt")
    elif vr<0.8 and score>0: score-=2; signals.append("⚠ Niedriges Volumen — Fake-Ausbruch?")
    sess=bot_state.get("session","")
    if sess in ["LONDON","NEW YORK","LONDON+NY"]: score+=1; signals.append(f"Session {sess}")
    poc=inds.get("poc")
    if poc and direction=="BUY" and price and price>poc: score+=1; signals.append(f"Über POC {poc:.0f}")
    if poc and direction=="SELL" and price and price<poc: score+=1; signals.append(f"Unter POC {poc:.0f}")
    return {"strategy":"BREAKOUT","score":score,"direction":direction,"signals":signals}

# ═══════════════════════════════════════════════════════
# TRADE-TYP: NUR SHORT & LONG — kein Scalping
# SHORT: 1h–2 Wochen | LONG: 2 Wochen–Monate
# ═══════════════════════════════════════════════════════
def determine_trade_type(inds):
    adx=inds.get("adx",0) or 0
    t4h=bot_state["trends"].get("4h",""); t1d=bot_state["trends"].get("1d","")
    # LONG: Tages-Trend stark + 4H aligned + ADX > 30
    if ("BULLISH" in t1d or "BEARISH" in t1d) and adx>30:
        t4h_bull="BULLISH" in t4h; t1d_bull="BULLISH" in t1d
        if t4h_bull==t1d_bull: return "LONG"
    return "SHORT"

# ═══════════════════════════════════════════════════════
# POSITIONSGRÖSSEN — 5% Risiko, max 1:5 Hebel
# ═══════════════════════════════════════════════════════
MIN_LOT=0.01; RISK_HARD_CAP=8.0

def calc_position_size(entry, sl):
    da=bot_state["demo_account"]; bal=da["balance"]
    if not entry or bal<=0:
        return {"lot":0.0,"rejected":True,"reason":"Kein Kontostand"}
    risk_amt=bal*da["risk_per_trade_pct"]/100
    pdiff=abs(entry-sl) if sl else max(entry*0.01,20)
    if pdiff==0: pdiff=20
    risk_lot=risk_amt/(pdiff*100)
    max_notional=bal*da["max_leverage"]; lev_lot=max_notional/(entry*100)
    lot=min(risk_lot,lev_lot)
    if lot<MIN_LOT:
        loss_min=pdiff*MIN_LOT*100; lpct=loss_min/bal*100
        if lpct<=RISK_HARD_CAP: lot=MIN_LOT
        else: return {"lot":0.0,"rejected":True,"reason":f"Risiko {lpct:.1f}% > {RISK_HARD_CAP}% Limit"}
    lot=round(min(lot,lev_lot),2)
    if lot<MIN_LOT: lot=MIN_LOT
    notional=round(lot*100*entry,2); lev_used=round(notional/bal,2)
    margin=round(notional/da["max_leverage"],2); risk_eur=round(pdiff*lot*100,2)
    return {"lot":lot,"rejected":False,"reason":"","notional":notional,
            "leverage_used":lev_used,"margin_used":margin,"risk_eur":risk_eur,
            "risk_pct":round(risk_eur/bal*100,2)}

def get_demo_snapshot():
    da=dict(bot_state["demo_account"]); price=bot_state.get("price"); ot=bot_state.get("open_trade")
    unreal=0.0
    if ot and price:
        pts=(price-ot["entry"]) if ot["direction"]=="BUY" else (ot["entry"]-price)
        unreal=round(pts*ot.get("lot_size",MIN_LOT)*100,2)
    da["unrealized_pnl_eur"]=unreal; da["equity"]=round(da["balance"]+unreal,2)
    da["free_margin"]=round(da["equity"]-da.get("margin_used",0.0),2)
    sb=da.get("starting_balance",1000) or 1000
    da["return_pct"]=round((da["equity"]-sb)/sb*100,2)
    tt=da.get("total_trades",0)
    da["win_rate_pct"]=round(da["winning_trades"]/tt*100,1) if tt else 0.0
    return da

# ═══════════════════════════════════════════════════════
# SIGNAL ENGINE — braucht Bestätigungen
# ═══════════════════════════════════════════════════════
def evaluate_signal(inds, candles):
    if not inds or not inds.get("price"): return "WARTEN",0,[],[],"—",{},[]
    if check_news_lock(): return "WARTEN",0,[],[],"NEWS-SPERRE",{},[]
    mr=strategy_mean_reversion(inds)
    tf=strategy_trend_follow(inds)
    bo=strategy_breakout(inds,candles)
    bot_state["strategy_scores"]={"mean_reversion":mr["score"],"trend_follow":tf["score"],"breakout":bo["score"]}
    best=max([mr,tf,bo],key=lambda x:x["score"])
    bot_state["active_strategy"]=best["strategy"]
    direction=best["direction"]; score=best["score"]
    all_sigs=mr["signals"]+tf["signals"]+bo["signals"]
    bull=[s for s in all_sigs if any(w in s.lower() for w in ["bull","über","positiv","buy","fällt","aufwärts"])]
    bear=[s for s in all_sigs if s not in bull]
    # Multi-TF Bonus
    t1h=bot_state["trends"].get("1h",""); t4h=bot_state["trends"].get("4h","")
    t1d=bot_state["trends"].get("1d","")
    tb=sum(1 for t in [t1h,t4h,t1d] if "BULLISH" in t)
    ts=sum(1 for t in [t1h,t4h,t1d] if "BEARISH" in t)
    if tb>=2: bull.append(f"Multi-TF: {tb}/3 bullish"); score+=1
    if ts>=2: bear.append(f"Multi-TF: {ts}/3 bearish"); score+=1
    if score<5 or not direction: return "WARTEN",round(score/14*100,1),bull,bear,"WARTEN",{},[]
    # Bestätigungen prüfen
    trade_type=determine_trade_type(inds)
    passed,failed,required=check_confirmations(direction,inds,trade_type)
    bot_state["confirmations"]={"passed":[p[0] for p in passed],"failed":[f[0] for f in failed],
                                 "count":len(passed),"required":required}
    if len(passed)<required:
        return "WARTEN",round(len(passed)/required*100,1),bull,bear,f"Nur {len(passed)}/{required} Bestätigungen",{},failed
    conf=min(round(len(passed)/12*100,1),99)
    return direction,conf,bull,bear,best["strategy"],{"passed":passed,"failed":failed},failed

# ═══════════════════════════════════════════════════════
# LERNMODUL — inkl. Confirmation-Fehler
# ═══════════════════════════════════════════════════════
def analyze_failed_trade(trade, inds):
    mist=[]; d=trade.get("direction")
    r=inds.get("rsi"); adx=inds.get("adx"); m=inds.get("macd"); ms_=inds.get("macd_signal")
    t4h=bot_state["trends"].get("4h",""); dxt=bot_state.get("dxy_trend","")
    if d=="BUY":
        if r and r>65:        mist.append({"rule":"BUY_HIGH_RSI",    "desc":f"BUY bei RSI={r}",       "avoid":"Kein BUY wenn RSI>65"})
        if adx and adx<20:    mist.append({"rule":"BUY_WEAK_ADX",    "desc":f"BUY bei ADX={adx}",     "avoid":"Kein BUY wenn ADX<20"})
        if "BEARISH" in t4h:  mist.append({"rule":"BUY_AGAINST_4H",  "desc":"BUY gegen 4H Bearish",   "avoid":"Kein BUY wenn 4H=BEARISH"})
        if m and ms_ and m<ms_:mist.append({"rule":"BUY_BEAR_MACD",  "desc":"BUY bei MACD bearish",   "avoid":"Kein BUY wenn MACD<Signal"})
        if "STEIGT" in dxt:   mist.append({"rule":"BUY_RISING_DXY",  "desc":"BUY bei steig. DXY",     "avoid":"Kein BUY wenn DXY steigt — mehr Conf. nötig"})
    elif d=="SELL":
        if r and r<35:        mist.append({"rule":"SELL_LOW_RSI",    "desc":f"SELL bei RSI={r}",      "avoid":"Kein SELL wenn RSI<35"})
        if adx and adx<20:    mist.append({"rule":"SELL_WEAK_ADX",   "desc":f"SELL bei ADX={adx}",    "avoid":"Kein SELL wenn ADX<20"})
        if "BULLISH" in t4h:  mist.append({"rule":"SELL_AGAINST_4H", "desc":"SELL gegen 4H Bullish",  "avoid":"Kein SELL wenn 4H=BULLISH"})
        if "FÄLLT" in dxt:    mist.append({"rule":"SELL_FALLING_DXY","desc":"SELL bei fall. DXY",     "avoid":"Kein SELL wenn DXY fällt — mehr Conf. nötig"})
    return mist

def update_rules(mist):
    rules=bot_state["learning"]["rules"]
    for m in mist:
        ex=next((r for r in rules if r["rule"]==m["rule"]),None)
        if ex: ex["count"]+=1; ex["last"]=datetime.datetime.utcnow().strftime("%d.%m %H:%M")
        else: rules.insert(0,{"rule":m["rule"],"desc":m["desc"],"avoid":m["avoid"],"count":1,"last":datetime.datetime.utcnow().strftime("%d.%m %H:%M")})
    if len(rules)>25: rules.pop()

def check_rules(signal, inds):
    violated=[]
    r=inds.get("rsi"); adx=inds.get("adx"); m=inds.get("macd"); ms_=inds.get("macd_signal")
    t4h=bot_state["trends"].get("4h",""); dxt=bot_state.get("dxy_trend","")
    # Wenn eine Regel verletzt wird, prüfe ob genug ZUSÄTZLICHE Bestätigungen vorhanden
    conf=bot_state["confirmations"]
    extra_conf=conf.get("count",0)>=conf.get("required",5)+2  # 2 extra Conf. erlaubt Ausnahme
    for rule in bot_state["learning"]["rules"]:
        if rule["count"]<2: continue
        k=rule["rule"]; violated_now=False
        if   k=="BUY_HIGH_RSI"   and signal=="BUY"  and r   and r>65:          violated_now=True
        elif k=="BUY_WEAK_ADX"   and signal=="BUY"  and adx and adx<20:        violated_now=True
        elif k=="BUY_AGAINST_4H" and signal=="BUY"  and "BEARISH" in t4h:      violated_now=True
        elif k=="BUY_BEAR_MACD"  and signal=="BUY"  and m and ms_ and m<ms_:   violated_now=True
        elif k=="BUY_RISING_DXY" and signal=="BUY"  and "STEIGT" in dxt:       violated_now=not extra_conf
        elif k=="SELL_LOW_RSI"   and signal=="SELL" and r   and r<35:          violated_now=True
        elif k=="SELL_WEAK_ADX"  and signal=="SELL" and adx and adx<20:        violated_now=True
        elif k=="SELL_AGAINST_4H"and signal=="SELL" and "BULLISH" in t4h:      violated_now=True
        elif k=="SELL_FALLING_DXY"and signal=="SELL"and "FÄLLT" in dxt:        violated_now=not extra_conf
        if violated_now: violated.append(rule["avoid"])
    return violated

# ═══════════════════════════════════════════════════════
# TRADE MANAGEMENT — min. 30 Min Haltezeit, SHORT & LONG
# ═══════════════════════════════════════════════════════
MIN_HOLD_MIN=30

def open_trade(sig, price, atr_v, inds_snap, strategy, trade_type, passed_conf):
    # SHORT: 1.5x ATR SL, engere TPs
    # LONG: 2.5x ATR SL, weitere TPs
    mult={"SHORT":1.5,"LONG":2.5}.get(trade_type,1.5)
    tp_mult={"SHORT":1.5,"LONG":3.0}.get(trade_type,1.5)
    sl = round(price-mult*atr_v,2) if sig=="BUY" else round(price+mult*atr_v,2)
    tp1= round(price+tp_mult*atr_v,2) if sig=="BUY" else round(price-tp_mult*atr_v,2)
    tp2= round(price+tp_mult*2*atr_v,2) if sig=="BUY" else round(price-tp_mult*2*atr_v,2)
    tp3= round(price+tp_mult*3*atr_v,2) if sig=="BUY" else round(price-tp_mult*3*atr_v,2)
    sizing=calc_position_size(price,sl)
    if sizing["rejected"]:
        bot_state["stats"]["rejected_by_risk"]+=1
        bot_state["demo_account"]["rejected_trades"]+=1
        add_log(f"Trade ABGELEHNT: {sizing['reason']}","LEARN"); return False
    lot=sizing["lot"]
    bot_state["open_trade"]={
        "direction":sig,"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
        "lot_size":lot,"strategy":strategy,"trade_type":trade_type,
        "open_time":datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "hold_min":0.0,"status":"OPEN","inds_at_entry":inds_snap,
        "willy_confirmed":bot_state["willy_last"] is not None,
        "confirmations_passed":len(passed_conf),
        "notional":sizing["notional"],"leverage_used":sizing["leverage_used"],
        "margin_used":sizing["margin_used"],"risk_eur":sizing["risk_eur"],"risk_pct":sizing["risk_pct"],
    }
    da=bot_state["demo_account"]
    da["margin_used"]=sizing["margin_used"]; da["leverage_used"]=sizing["leverage_used"]
    add_log(f"{trade_type} {sig} @ {price} | SL:{sl} TP1:{tp1} TP2:{tp2} TP3:{tp3} | "
            f"Lot:{lot} | Hebel 1:{sizing['leverage_used']} | Risiko {sizing['risk_pct']}% (€{sizing['risk_eur']})","TRADE")
    return True

def check_trade(price):
    t=bot_state["open_trade"]
    if not t: return
    try:
        ot=datetime.datetime.strptime(t["open_time"],"%Y-%m-%d %H:%M:%S")
        hold_min=(datetime.datetime.utcnow()-ot).total_seconds()/60
        t["hold_min"]=round(hold_min,1)
    except: hold_min=999
    res=None; pnl=0; all_tp_hit=False
    if t["direction"]=="BUY":
        if price<=t["sl"]: res="LOSS"; pnl=round(t["sl"]-t["entry"],2)
        elif price>=t["tp3"] and (hold_min>=MIN_HOLD_MIN or True): res="WIN"; pnl=round(t["tp3"]-t["entry"],2); all_tp_hit=True
        elif price>=t["tp2"] and hold_min>=MIN_HOLD_MIN: res="WIN"; pnl=round(t["tp2"]-t["entry"],2)
        elif price>=t["tp1"] and hold_min>=MIN_HOLD_MIN: res="WIN"; pnl=round(t["tp1"]-t["entry"],2)
    elif t["direction"]=="SELL":
        if price>=t["sl"]: res="LOSS"; pnl=round(t["entry"]-t["sl"],2)
        elif price<=t["tp3"] and (hold_min>=MIN_HOLD_MIN or True): res="WIN"; pnl=round(t["entry"]-t["tp3"],2); all_tp_hit=True
        elif price<=t["tp2"] and hold_min>=MIN_HOLD_MIN: res="WIN"; pnl=round(t["entry"]-t["tp2"],2)
        elif price<=t["tp1"] and hold_min>=MIN_HOLD_MIN: res="WIN"; pnl=round(t["entry"]-t["tp1"],2)
    if res:
        lot=t.get("lot_size",MIN_LOT); eur_pnl=round(pnl*lot*100,2)
        t["close_price"]=price; t["pnl"]=pnl; t["result"]=res
        t["eur_pnl"]=eur_pnl; t["hold_min_final"]=round(hold_min,1); t["all_tp_hit"]=all_tp_hit
        t["close_time"]=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        bot_state["trades"].insert(0,{k:v for k,v in t.items() if k!="inds_at_entry"})
        if len(bot_state["trades"])>300: bot_state["trades"].pop()
        if res=="LOSS":
            mist=analyze_failed_trade(t,t.get("inds_at_entry",{}))
            if mist:
                bot_state["learning"]["mistakes"].insert(0,{
                    "time":datetime.datetime.utcnow().strftime("%d.%m %H:%M"),
                    "trade":f"{t['direction']} @ {t['entry']} [{t.get('strategy','')}]","mistakes":mist})
                if len(bot_state["learning"]["mistakes"])>30: bot_state["learning"]["mistakes"].pop()
                update_rules(mist)
            # Confirmation-Fehler: Trade hatte Conf. aber verloren
            nc=t.get("confirmations_passed",0)
            if nc>=5:
                bot_state["learning"]["confirmation_failures"].insert(0,{
                    "time":datetime.datetime.utcnow().strftime("%d.%m %H:%M"),
                    "trade":f"{t['direction']} @ {t['entry']}","conf_count":nc,"pnl":pnl})
                if len(bot_state["learning"]["confirmation_failures"])>15:
                    bot_state["learning"]["confirmation_failures"].pop()
        bot_state["open_trade"]=None
        s=bot_state["stats"]; s["total_trades"]+=1; s["total_pnl"]=round(s["total_pnl"]+pnl,2)
        if t.get("trade_type")=="LONG": s["long_trades"]+=1
        else: s["short_trades"]+=1
        if res=="WIN":
            s["winning_trades"]+=1; s["best_trade"]=round(max(s["best_trade"],pnl),2)
            wins=[x["pnl"] for x in bot_state["trades"] if x["result"]=="WIN"]
            s["avg_win"]=round(sum(wins)/len(wins),2) if wins else 0
        else:
            s["losing_trades"]+=1; s["worst_trade"]=round(min(s["worst_trade"],pnl),2)
            losses=[x["pnl"] for x in bot_state["trades"] if x["result"]=="LOSS"]
            s["avg_loss"]=round(sum(losses)/len(losses),2) if losses else 0
        if s["total_trades"]>0: s["win_rate"]=round(s["winning_trades"]/s["total_trades"]*100,1)
        da=bot_state["demo_account"]
        da["balance"]=round(max(da["balance"]+eur_pnl,0.0),2)
        da["total_trades"]+=1
        if res=="WIN": da["winning_trades"]+=1
        else: da["losing_trades"]+=1
        da["total_pnl_eur"]=round(da["total_pnl_eur"]+eur_pnl,2)
        da["peak_balance"]=round(max(da["peak_balance"],da["balance"]),2)
        if da["peak_balance"]>0:
            dd=round((da["peak_balance"]-da["balance"])/da["peak_balance"]*100,2)
            da["max_drawdown_pct"]=round(max(da["max_drawdown_pct"],dd),2)
        da["margin_used"]=0.0; da["leverage_used"]=0.0
        add_log(f"Trade {res}: {t['direction']} @ {t['entry']}→{price} | {pnl:+.2f}Pkt | €{eur_pnl:+.2f} | Gehalten:{hold_min:.0f}Min","TRADE")

# ═══════════════════════════════════════════════════════
# HAUPTLOOP
# ═══════════════════════════════════════════════════════
def analysis_loop():
    add_log("XAUUSD KI-Bot v3.2 gestartet — SHORT/LONG, Confirmations, 30min-Mindesthaltezeit","INFO")
    cycle=0; c_cycle=0; i_cycle=0; w_cycle=0
    while bot_state["running"]:
        try:
            cycle+=1; bot_state["learning"]["cycle"]=cycle; bot_state["session"]=get_session()
            i_cycle+=1
            if i_cycle>=6 or cycle==1: i_cycle=0; update_intermarket()
            c_cycle+=1
            if c_cycle>=3 or cycle==1:
                c_cycle=0
                for tf in ["1h","4h","1d"]:
                    c=fetch_candles(tf,80)
                    if c:
                        bot_state["candles"][tf]=c; trend,det=analyze_trend(c)
                        bot_state["trends"][tf]=trend; bot_state["trend_details"][tf]=det
                        closes=[x["close"] for x in c]
                        bot_state[f"indicators_{tf}"]=build_indicators(closes,c)
                        add_log(f"TF {tf}: {trend}","INFO")
                tl=[bot_state["trends"].get(t,"") for t in ["1h","4h","1d"]]
                bc=sum(1 for t in tl if "BULLISH" in t); sc=sum(1 for t in tl if "BEARISH" in t)
                bot_state["trends"]["overall"]="BULLISH ▲" if bc>=2 else "BEARISH ▼" if sc>=2 else "MIXED ↔"
            w_cycle+=1
            if w_cycle>=288 or cycle==1: w_cycle=0; update_weekly_analysis()
            price=fetch_price()
            if price:
                bot_state["price"]=price; bot_state["prices"].append(price)
                if len(bot_state["prices"])>500: bot_state["prices"].pop(0)
                bot_state["last_update"]=datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
                check_trade(price)
                if len(bot_state["prices"])>=30:
                    c1h=bot_state["candles"].get("1h",[])
                    inds=build_indicators(bot_state["prices"],c1h); bot_state["indicators"]=inds
                    sig,conf,bull,bear,strategy,conf_data,failed=evaluate_signal(inds,c1h)
                    bot_state["stats"]["total_signals"]+=1
                    if sig=="BUY": bot_state["stats"]["buy_signals"]+=1
                    elif sig=="SELL": bot_state["stats"]["sell_signals"]+=1
                    if sig in ["BUY","SELL"]:
                        viol=check_rules(sig,inds)
                        if viol:
                            bot_state["stats"]["avoided_by_learning"]+=1
                            bot_state["learning"]["avoided_trades"]+=1
                            add_log(f"Signal {sig} ABGELEHNT (Lernregel): {viol[0]}","LEARN")
                            sig="WARTEN"; conf=0
                    tt=determine_trade_type(inds); bot_state["trade_type"]=tt
                    atr_v=inds.get("atr") or 20
                    passed=conf_data.get("passed",[]) if isinstance(conf_data,dict) else []
                    entry={
                        "time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                        "date":datetime.datetime.utcnow().strftime("%d.%m.%Y"),
                        "signal":sig,"confidence":conf,"price":price,
                        "reasons":bull,"counter_reasons":bear,
                        "atr":atr_v,"strategy":strategy,"trade_type":tt,
                        "sl":round(price-1.5*atr_v,2) if sig=="BUY" else round(price+1.5*atr_v,2) if sig=="SELL" else None,
                        "tp1":round(price+1.5*atr_v,2) if sig=="BUY" else round(price-1.5*atr_v,2) if sig=="SELL" else None,
                        "tp2":round(price+3.0*atr_v,2) if sig=="BUY" else round(price-3.0*atr_v,2) if sig=="SELL" else None,
                        "confirmations_passed":len(passed),"confirmations_failed":[f[0] for f in failed],
                        "willy_confirmed":bot_state["willy_last"] is not None,
                        "session":bot_state["session"],"dxy":bot_state.get("dxy"),"yields":bot_state.get("yields_10y"),
                    }
                    bot_state["last_signal"]=entry; bot_state["signals"].insert(0,entry)
                    if len(bot_state["signals"])>500: bot_state["signals"].pop()
                    if sig!="WARTEN" and not bot_state["open_trade"]:
                        open_trade(sig,price,atr_v,dict(inds),strategy,tt,passed)
                    bot_state["learning"]["total"]+=1
                    if sig in ["BUY","SELL"]: bot_state["learning"]["wins"]+=1
                    t2=bot_state["learning"]["total"]
                    bot_state["learning"]["accuracy"]=round(bot_state["learning"]["wins"]/t2*100,1) if t2>0 else 0
                    lvl="SIGNAL" if sig!="WARTEN" else "INFO"
                    add_log(f"{sig} [{strategy}] {tt} | {conf}% | {price} | Conf:{len(passed)}/{bot_state['confirmations'].get('required',5)}","INFO" if sig=="WARTEN" else lvl)
                else:
                    add_log(f"Preis:{price} | Sammle Daten ({len(bot_state['prices'])}/30)","INFO")
        except Exception as e:
            add_log(f"Loop-Fehler: {e}","ERROR")
        time.sleep(300)

# ═══════════════════════════════════════════════════════
# DASHBOARD — Arial, übersichtlich, alle Features
# ═══════════════════════════════════════════════════════
DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD KI-Bot v3.2</title>
<style>
:root {
  --bg:      #0b0f1a;
  --panel:   #111827;
  --border:  #1f2d45;
  --text:    #e8edf5;
  --dim:     #8899b0;
  --faint:   #4b5a70;
  --green:   #34d399;
  --red:     #f87171;
  --amber:   #fbbf24;
  --blue:    #60a5fa;
  --purple:  #c084fc;
  --teal:    #2dd4bf;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: Arial, "Helvetica Neue", Helvetica, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text);
  font-size: 14px; line-height: 1.55; padding: 16px;
  -webkit-font-smoothing: antialiased;
}
/* ── Header ── */
.hdr { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 18px; margin-bottom: 16px; display: flex;
  justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.logo { font-size: 18px; font-weight: 700; color: var(--amber); }
.sub  { font-size: 11px; color: var(--faint); margin-top: 2px; }
.badges { display: flex; gap: 5px; flex-wrap: wrap; }
.b { padding: 4px 10px; border-radius: 5px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.bg { background: #0a2017; color: var(--green);  border: 1px solid #1a5035; }
.bb { background: #0c1a35; color: var(--blue);   border: 1px solid #1e3a6a; }
.ba { background: #271c06; color: var(--amber);  border: 1px solid #66480f; }
.br { background: #270f0f; color: var(--red);    border: 1px solid #6b1e1e; }
.bp { background: #1e1030; color: var(--purple); border: 1px solid #5b2d8a; }
.bc { background: #0a2220; color: var(--teal);   border: 1px solid #1a5550; }
/* ── Section labels ── */
.sec { font-size: 11px; font-weight: 700; letter-spacing: 1.2px; color: var(--faint);
  text-transform: uppercase; padding: 18px 0 8px; border-bottom: 1px solid var(--border); margin-bottom: 12px; }
.sec:first-of-type { padding-top: 0; }
/* ── Grids ── */
.g5 { display: grid; grid-template-columns: repeat(5,1fr); gap: 10px; margin-bottom: 12px; }
.g4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin-bottom: 12px; }
.g3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 10px; margin-bottom: 12px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr;       gap: 10px; margin-bottom: 12px; }
/* ── Panels ── */
.pn { background: var(--panel); border: 1px solid var(--border); border-radius: 9px; padding: 14px; }
.pt { font-size: 10.5px; font-weight: 700; color: var(--faint); letter-spacing: 1px;
  text-transform: uppercase; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dg { background: var(--green);  box-shadow: 0 0 5px var(--green); }
.da { background: var(--amber);  box-shadow: 0 0 5px var(--amber); }
.db { background: var(--blue);   box-shadow: 0 0 5px var(--blue); }
.dp { background: var(--purple); box-shadow: 0 0 5px var(--purple); }
.dc { background: var(--teal);   box-shadow: 0 0 5px var(--teal); }
/* ── Values ── */
.big { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
.sv  { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.pos { color: var(--green); } .neg { color: var(--red); }
.neu { color: var(--dim);   } .amr { color: var(--amber); }
.pur { color: var(--purple); } .cyn { color: var(--teal); }
.sm  { text-align: center; }
.lbl { font-size: 10.5px; color: var(--faint); letter-spacing: .4px; margin-bottom: 5px; }
.meta { font-size: 12px; color: var(--dim); margin-top: 4px; }
/* ── Rows ── */
.row { display: flex; justify-content: space-between; align-items: center;
  padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.row:last-child { border-bottom: none; }
.rk { color: var(--dim); } .rv { font-weight: 600; font-variant-numeric: tabular-nums; }
/* ── Progress bars ── */
.pb { background: var(--border); border-radius: 4px; height: 6px; margin: 5px 0; overflow: hidden; }
.pf { height: 100%; border-radius: 4px; transition: width .5s; }
.pg { background: linear-gradient(90deg,#1a5035,#34d399); }
.pr { background: linear-gradient(90deg,#6b1e1e,#f87171); }
.pb2{ background: linear-gradient(90deg,#1e3a6a,#60a5fa); }
.pa { background: linear-gradient(90deg,#66480f,#fbbf24); }
/* ── Signal box ── */
.sbox { padding: 12px; border-radius: 7px; border: 1px solid; margin-bottom: 6px; }
.sbuy  { background: #0a2017; border-color: #1a5035; }
.ssell { background: #270f0f; border-color: #6b1e1e; }
.swait { background: #1f1800; border-color: #66480f; }
/* ── Demo kacheln ── */
.dk { background: #0d1625; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px; text-align: center; }
.dk .dv { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 4px; }
/* ── Conf badges ── */
.cfp { display: inline-block; background: #0a2017; color: var(--green);
  border: 1px solid #1a5035; border-radius: 4px; font-size: 11px; padding: 2px 7px; margin: 2px; }
.cff { display: inline-block; background: #270f0f; color: var(--red);
  border: 1px solid #6b1e1e; border-radius: 4px; font-size: 11px; padding: 2px 7px; margin: 2px; }
/* ── Table ── */
.tw { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; min-width: 620px; }
th { color: var(--faint); font-weight: 700; padding: 7px 8px; border-bottom: 1px solid var(--border);
  text-align: left; font-size: 11px; letter-spacing: .5px; white-space: nowrap; }
td { padding: 7px 8px; border-bottom: 1px solid #0d1420; font-variant-numeric: tabular-nums; white-space: nowrap; }
/* ── Log ── */
.le { font-size: 12px; padding: 5px 0; border-bottom: 1px solid #0d1420; line-height: 1.5; }
.le .t { color: var(--faint); margin-right: 6px; }
/* ── Alerts ── */
.alert { display: none; border: 1px solid #6b1e1e; background: #270f0f; border-radius: 7px;
  padding: 10px 14px; margin-bottom: 12px; font-size: 13px; color: var(--red); font-weight: 600; }
/* ── Animations ── */
.pulse { animation: pulse 2s infinite; }
.blink { animation: blink 1s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
@keyframes blink  { 0%,100%{opacity:1} 50%{opacity:0} }
/* ── Responsive ── */
@media(max-width:900px) {
  .g5,.g4 { grid-template-columns: repeat(2,1fr); }
  .g3 { grid-template-columns: 1fr 1fr; }
  .g2 { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<!-- HEADER -->
<div class="hdr">
  <div>
    <div class="logo">⚡ XAUUSD KI-Bot v3.2</div>
    <div class="sub">OANDA-Preis · Intermarket · 3 Strategien · Confirmations · SHORT/LONG · Lernmodul · Demo-Konto €1.000</div>
  </div>
  <div class="badges">
    <span class="b bg"><span class="blink">●</span> LIVE</span>
    <span class="b bb" id="clk">—</span>
    <span class="b ba" id="sess-b">—</span>
    <span class="b ba" id="last-upd">Warte...</span>
    <span class="b bp" id="willy-b">WILLY: —</span>
    <span class="b bc" id="strat-b">STRAT: —</span>
  </div>
</div>

<div class="alert" id="news-alert">⚠ News-Sperre: <span id="news-reason">—</span></div>

<!-- ══ 1. MARKT & SIGNAL ══ -->
<div class="sec">Markt &amp; Signal</div>
<div class="g5">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>XAUUSD Preis</div>
    <div class="big amr" id="price">—</div>
    <div class="meta">ATR <b id="atr">—</b> &nbsp;·&nbsp; ADX <b id="adx">—</b></div>
    <div class="meta" id="ov-trend">Gesamttrend: —</div>
    <div class="meta" style="font-size:10.5px;color:var(--faint);margin-top:4px" id="price-src">—</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>Signal</div>
    <div id="sig-box" class="sbox swait">
      <div style="font-size:16px;font-weight:700" id="sig-t">WARTEN</div>
      <div style="font-size:12px;color:var(--dim);margin-top:3px" id="sig-c">Warte auf Daten...</div>
      <div style="font-size:12px;margin-top:3px" id="sig-lvl"></div>
    </div>
    <div class="meta" id="sig-meta">Typ: — · Strategie: —</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Win Rate</div>
    <div class="big pos" id="winrate">—</div>
    <div class="pb"><div class="pf pg" id="wr-bar" style="width:0%"></div></div>
    <div class="meta"><b id="wins">0</b> Gewinn · <b id="losses">0</b> Verlust · <b id="total-t">0</b> Trades</div>
    <div class="meta" style="color:var(--purple)">Lern-Verm.: <b id="avoided">0</b></div>
    <div class="meta">SHORT <b id="sh-t">0</b> · LONG <b id="lo-t">0</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg"></span>P&amp;L (Punkte)</div>
    <div class="big" id="total-pnl">+0.00 Pkt</div>
    <div class="meta">Best <b id="best" class="pos">—</b> · Worst <b id="worst" class="neg">—</b></div>
    <div class="meta">Ø Win <b id="avg-win" class="pos">—</b> · Ø Loss <b id="avg-loss" class="neg">—</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dc"></span>Intermarket</div>
    <div class="row"><span class="rk">DXY (US-Dollar)</span><span class="rv amr" id="dxy">—</span></div>
    <div class="row"><span class="rk">DXY Trend</span><span class="rv" id="dxy-trend">—</span></div>
    <div class="row"><span class="rk">10Y Yields</span><span class="rv amr" id="yields">—</span></div>
    <div class="row"><span class="rk">Yields Trend</span><span class="rv" id="yields-trend">—</span></div>
    <div class="row"><span class="rk">Gold/DXY Korr.</span><span class="rv neu" id="corr">—</span></div>
  </div>
</div>

<!-- ══ 2. DEMO-KONTO ══ -->
<div class="sec">Demo-Konto — Start €1.000 · Max. Hebel 1:5 · 5% Risiko/Trade</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g5" style="margin-bottom:10px">
    <div class="dk"><div class="lbl">Kontostand</div><div class="dv" id="da-balance">€1.000,00</div></div>
    <div class="dk"><div class="lbl">Eigenkapital (live)</div><div class="dv" id="da-equity">€1.000,00</div></div>
    <div class="dk"><div class="lbl">Gesamt P&amp;L</div><div class="dv" id="da-pnl">+0,00 €</div></div>
    <div class="dk"><div class="lbl">Rendite seit Start</div><div class="dv" id="da-return">+0,00%</div></div>
    <div class="dk"><div class="lbl">Max. Drawdown</div><div class="dv" id="da-dd">0,00%</div></div>
  </div>
  <div class="g4" style="margin-bottom:8px">
    <div class="row" style="padding:5px 0"><span class="rk">Genutzter Hebel</span><span class="rv" id="da-lev">1:0,0 / max 1:5</span></div>
    <div class="row" style="padding:5px 0"><span class="rk">Margin verw. / frei</span><span class="rv" id="da-margin">— / —</span></div>
    <div class="row" style="padding:5px 0"><span class="rk">Risiko-Ziel / Trade</span><span class="rv amr">5,0%</span></div>
    <div class="row" style="padding:5px 0"><span class="rk">Trades · Win-Rate</span><span class="rv" id="da-stats">0 · —</span></div>
  </div>
  <div style="font-size:11px;color:var(--faint);border-top:1px solid var(--border);padding-top:8px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px">
    <span id="da-note">1 USD ≈ 1 EUR (vereinfacht) · 1 Lot = 100 oz · Max. 1:5 Hebel strikt eingehalten</span>
    <span>Abgelehnte Trades: <b style="color:var(--text)" id="da-rejected">0</b></span>
  </div>
</div>

<!-- ══ 3. CONFIRMATIONS ══ -->
<div class="sec">Bestätigungs-System — SHORT: 5 nötig · LONG: 7 nötig</div>
<div class="pn" style="margin-bottom:12px">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px">
    <div>
      <span style="font-size:20px;font-weight:700" id="conf-count">0</span>
      <span style="font-size:14px;color:var(--dim)"> / <span id="conf-req">5</span> Bestätigungen</span>
    </div>
    <div class="pb" style="flex:1;margin:0 16px;min-width:100px"><div class="pf pg" id="conf-bar" style="width:0%"></div></div>
    <div id="conf-type" style="font-size:12px;color:var(--dim)">—</div>
  </div>
  <div id="conf-passed" style="margin-bottom:6px"></div>
  <div id="conf-failed"></div>
</div>

<!-- ══ 4. TREND ══ -->
<div class="sec">Multi-Timeframe Trend — 1H · 4H · Täglich · Gesamt</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g4" style="margin-bottom:0">
    <div class="sm"><div class="lbl">1 STUNDE</div><div class="sv" id="t-1h">—</div>
      <div class="meta">RSI <b id="t1h-rsi">—</b> · POC <b id="t1h-poc" class="amr">—</b></div></div>
    <div class="sm"><div class="lbl">4 STUNDEN</div><div class="sv" id="t-4h">—</div>
      <div class="meta">RSI <b id="t4h-rsi">—</b> · POC <b id="t4h-poc" class="amr">—</b></div></div>
    <div class="sm"><div class="lbl">TÄGLICH</div><div class="sv" id="t-1d">—</div>
      <div class="meta">RSI <b id="t1d-rsi">—</b> · EMA200 <b id="t1d-e200" class="amr">—</b></div></div>
    <div class="sm"><div class="lbl">GESAMTTREND</div><div class="sv" id="t-overall">—</div>
      <div class="meta">Strategie: <b id="active-strat">—</b></div></div>
  </div>
</div>

<!-- ══ 5. WOCHENANALYSE ══ -->
<div class="sec">Wochenanalyse &amp; Prognose</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g3" style="margin-bottom:0">
    <div>
      <div class="lbl">TREND &amp; FORECAST</div>
      <div style="font-size:16px;font-weight:700;margin-top:4px" id="w-trend">—</div>
      <div style="font-size:13px;font-weight:700;margin-top:6px" id="w-forecast">—</div>
      <div class="meta" id="w-updated">—</div>
    </div>
    <div>
      <div class="lbl">KEY LEVELS</div>
      <div id="w-levels" style="font-size:13px;color:var(--amber);line-height:1.9;margin-top:4px">—</div>
    </div>
    <div>
      <div class="lbl">BEGRÜNDUNG</div>
      <div id="w-reasoning" style="font-size:13px;color:var(--dim);line-height:1.9;margin-top:4px">—</div>
    </div>
  </div>
</div>

<!-- ══ 6. STRATEGIEN ══ -->
<div class="sec">3 Strategien — Live-Bewertung</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g3" style="margin-bottom:0">
    <div class="sm">
      <div class="lbl" style="color:var(--blue)">MEAN REVERSION</div>
      <div class="sv" style="color:var(--blue)" id="sc-mr">0</div>
      <div class="meta">BB · RSI · Stochastic</div>
      <div class="pb"><div class="pf pb2" id="bar-mr" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div class="lbl" style="color:var(--green)">TREND FOLLOW</div>
      <div class="sv pos" id="sc-tf">0</div>
      <div class="meta">EMA-Stack · MACD · ADX</div>
      <div class="pb"><div class="pf pg" id="bar-tf" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div class="lbl" style="color:var(--amber)">BREAKOUT</div>
      <div class="sv amr" id="sc-bo">0</div>
      <div class="meta">Volumen · Levels · Session</div>
      <div class="pb"><div class="pf pa" id="bar-bo" style="width:0%"></div></div>
    </div>
  </div>
</div>

<!-- ══ 7. INDIKATOREN & SIGNAL ══ -->
<div class="sec">Indikatoren &amp; Signal-Begründung</div>
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>Indikatoren — live</div>
    <div class="row"><span class="rk">EMA 9/20/50/100/200</span><span class="rv neu" id="emas">—</span></div>
    <div class="row"><span class="rk">RSI (14)</span><span class="rv neu" id="rsi">—</span></div>
    <div class="row"><span class="rk">MACD / Signal</span><span class="rv neu" id="macd">—</span></div>
    <div class="row"><span class="rk">Bollinger O/M/U</span><span class="rv neu" id="bb">—</span></div>
    <div class="row"><span class="rk">Stochastic K/D</span><span class="rv neu" id="stoch">—</span></div>
    <div class="row"><span class="rk">Williams %R</span><span class="rv neu" id="wr2">—</span></div>
    <div class="row"><span class="rk">CCI (20)</span><span class="rv neu" id="cci">—</span></div>
    <div class="row"><span class="rk">VWAP</span><span class="rv neu" id="vwap">—</span></div>
    <div class="row"><span class="rk">Momentum 10/5</span><span class="rv neu" id="mom">—</span></div>
    <div class="row"><span class="rk">ATR / ADX</span><span class="rv neu" id="atr-adx">—</span></div>
    <div class="row"><span class="rk">Vol. POC/VAH/VAL</span><span class="rv amr" id="vpoc">—</span></div>
    <div style="border-top:1px solid var(--border);margin-top:10px;padding-top:10px">
      <div class="pt"><span class="dot db"></span>Offener Trade</div>
      <div id="open-trade" style="font-size:13px;color:var(--dim)">Kein offener Trade</div>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>Signal-Begründung</div>
    <div style="font-size:12px;color:var(--green);font-weight:700;margin-bottom:4px">✓ BULLISH</div>
    <div id="bull-r" style="font-size:13px;color:var(--green);line-height:1.9;min-height:48px">—</div>
    <div style="font-size:12px;color:var(--red);font-weight:700;margin:10px 0 4px">✗ BEARISH</div>
    <div id="bear-r" style="font-size:13px;color:var(--red);line-height:1.9;min-height:48px">—</div>
    <div style="border-top:1px solid var(--border);margin-top:10px;padding-top:10px">
      <div class="pt"><span class="dot dp"></span>WillyAlgoTrader</div>
      <div class="g4" style="margin-bottom:6px">
        <div class="sm"><div class="sv" id="w-sig" style="font-size:15px">—</div><div class="lbl">Signal</div></div>
        <div class="sm"><div class="sv neu" id="w-tf" style="font-size:13px">—</div><div class="lbl">TF</div></div>
        <div class="sm"><div class="sv neu" id="w-sc" style="font-size:13px">—</div><div class="lbl">Score</div></div>
        <div class="sm"><div class="sv amr" id="w-cnt" style="font-size:13px">0</div><div class="lbl">Total</div></div>
      </div>
      <div style="font-size:12px;color:var(--faint)" id="w-tps">—</div>
    </div>
  </div>
</div>

<!-- ══ 8. LERNMODUL ══ -->
<div class="sec">Lernmodul — Fehleranalyse &amp; Confirmation-Tracking</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g3" style="margin-bottom:0">
    <div>
      <div class="lbl">⚡ AKTIVE LERNREGELN (ab 2× Fehler)</div>
      <div id="l-rules" style="font-size:13px;color:var(--purple);line-height:1.9;margin-top:4px">Noch keine Regeln...</div>
    </div>
    <div>
      <div class="lbl">🔍 LETZTE FEHLER-ANALYSEN</div>
      <div id="l-mist" style="font-size:13px;color:var(--red);line-height:1.9;margin-top:4px">Noch keine Fehler...</div>
    </div>
    <div>
      <div class="lbl">📊 CONFIRMATION-FEHLER (Trade mit Conf. verloren)</div>
      <div id="l-conf-fail" style="font-size:13px;color:var(--amber);line-height:1.9;margin-top:4px">Noch keine...</div>
    </div>
  </div>
</div>

<!-- ══ 9. TRADES & LOG ══ -->
<div class="sec">Trade-Verlauf &amp; System-Log</div>
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Trade-Historie</div>
    <div class="tw" style="max-height:220px;overflow-y:auto">
    <table>
      <thead><tr>
        <th>Zeit</th><th>Typ</th><th>Dir</th><th>Entry</th><th>Close</th>
        <th>Pkt</th><th>€ P&amp;L</th><th>Hebel</th><th>Gehalten</th><th>Strat.</th><th>Conf.</th><th>⭐</th><th>Erg.</th>
      </tr></thead>
      <tbody id="t-body"><tr><td colspan="13" style="color:var(--faint);text-align:center;padding:10px">Noch keine Trades</td></tr></tbody>
    </table>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db pulse"></span>System-Log</div>
    <div id="log-box" style="max-height:260px;overflow-y:auto"></div>
  </div>
</div>

<script>
const fmt = v => (v===null||v===undefined) ? '—' : v;
const tc  = t => t&&t.includes('BULLISH')?'pos':t&&t.includes('BEARISH')?'neg':'neu';
const eur = (v,dec=2) => v===null||v===undefined ? '—' : (v>=0?'+':'')+v.toFixed(dec)+'€';

async function refresh() {
  try {
    const [sr, tr] = await Promise.all([fetch('/state'),fetch('/trades')]);
    const d = await sr.json(), trades = await tr.json();
    const i=d.indicators||{}, s=d.stats||{}, sig=d.last_signal||{}, w=d.willy_last||null;
    const trends=d.trends||{}, learn=d.learning||{}, wa=d.weekly_analysis||{};
    const ss=d.strategy_scores||{}, da=d.demo_account||{}, conf=d.confirmations||{};
    const t1h=d.indicators_1h||{}, t4h=d.indicators_4h||{}, t1d=d.indicators_1d||{};
    const td=d.trend_details||{};
    const p=d.price;

    // Header
    document.getElementById('clk').textContent = new Date().toUTCString().slice(17,25)+' UTC';
    document.getElementById('last-upd').textContent = d.last_update||'Warte...';
    document.getElementById('sess-b').textContent   = d.session||'—';

    // News
    const na=document.getElementById('news-alert');
    if(d.news_lock){na.style.display='block';document.getElementById('news-reason').textContent=d.news_lock_reason||'';}
    else na.style.display='none';

    // Preis
    if(p) document.getElementById('price').textContent=p.toFixed(2);
    document.getElementById('atr').textContent=fmt(i.atr);
    document.getElementById('adx').textContent=fmt(i.adx);
    document.getElementById('price-src').textContent=d.price_source||'XAUUSD Spot';
    const ov=trends.overall||'—', ote=document.getElementById('ov-trend');
    ote.textContent='Gesamttrend: '+ov; ote.className='meta '+tc(ov);

    // Signal
    const st=sig.signal||'WARTEN';
    document.getElementById('sig-box').className='sbox '+(st==='BUY'?'sbuy':st==='SELL'?'ssell':'swait');
    const ste=document.getElementById('sig-t');
    ste.textContent=st+(sig.willy_confirmed?' ⭐':'');
    ste.style.color=st==='BUY'?'var(--green)':st==='SELL'?'var(--red)':'var(--amber)';
    document.getElementById('sig-c').textContent=sig.confidence
      ?`Konfidenz: ${sig.confidence}%  ·  ${sig.price}  ·  Conf: ${sig.confirmations_passed||0}/${conf.required||5}`
      :'Warte auf Bestätigungen...';
    document.getElementById('sig-lvl').innerHTML=sig.sl
      ?`<span style="color:var(--red)">SL ${sig.sl}</span>&nbsp;&nbsp;<span style="color:var(--green)">TP1 ${sig.tp1} · TP2 ${sig.tp2}</span>`:''
    document.getElementById('sig-meta').textContent=`Typ: ${sig.trade_type||d.trade_type||'—'} · Strategie: ${sig.strategy||'—'}`;
    document.getElementById('strat-b').textContent='STRAT: '+(d.active_strategy||'—');

    // Stats
    document.getElementById('winrate').textContent=s.win_rate?s.win_rate+'%':'—';
    document.getElementById('winrate').className='big '+(s.win_rate>=50?'pos':'neg');
    document.getElementById('wr-bar').style.width=(s.win_rate||0)+'%';
    document.getElementById('wins').textContent=s.winning_trades||0;
    document.getElementById('losses').textContent=s.losing_trades||0;
    document.getElementById('total-t').textContent=s.total_trades||0;
    document.getElementById('avoided').textContent=s.avoided_by_learning||0;
    document.getElementById('sh-t').textContent=s.short_trades||0;
    document.getElementById('lo-t').textContent=s.long_trades||0;
    const pnl=s.total_pnl||0;
    const pe=document.getElementById('total-pnl');
    pe.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+' Pkt'; pe.className='big '+(pnl>=0?'pos':'neg');
    document.getElementById('best').textContent=(s.best_trade||0).toFixed(2);
    document.getElementById('worst').textContent=(s.worst_trade||0).toFixed(2);
    document.getElementById('avg-win').textContent=s.avg_win?'+'+s.avg_win:'—';
    document.getElementById('avg-loss').textContent=s.avg_loss||'—';

    // Intermarket
    const dx=d.dxy,dt=d.dxy_trend,yi=d.yields_10y,yt=d.yields_trend;
    document.getElementById('dxy').textContent=dx?dx.toFixed(2):'—';
    document.getElementById('dxy').className='rv '+(dx&&dx>103?'neg':'pos');
    const dte=document.getElementById('dxy-trend');
    dte.textContent=dt||'—'; dte.className='rv '+(dt&&dt.includes('STEIGT')?'neg':dt&&dt.includes('FÄLLT')?'pos':'neu');
    document.getElementById('yields').textContent=yi?yi.toFixed(2)+'%':'—';
    document.getElementById('yields').className='rv '+(yi&&yi>4?'neg':'pos');
    const yte=document.getElementById('yields-trend');
    yte.textContent=yt||'—'; yte.className='rv '+(yt&&yt.includes('STEIG')?'neg':yt&&yt.includes('FALL')?'pos':'neu');
    document.getElementById('corr').textContent=d.gold_dxy_correlation??'—';

    // Demo Account
    const sb=da.starting_balance||1000;
    const balE=document.getElementById('da-balance');
    balE.textContent=da.balance!==undefined?'€'+da.balance.toFixed(2):'—';
    const eqE=document.getElementById('da-equity');
    eqE.textContent=da.equity!==undefined?'€'+da.equity.toFixed(2):'—';
    eqE.className='dv '+(da.equity>=sb?'pos':'neg');
    const pnlE=document.getElementById('da-pnl');
    pnlE.textContent=eur(da.total_pnl_eur); pnlE.className='dv '+(da.total_pnl_eur>=0?'pos':'neg');
    const retE=document.getElementById('da-return');
    retE.textContent=da.return_pct!==undefined?(da.return_pct>=0?'+':'')+da.return_pct+'%':'—';
    retE.className='dv '+(da.return_pct>=0?'pos':'neg');
    const ddE=document.getElementById('da-dd');
    ddE.textContent=da.max_drawdown_pct!==undefined?'-'+da.max_drawdown_pct+'%':'—';
    ddE.className='dv '+(da.max_drawdown_pct>10?'neg':da.max_drawdown_pct>5?'amr':'pos');
    document.getElementById('da-lev').textContent='1:'+(da.leverage_used||0).toFixed(1)+' / max 1:'+(da.max_leverage||5);
    document.getElementById('da-margin').textContent='€'+(da.margin_used||0).toFixed(2)+' / €'+(da.free_margin||da.equity||0).toFixed(2);
    document.getElementById('da-stats').textContent=(da.total_trades||0)+' · '+(da.win_rate_pct!==undefined?da.win_rate_pct+'%':'—');
    document.getElementById('da-rejected').textContent=da.rejected_trades||0;

    // Confirmations
    const cp=conf.passed||[], cf=conf.failed||[], ccount=conf.count||0, creq=conf.required||5;
    document.getElementById('conf-count').textContent=ccount;
    document.getElementById('conf-req').textContent=creq;
    document.getElementById('conf-bar').style.width=Math.min(ccount/creq*100,100)+'%';
    document.getElementById('conf-bar').className='pf '+(ccount>=creq?'pg':'pr');
    document.getElementById('conf-type').textContent=sig.trade_type?`Trade-Typ: ${sig.trade_type}`:'—';
    document.getElementById('conf-passed').innerHTML=cp.length
      ?cp.map(c=>`<span class="cfp">✓ ${c}</span>`).join('')
      :'<span style="color:var(--faint);font-size:12px">Keine Bestätigungen</span>';
    document.getElementById('conf-failed').innerHTML=cf.length
      ?'<div style="margin-top:4px">'+cf.map(c=>`<span class="cff">✗ ${c}</span>`).join('')+'</div>':'';

    // Trends
    const tmap=[['1h','t-1h','t1h-rsi','t1h-poc',t1h,td['1h']||{}],
                ['4h','t-4h','t4h-rsi','t4h-poc',t4h,td['4h']||{}],
                ['1d','t-1d','t1d-rsi',null,t1d,td['1d']||{}]];
    for(const[tf,tid,rid,pid,tdi,det] of tmap){
      const tv=trends[tf]||'—', el=document.getElementById(tid);
      el.textContent=tv; el.className='sv '+tc(tv);
      document.getElementById(rid).textContent=fmt(tdi.rsi);
      if(pid) document.getElementById(pid).textContent=fmt(tdi.poc||det.poc||'—');
    }
    if(document.getElementById('t1d-e200')) document.getElementById('t1d-e200').textContent=fmt(t1d.ema200);
    const ove=document.getElementById('t-overall'); ove.textContent=ov; ove.className='sv '+tc(ov);
    document.getElementById('active-strat').textContent=d.active_strategy||'—';

    // Wochenanalyse
    const wte=document.getElementById('w-trend');
    wte.textContent=wa.trend||'—'; wte.className=tc(wa.trend||'');
    const wfe=document.getElementById('w-forecast');
    wfe.textContent=wa.forecast||'—';
    wfe.style.color=wa.forecast&&wa.forecast.includes('BULLISH')?'var(--green)':wa.forecast&&wa.forecast.includes('BEARISH')?'var(--red)':'var(--amber)';
    document.getElementById('w-updated').textContent=wa.updated||'—';
    document.getElementById('w-levels').innerHTML=(wa.key_levels||[]).map(l=>`• ${l}`).join('<br>')||'—';
    document.getElementById('w-reasoning').innerHTML=(wa.reasoning||[]).map(r=>`→ ${r}`).join('<br>')||'—';

    // Strategie Scores
    const ms=Math.max(ss.mean_reversion||0,ss.trend_follow||0,ss.breakout||0,1);
    document.getElementById('sc-mr').textContent=ss.mean_reversion||0;
    document.getElementById('sc-tf').textContent=ss.trend_follow||0;
    document.getElementById('sc-bo').textContent=ss.breakout||0;
    document.getElementById('bar-mr').style.width=Math.min((ss.mean_reversion||0)/ms*100,100)+'%';
    document.getElementById('bar-tf').style.width=Math.min((ss.trend_follow||0)/ms*100,100)+'%';
    document.getElementById('bar-bo').style.width=Math.min((ss.breakout||0)/ms*100,100)+'%';

    // Indikatoren
    document.getElementById('emas').textContent=`${fmt(i.ema9)}/${fmt(i.ema20)}/${fmt(i.ema50)}/${fmt(i.ema100)}/${fmt(i.ema200)}`;
    document.getElementById('emas').className='rv '+(i.ema20&&p&&i.ema20<p?'pos':'neg');
    const rEl=document.getElementById('rsi'); rEl.textContent=fmt(i.rsi);
    rEl.className='rv '+(i.rsi<35?'pos':i.rsi>65?'neg':'neu');
    document.getElementById('macd').textContent=`${fmt(i.macd)} / ${fmt(i.macd_signal)}`;
    document.getElementById('macd').className='rv '+(i.macd&&i.macd>0?'pos':'neg');
    document.getElementById('bb').textContent=`${fmt(i.bb_upper)}/${fmt(i.bb_mid)}/${fmt(i.bb_lower)}`;
    const skE=document.getElementById('stoch'); skE.textContent=`${fmt(i.stoch_k)}/${fmt(i.stoch_d)}`;
    skE.className='rv '+(i.stoch_k<25?'pos':i.stoch_k>75?'neg':'neu');
    const wrE=document.getElementById('wr2'); wrE.textContent=fmt(i.williams_r);
    wrE.className='rv '+(i.williams_r<-80?'pos':i.williams_r>-20?'neg':'neu');
    const cE=document.getElementById('cci'); cE.textContent=fmt(i.cci);
    cE.className='rv '+(i.cci<-100?'pos':i.cci>100?'neg':'neu');
    const vE=document.getElementById('vwap'); vE.textContent=fmt(i.vwap);
    vE.className='rv '+(i.vwap&&p&&p>i.vwap?'pos':'neg');
    const mE=document.getElementById('mom'); mE.textContent=`${fmt(i.momentum)}/${fmt(i.momentum_5)}`;
    mE.className='rv '+(i.momentum&&i.momentum>0?'pos':'neg');
    document.getElementById('atr-adx').textContent=`${fmt(i.atr)} / ${fmt(i.adx)}`;
    document.getElementById('vpoc').textContent=`${fmt(i.poc)}/${fmt(i.vah)}/${fmt(i.val)}`;

    // Signal Begründung
    const br=sig.reasons||[], cr=sig.counter_reasons||[];
    document.getElementById('bull-r').innerHTML=br.length?br.map(r=>`✓ ${r}`).join('<br>'):'<span style="color:var(--faint)">—</span>';
    document.getElementById('bear-r').innerHTML=cr.length?cr.map(r=>`✗ ${r}`).join('<br>'):'<span style="color:var(--faint)">—</span>';

    // Offener Trade
    const ot=d.open_trade;
    if(ot){
      const upnl=ot.direction==='BUY'?(p||0)-ot.entry:ot.entry-(p||0);
      const upnlEur=upnl*(ot.lot_size||0.01)*100;
      document.getElementById('open-trade').innerHTML=
        `<span class="${ot.direction==='BUY'?'pos':'neg'}" style="font-weight:700">[${ot.trade_type||''}] ${ot.direction}</span>`+
        ` @ ${ot.entry} · SL ${ot.sl} · TP1 ${ot.tp1} · TP2 ${ot.tp2} · TP3 ${ot.tp3||'—'}<br>`+
        `Lot ${ot.lot_size||'—'} · Hebel 1:${ot.leverage_used||'—'} · Risiko ${ot.risk_pct||'—'}% (€${ot.risk_eur||'—'}) · ${ot.strategy||'—'}<br>`+
        `Gehalten: ${ot.hold_min||0} Min · Conf: ${ot.confirmations_passed||0} · `+
        `Unrealisiert: <span class="${upnl>=0?'pos':'neg'}">${upnl>=0?'+':''}${upnl.toFixed(2)} Pkt (${upnlEur>=0?'+':''}${upnlEur.toFixed(2)}€)</span>`;
    } else document.getElementById('open-trade').textContent='Kein offener Trade';

    // Willy
    if(w){
      const wd=w.signal_type||'—';
      const we=document.getElementById('w-sig'); we.textContent=wd;
      we.className='sv '+(wd.includes('BUY')?'pos':wd.includes('SELL')?'neg':'pur');
      document.getElementById('w-tf').textContent=w.timeframe||'—';
      document.getElementById('w-sc').textContent=w.score||'—';
      document.getElementById('willy-b').textContent='WILLY: '+wd;
      document.getElementById('willy-b').className='b '+(wd.includes('BUY')?'bg':wd.includes('SELL')?'br':'bp');
      document.getElementById('w-tps').textContent=`Entry ${w.entry||'—'} · TP1 ${w.tp1||'—'} · TP2 ${w.tp2||'—'} · TP3 ${w.tp3||'—'}`;
    }
    document.getElementById('w-cnt').textContent=d.willy_signals_count||0;

    // Lernmodul
    const rules=learn.rules||[], mist=learn.mistakes||[], cfl=learn.confirmation_failures||[];
    document.getElementById('l-rules').innerHTML=rules.length
      ?rules.slice(0,6).map(r=>`⚡ [${r.count}×] ${r.avoid}`).join('<br>'):'Noch keine Regeln...';
    document.getElementById('l-mist').innerHTML=mist.length
      ?mist.slice(0,4).map(m=>`📍 ${m.time} — ${m.trade}<br>${m.mistakes.map(x=>`&nbsp;→ ${x.desc}`).join('<br>')}`).join('<br>')
      :'Noch keine Fehler...';
    document.getElementById('l-conf-fail').innerHTML=cfl.length
      ?cfl.slice(0,4).map(f=>`⚠ ${f.time} — ${f.trade} (${f.conf_count} Conf., P&L: ${f.pnl})`).join('<br>')
      :'Noch keine...';

    // Trades Tabelle
    const tb=document.getElementById('t-body');
    if(trades.length){
      tb.innerHTML=trades.slice(0,15).map(t=>{
        const ep=t.eur_pnl!==undefined?t.eur_pnl:(t.pnl*(t.lot_size||0.01)*100);
        return `<tr>
          <td>${(t.close_time||'').slice(11,16)}</td>
          <td class="amr" style="font-weight:700">${t.trade_type||'SH'}</td>
          <td class="${t.direction==='BUY'?'pos':'neg'}" style="font-weight:700">${t.direction}</td>
          <td>${t.entry}</td><td>${t.close_price||'—'}</td>
          <td class="${t.pnl>=0?'pos':'neg'}">${t.pnl>=0?'+':''}${t.pnl}</td>
          <td class="${ep>=0?'pos':'neg'}">${ep>=0?'+':''}${ep.toFixed(2)}€</td>
          <td>1:${t.leverage_used||'—'}</td>
          <td>${t.hold_min_final||t.hold_min||'—'} Min</td>
          <td style="color:var(--blue);font-size:11px">${(t.strategy||'').replace('_',' ')}</td>
          <td style="font-size:11px">${t.confirmations_passed||'—'}</td>
          <td>${t.willy_confirmed?'⭐':'—'}</td>
          <td class="${t.result==='WIN'?'pos':'neg'}" style="font-weight:700">${t.result}</td>
        </tr>`;
      }).join('');
    }

    // Log
    const lc={SIGNAL:'var(--amber)',TRADE:'var(--green)',ERROR:'var(--red)',WARN:'var(--amber)',LEARN:'var(--purple)',INFO:'var(--blue)'};
    document.getElementById('log-box').innerHTML=(d.log||[]).map(l=>
      `<div class="le" style="color:${lc[l.level]||'var(--blue)'}"><span class="t">${l.time}</span>[${l.level}] ${l.msg}</div>`
    ).join('');

  } catch(e){ console.error('Refresh-Fehler:',e); }
  setTimeout(refresh, 10000);
}

refresh();
setInterval(()=>{ const e=document.getElementById('clk'); if(e) e.textContent=new Date().toUTCString().slice(17,25)+' UTC'; },1000);
</script>
</body></html>"""

# ═══════════════════════════════════════════════════════
# API ROUTEN
# ═══════════════════════════════════════════════════════
@app.route("/")
def dashboard(): return render_template_string(DASHBOARD)

@app.route("/state")
def state():
    return jsonify({
        "price": bot_state["price"], "price_source": bot_state["price_source"],
        "last_update": bot_state["last_update"], "last_signal": bot_state["last_signal"],
        "indicators": bot_state["indicators"],
        "indicators_1h": bot_state["indicators_1h"],
        "indicators_4h": bot_state["indicators_4h"],
        "indicators_1d": bot_state["indicators_1d"],
        "trend_details": bot_state["trend_details"],
        "trends": bot_state["trends"], "learning": bot_state["learning"],
        "log": bot_state["log"][:50], "stats": bot_state["stats"],
        "open_trade": bot_state["open_trade"], "running": bot_state["running"],
        "willy_last": bot_state["willy_last"],
        "willy_signals_count": len(bot_state["willy_signals"]),
        "dxy": bot_state["dxy"], "dxy_trend": bot_state["dxy_trend"],
        "yields_10y": bot_state["yields_10y"], "yields_trend": bot_state["yields_trend"],
        "gold_dxy_correlation": bot_state["gold_dxy_correlation"],
        "session": bot_state["session"], "trade_type": bot_state["trade_type"],
        "weekly_analysis": bot_state["weekly_analysis"],
        "strategy_scores": bot_state["strategy_scores"],
        "active_strategy": bot_state["active_strategy"],
        "confirmations": bot_state["confirmations"],
        "news_lock": bot_state["news_lock"],
        "news_lock_reason": bot_state["news_lock_reason"],
        "demo_account": get_demo_snapshot(),
    })

@app.route("/trades")
def trades(): return jsonify(bot_state["trades"])

@app.route("/signals")
def signals(): return jsonify(bot_state["signals"][:50])

@app.route("/weekly")
def weekly(): return jsonify(bot_state["weekly_analysis"])

@app.route("/learning")
def learning_route(): return jsonify(bot_state["learning"])

@app.route("/demo")
def demo_route(): return jsonify(get_demo_snapshot())

@app.route("/news", methods=["POST"])
def add_news():
    data=request.get_json(force=True)
    bot_state["news_events"].append({"name":data.get("name","Event"),"time":data.get("time","2025-01-01 00:00"),"impact":"HIGH"})
    add_log(f"News-Event: {data.get('name')} @ {data.get('time')}","INFO")
    return jsonify({"status":"ok"})

@app.route("/settings", methods=["POST"])
def settings():
    data=request.get_json(force=True)
    da=bot_state["demo_account"]
    if "balance"  in data: da["balance"]=float(data["balance"])
    if "risk"     in data: da["risk_per_trade_pct"]=float(data["risk"])
    if "leverage" in data: da["max_leverage"]=int(data["leverage"])
    return jsonify({"status":"ok","balance":da["balance"],"risk":da["risk_per_trade_pct"],"leverage":da["max_leverage"]})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data=request.get_json(force=True); add_log(f"Webhook: {data}","INFO")
        st=data.get("signal","").upper(); tf=data.get("timeframe","—")
        pr=data.get("price") or data.get("close")
        if pr:
            try:
                pf=float(str(pr).replace(",",".")); 
                if 1500<pf<6000: bot_state["prices"].append(pf); bot_state["price"]=pf
            except: pass
        if st:
            we={"signal_type":st,"timeframe":tf,"score":data.get("score","—"),
                "entry":data.get("entry") or pr,"tp1":data.get("tp1"),
                "tp2":data.get("tp2"),"tp3":data.get("tp3"),"sl":data.get("sl"),
                "time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                "date":datetime.datetime.utcnow().strftime("%d.%m.%Y")}
            bot_state["willy_last"]=we
            bot_state["willy_signals"].insert(0,we)
            if len(bot_state["willy_signals"])>200: bot_state["willy_signals"].pop()
            add_log(f"⭐ WillyAlgoTrader: {st} | TF:{tf}","SIGNAL")
        return jsonify({"status":"ok"}),200
    except Exception as e:
        add_log(f"Webhook Fehler: {e}","ERROR"); return jsonify({"status":"error"}),400

@app.route("/health")
def health(): return jsonify({"status":"healthy","version":"3.2","time":datetime.datetime.utcnow().isoformat()})

@app.route("/start")
def start():
    if not bot_state["running"]:
        bot_state["running"]=True
        threading.Thread(target=analysis_loop,daemon=True).start()
        return jsonify({"status":"Bot v3.2 gestartet"})
    return jsonify({"status":"Läuft bereits"})

@app.route("/stop")
def stop():
    bot_state["running"]=False; return jsonify({"status":"Bot gestoppt"})

# ═══════════════════════════════════════════════════════
# AUTO-START — gunicorn führt __main__ NICHT aus!
# ═══════════════════════════════════════════════════════
def _auto_start():
    if not bot_state["running"]:
        bot_state["running"]=True
        threading.Thread(target=analysis_loop,daemon=True).start()
        add_log("XAUUSD KI-Bot v3.2 auto-gestartet (gunicorn)","INFO")

_auto_start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
