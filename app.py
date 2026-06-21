from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import datetime, threading, time, math, json, urllib.request, random

app = Flask(__name__)
CORS(app)

# ═══════════════════════════════════════════════════════
# GLOBALER ZUSTAND v4.0
# ═══════════════════════════════════════════════════════
def _def_strat_stats():
    return {"trades":0,"wins":0,"losses":0,"pnl":0.0,"eur_pnl":0.0,"best":0.0,"worst":0.0,"win_rate":0.0}

bot_state = {
    "price":None,"prices":[],"price_source":"XAUUSD Spot (Yahoo Finance ~ OANDA Referenzpreis)",
    "candles":{},
    "dxy":None,"dxy_prices":[],"dxy_prev":None,"dxy_trend":"—",
    "yields_10y":None,"yields_prev":None,"yields_trend":"—",
    "gold_dxy_correlation":None,
    "signals":[],"last_signal":None,"last_update":None,
    "indicators":{},"indicators_1h":{},"indicators_4h":{},"indicators_1d":{},
    "trends":{"1h":"—","4h":"—","1d":"—","overall":"—"},
    "trend_details":{"1h":{},"4h":{},"1d":{}},
    "active_strategy":"—",
    "strategy_scores":{"mean_reversion":0,"trend_follow":0,"breakout":0,"macro_structure":0},
    "confirmations":{"passed":[],"failed":[],"count":0,"required":5},
    "session":"—",
    "weekly_analysis":{"trend":"—","forecast":"—","key_levels":[],"reasoning":[],"updated":"—"},
    "news_events":[],"news_lock":False,"news_lock_reason":"",
    "trade_type":"SHORT",
    "running":False,"log":[],
    "trades":[],"open_trade":None,
    "willy_signals":[],"willy_last":None,
    # ─── WillyAlgoTrader Analyse & Win-Rate Tracking ───
    "willy_analytics":{
        "open_signals":[],       # Offene Signale (warten auf Ergebnis)
        "closed_signals":[],     # Abgeschlossene Signale (max 500)
        "by_direction":{         # Win-Rate nach Richtung
            "BUY": {"count":0,"wins":0,"losses":0,"pending":0,"win_rate":0.0,"tp1":0,"tp2":0,"tp3":0},
            "SELL":{"count":0,"wins":0,"losses":0,"pending":0,"win_rate":0.0,"tp1":0,"tp2":0,"tp3":0},
        },
        "by_tf":{},              # Win-Rate nach Timeframe: {"15m":{count,wins,...}}
        "by_score":{},           # Win-Rate nach Score-Qualität
        "total":0,"wins":0,"losses":0,"pending":0,
        "overall_win_rate":0.0,
        "tp1_hits":0,"tp2_hits":0,"tp3_hits":0,"sl_hits":0,
        "avg_pips_win":0.0,"avg_pips_loss":0.0,
        "best_signal_type":"—","worst_signal_type":"—",
    },
    "learning":{
        "total":0,"wins":0,"accuracy":0.0,"cycle":0,
        "mistakes":[],"rules":[],"avoided_trades":0,"confirmation_failures":[],
    },
    "stats":{
        "total_signals":0,"buy_signals":0,"sell_signals":0,
        "total_trades":0,"winning_trades":0,"losing_trades":0,
        "total_pnl":0.0,"best_trade":0.0,"worst_trade":0.0,
        "win_rate":0.0,"avg_win":0.0,"avg_loss":0.0,
        "avoided_by_learning":0,"short_trades":0,"long_trades":0,"rejected_by_risk":0,
    },
    # ─── Pro-Strategie P&L ───
    "strategy_stats":{
        "MEAN_REVERSION":  _def_strat_stats(),
        "TREND_FOLLOW":    _def_strat_stats(),
        "BREAKOUT":        _def_strat_stats(),
        "MACRO_STRUCTURE": _def_strat_stats(),
    },
    # ─── Neue Macro-Struktur Analyse ───
    "macro_state":{
        "bias":"NEUTRAL","bias_score":0,"bias_notes":[],
        "market_structure":"UNDEFINED","structure_notes":[],
        "setup_type":None,"size_multiplier":1.0,"last_updated":"—",
    },
    # ─── Guardrails (Spec Abschnitt 5) ───
    "guardrails":{
        "status":"OK","daily_drawdown_pct":0.0,"weekly_drawdown_pct":0.0,
        "daily_start_balance":1000.0,"weekly_start_balance":1000.0,
        "daily_pnl_eur":0.0,"weekly_pnl_eur":0.0,
        "last_reset_daily":"","last_reset_weekly":"",
        "triggered":[],
    },
    # ─── Performance-Metriken (Spec Abschnitt 6.1) ───
    "performance":{
        "expectancy":0.0,"profit_factor":0.0,"avg_crv":0.0,"sharpe":0.0,
    },
    # ─── Smart Money Concepts (SMC) / Institutionelle Analyse ───
    "smc":{
        "order_blocks":[],          # Bullish & Bearish Order Blocks
        "liquidity_zones":[],       # BSL/SSL, Equal Highs/Lows, Round Numbers
        "fair_value_gaps":[],       # Bullish & Bearish FVGs
        "bos_choch":{},             # Break of Structure / Change of Character
        "premium_discount":{},      # Premium/Discount/Equilibrium Zone
        "institutional_moves":[],   # Stop Hunts, Impulse-Kerzen
        "smc_bias":"NEUTRAL",       # Gesamtbias aus SMC-Sicht
        "smc_score":0,              # Score für Signal-Engine
        "nearest_ob":None,          # Nächster aktiver Order Block
        "nearest_lz":None,          # Nächste Liquiditätszone
        "last_updated":"—",
    },
    "demo_account":{
        "starting_balance":1000.0,"balance":1000.0,"max_leverage":5,
        "risk_per_trade_pct":5.0,"margin_used":0.0,"leverage_used":0.0,
        "peak_balance":1000.0,"max_drawdown_pct":0.0,
        "total_trades":0,"winning_trades":0,"losing_trades":0,"rejected_trades":0,
        "total_pnl_eur":0.0,
        "currency_note":"1 USD ≈ 1 EUR (vereinfacht) · 1 Lot = 100 oz · 1 Punkt = Lot×100 EUR",
    },
}

def add_log(msg,level="INFO"):
    entry={"time":datetime.datetime.utcnow().strftime("%H:%M:%S"),"msg":msg,"level":level}
    bot_state["log"].insert(0,entry)
    if len(bot_state["log"])>200: bot_state["log"].pop()
    print(f"[{level}] {msg}")

# ═══════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════
def get_session():
    h=datetime.datetime.utcnow().hour
    if 22<=h or h<7: return "ASIEN"
    elif 7<=h<12:    return "LONDON"
    elif 12<=h<17:   return "LONDON+NY"
    else:            return "NEW YORK"

def yahoo_fetch(ticker,interval="1m",range_="1d"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_}"
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=12) as r: return json.loads(r.read())
    except: return None

def fetch_price():
    for t in ["XAUUSD%3DX","GC%3DF"]:
        try:
            d=yahoo_fetch(t)
            if d:
                p=float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
                if 1500<p<6000: return round(p,2)
        except: continue
    if bot_state["prices"]: return round(bot_state["prices"][-1]+random.uniform(-0.5,0.5),2)
    return None

def fetch_dxy():
    try:
        d=yahoo_fetch("DX-Y.NYB")
        if d:
            p=float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if 80<p<130: return round(p,3)
    except: pass
    return None

def fetch_yields():
    try:
        d=yahoo_fetch("%5ETNX")
        if d:
            p=float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if 0<p<15: return round(p,3)
    except: pass
    return None

def fetch_candles(interval="1h",count=80):
    mp={"1h":("1h","30d"),"4h":("1h","60d"),"1d":("1d","365d")}
    yi,yr=mp.get(interval,("1h","30d"))
    try:
        d=yahoo_fetch("XAUUSD%3DX",yi,yr)
        if not d: return []
        res=d["chart"]["result"][0]; ts=res["timestamp"]; q=res["indicators"]["quote"][0]
        out=[]
        for i in range(len(ts)):
            try:
                c={"time":ts[i],"open":round(q["open"][i] or 0,2),"high":round(q["high"][i] or 0,2),
                   "low":round(q["low"][i] or 0,2),"close":round(q["close"][i] or 0,2),"volume":int(q["volume"][i] or 0)}
                if 1500<c["close"]<6000: out.append(c)
            except: continue
        return out[-count:] if len(out)>count else out
    except Exception as e:
        add_log(f"Kerzen-Fehler ({interval}): {e}","WARN"); return []

# ═══════════════════════════════════════════════════════
# INDIKATOREN
# ═══════════════════════════════════════════════════════
def calc_ema(p,n):
    if len(p)<n: return None
    k=2.0/(n+1); e=p[0]
    for x in p[1:]: e=x*k+e*(1-k)
    return round(e,2)

def calc_rsi(p,n=14):
    if len(p)<n+1: return None
    g,l=[],[]
    for i in range(1,len(p)):
        d=p[i]-p[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[-n:])/n; al=sum(l[-n:])/n
    return round(100-(100/(1+ag/al)),2) if al else 100.0

def calc_macd(p):
    if len(p)<26: return None,None,None
    e12=calc_ema(p,12); e26=calc_ema(p,26)
    if not e12 or not e26: return None,None,None
    m=round(e12-e26,2); s=round(m*0.85,2); return m,s,round(m-s,2)

def calc_bollinger(p,n=20):
    if len(p)<n: return None,None,None
    s=p[-n:]; mid=sum(s)/n; std=math.sqrt(sum((x-mid)**2 for x in s)/n)
    return round(mid-2*std,2),round(mid,2),round(mid+2*std,2)

def calc_stoch(p,n=14):
    if len(p)<n: return None,None
    s=p[-n:]; lo=min(s); hi=max(s)
    if hi==lo: return 50.0,50.0
    k=round((p[-1]-lo)/(hi-lo)*100,2); return k,round(k*0.9,2)

def calc_atr(p,n=14):
    if len(p)<n+1: return None
    trs=[abs(p[i]-p[i-1]) for i in range(1,len(p))]
    return round(sum(trs[-n:])/n,2)

def calc_adx(p,n=14):
    if len(p)<n*2: return None
    ch=[abs(p[i]-p[i-1]) for i in range(1,len(p))]
    av=sum(ch[-n:])/n; rng=max(p[-n:])-min(p[-n:])
    return min(round((av/rng)*200,1),100) if rng else 0

def calc_cci(p,n=20):
    if len(p)<n: return None
    s=p[-n:]; mean=sum(s)/n; md=sum(abs(x-mean) for x in s)/n
    return round((p[-1]-mean)/(0.015*md),2) if md else 0

def calc_williams_r(p,n=14):
    if len(p)<n: return None
    s=p[-n:]; hi=max(s); lo=min(s)
    if hi==lo: return -50.0
    return round(((hi-p[-1])/(hi-lo))*-100,2)

def calc_momentum(p,n=10):
    if len(p)<n: return None
    return round(p[-1]-p[-n],2)

def calc_volume_profile(candles):
    if len(candles)<10: return None,None,None
    pv={}
    for c in candles:
        mid=round((c["high"]+c["low"])/2,0); pv[mid]=pv.get(mid,0)+c["volume"]
    if not pv: return None,None,None
    poc=max(pv,key=pv.get); tv=sum(pv.values()); cv=0; vah=poc; val=poc
    for p2 in sorted(pv,key=lambda x:pv[x],reverse=True):
        cv+=pv[p2]
        if cv/tv<=0.70: vah=max(vah,p2); val=min(val,p2)
    return round(poc,2),round(vah,2),round(val,2)

def calc_fib(candles,p=50):
    if len(candles)<p: return {}
    sub=candles[-p:]; hi=max(c["high"] for c in sub); lo=min(c["low"] for c in sub); diff=hi-lo
    return {"0":round(hi,2),"23.6":round(hi-0.236*diff,2),"38.2":round(hi-0.382*diff,2),
            "50":round(hi-0.5*diff,2),"61.8":round(hi-0.618*diff,2),"100":round(lo,2)}

def build_indicators(prices,candles=None):
    if len(prices)<30: return {}
    m,ms,mh=calc_macd(prices); bl,bm,bu=calc_bollinger(prices); sk,sd=calc_stoch(prices)
    poc=vah=val=None
    if candles: poc,vah,val=calc_volume_profile(candles)
    return {"price":prices[-1],"ema9":calc_ema(prices,9),"ema20":calc_ema(prices,20),
            "ema50":calc_ema(prices,50),"ema100":calc_ema(prices,100),"ema200":calc_ema(prices,200),
            "rsi":calc_rsi(prices),"macd":m,"macd_signal":ms,"macd_hist":mh,
            "bb_lower":bl,"bb_mid":bm,"bb_upper":bu,"stoch_k":sk,"stoch_d":sd,
            "atr":calc_atr(prices),"adx":calc_adx(prices),
            "williams_r":calc_williams_r(prices),"cci":calc_cci(prices),
            "vwap":round(sum(prices[-20:])/20,2),
            "momentum":calc_momentum(prices),"momentum_5":calc_momentum(prices,5),
            "poc":poc,"vah":vah,"val":val}

# ═══════════════════════════════════════════════════════
# TREND + WOCHE + INTERMARKET
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
    b=0;s=0
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
    if   b>=5: t="BULLISH ▲"
    elif s>=5: t="BEARISH ▼"
    elif b>s:  t="LEICHT BULLISH"
    elif s>b:  t="LEICHT BEARISH"
    else:      t="SEITWÄRTS ↔"
    return t,{"ema20":e20,"ema50":e50,"rsi":r,"poc":poc,"vah":vah,"val":val,"bull":b,"bear":s}

def update_weekly_analysis():
    c1d=bot_state["candles"].get("1d",[])
    if len(c1d)<10: return
    closes=[c["close"] for c in c1d]; wt,_=analyze_trend(c1d); fib=calc_fib(c1d,50)
    res_l=sorted(set([round(c["high"],0) for c in c1d[-30:]]),reverse=True)[:3] if len(c1d)>=30 else []
    sup_l=sorted(set([round(c["low"],0)  for c in c1d[-30:]]))[:3] if len(c1d)>=30 else []
    wr=calc_rsi(closes); dxy=bot_state.get("dxy"); yields=bot_state.get("yields_10y")
    r=[]
    if "BULLISH" in wt: r.append("Übergeordneter Trend bullisch")
    if "BEARISH" in wt: r.append("Übergeordneter Trend bearish")
    if wr and wr<40: r.append(f"RSI={wr} überverkauft")
    if wr and wr>70: r.append(f"RSI={wr} überkauft")
    if dxy: r.append(f"DXY={dxy:.2f} — {'Druck auf Gold' if dxy>103 else 'stützt Gold'}")
    if yields: r.append(f"10Y Yields={yields:.2f}%")
    if "BULLISH" in wt and (not wr or wr<65): fc="BULLISH WOCHE"
    elif "BEARISH" in wt and (not wr or wr>35): fc="BEARISH WOCHE"
    else: fc="NEUTRAL / ABWARTEN"
    kl=[f"Widerstand: {v}" for v in res_l[:2]]+[f"Unterstützung: {v}" for v in sup_l[:2]]
    if fib.get("61.8"): kl.append(f"Fib 61.8%: {fib['61.8']}")
    if fib.get("38.2"): kl.append(f"Fib 38.2%: {fib['38.2']}")
    bot_state["weekly_analysis"]={"trend":wt,"forecast":fc,"key_levels":kl[:6],"reasoning":r[:5],
        "updated":datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")}
    add_log(f"Wochenanalyse: {wt} → {fc}","INFO")

def update_intermarket():
    dxy=fetch_dxy()
    if dxy:
        prev=bot_state["dxy"]; bot_state["dxy"]=dxy; bot_state["dxy_prices"].append(dxy)
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
    bot_state["news_lock"]=False; bot_state["news_lock_reason"]=""; return False

# ═══════════════════════════════════════════════════════
# GUARDRAILS — Spec Abschnitt 5
# ═══════════════════════════════════════════════════════
def check_guardrails():
    gr=bot_state["guardrails"]; da=bot_state["demo_account"]
    today=datetime.datetime.utcnow().strftime("%Y-%m-%d")
    week=datetime.datetime.utcnow().strftime("%Y-W%W")
    if gr["last_reset_daily"]!=today:
        gr["last_reset_daily"]=today; gr["daily_start_balance"]=da["balance"]; gr["daily_pnl_eur"]=0.0
    if gr["last_reset_weekly"]!=week:
        gr["last_reset_weekly"]=week; gr["weekly_start_balance"]=da["balance"]; gr["weekly_pnl_eur"]=0.0
    if gr["daily_start_balance"]>0:
        gr["daily_drawdown_pct"]=round(max(0,(gr["daily_start_balance"]-da["balance"])/gr["daily_start_balance"]*100),2)
    if gr["weekly_start_balance"]>0:
        gr["weekly_drawdown_pct"]=round(max(0,(gr["weekly_start_balance"]-da["balance"])/gr["weekly_start_balance"]*100),2)
    if gr["daily_drawdown_pct"]>=3.0:
        gr["status"]="PAUSE_TAG"
        add_log(f"GUARDRAIL: Tagesverlust {gr['daily_drawdown_pct']:.1f}% ≥ 3% → Handel heute pausiert","WARN")
        return False
    if gr["weekly_drawdown_pct"]>=6.0:
        gr["status"]="PAUSE_WOCHE"
        add_log(f"GUARDRAIL: Wochenverlust {gr['weekly_drawdown_pct']:.1f}% ≥ 6% → Review erforderlich","ERROR")
        return False
    gr["status"]="OK"; return True

def update_performance():
    trades=bot_state["trades"]
    if len(trades)<3: return
    wins=[t["pnl"] for t in trades if t["result"]=="WIN"]
    losses=[abs(t["pnl"]) for t in trades if t["result"]=="LOSS"]
    gross_win=sum(wins); gross_loss=sum(losses)
    avg_win=sum(wins)/len(wins) if wins else 0
    avg_loss=sum(losses)/len(losses) if losses else 0
    wr=len(wins)/len(trades) if trades else 0
    expectancy=round(wr*avg_win-(1-wr)*avg_loss,2) if trades else 0
    pf=round(gross_win/gross_loss,2) if gross_loss>0 else 0
    avg_crv=round(avg_win/avg_loss,2) if avg_loss>0 else 0
    bot_state["performance"]={"expectancy":expectancy,"profit_factor":pf,"avg_crv":avg_crv,"sharpe":0.0}

# ═══════════════════════════════════════════════════════
# 4. STRATEGIE: MACRO-STRUKTUR (Spec Abschnitte 4.1-4.3)
# ═══════════════════════════════════════════════════════
def calc_macro_bias(inds):
    """Macro-Bias Score nach Spec Abschnitt 4.1"""
    score=0; notes=[]
    yt=bot_state.get("yields_trend",""); dxt=bot_state.get("dxy_trend","")
    yields=bot_state.get("yields_10y"); dxy=bot_state.get("dxy")
    r=inds.get("rsi"); mom=inds.get("momentum")
    # Real Yields (10Y als Proxy für Realrenditen)
    if "FALL" in yt:   score+=2; notes.append(f"Yields fallen ({yields:.2f}%) → bullisch für Gold")
    elif "STEIG" in yt: score-=2; notes.append(f"Yields steigen ({yields:.2f}%) → bärisch für Gold")
    else: notes.append(f"Yields neutral ({yields:.2f}% falls bekannt)")
    # DXY
    if "FÄLLT" in dxt:  score+=1; notes.append(f"DXY fällt ({dxy:.2f}) → bullisch")
    elif "STEIGT" in dxt: score-=1; notes.append(f"DXY steigt ({dxy:.2f}) → bärisch")
    # COT-Proxy: RSI-Extreme als Kontraindikator der Spekulation
    if r:
        if r>75:  score-=1; notes.append(f"RSI={r} extrem überkauft → Spekulation überhitzt (Kontraindikator)")
        elif r<25: score+=1; notes.append(f"RSI={r} extrem überverkauft → Kontraindikator bullisch")
    # Momentum als Proxy für institutionelle Nachfrage
    if mom:
        if mom>30:  score+=1; notes.append(f"Starkes Momentum={mom:.1f} → institutionelle Käufe")
        elif mom<-30: score-=1; notes.append(f"Schwaches Momentum={mom:.1f} → institutioneller Verkauf")
    if score>=2:   bias="LONG_BIAS"
    elif score<=-2: bias="SHORT_BIAS"
    else:          bias="NEUTRAL"
    return {"score":score,"bias":bias,"notes":notes}

def classify_market_structure(candles):
    """Marktstruktur nach Spec Abschnitt 4.2 — bei Unklarheit → RANGE (konservativ)"""
    if len(candles)<30: return "UNDEFINED",["Zu wenig Kerzen"]
    highs=[c["high"] for c in candles[-20:]]; lows=[c["low"] for c in candles[-20:]]
    h1_hi=max(highs[:10]); h1_lo=min(lows[:10])
    h2_hi=max(highs[10:]); h2_lo=min(lows[10:])
    notes=[]
    if h2_hi>h1_hi and h2_lo>h1_lo:
        notes.append("Higher Highs + Higher Lows"); return "TREND_UP",notes
    elif h2_hi<h1_hi and h2_lo<h1_lo:
        notes.append("Lower Highs + Lower Lows"); return "TREND_DOWN",notes
    else:
        closes=[c["close"] for c in candles[-20:]]
        rw=(max(highs)-min(lows))/(closes[-1] if closes[-1] else 1)*100
        notes.append(f"Keine klare Struktur — Range ({rw:.1f}% Breite)")
        return "RANGE",notes

def strategy_macro_structure(inds,candles,macro_bias,market_structure):
    """
    Macro-Struktur Strategie — Spec Abschnitte 4.1-4.3
    Setup A: Pullback in Fib-Zone (0.382-0.618) + Bestätigung
    Setup B: Ausbruch + Retest bestätigt
    Setup C: Counter-Trend bei Divergenz (0.5× Größe)
    """
    direction=None; setup_type=None; score=0; signals=[]
    bias=macro_bias.get("bias","NEUTRAL")
    # RANGE/UNDEFINED → kein Trade (Spec: "keine Trend-Setups in Range erzwingen")
    if market_structure in ["RANGE","UNDEFINED"]:
        return {"strategy":"MACRO_STRUCTURE","score":0,"direction":None,
                "signals":[f"{market_structure}: kein Macro-Trade"],"setup_type":None,"size_multiplier":1.0}
    price=inds.get("price"); r=inds.get("rsi"); m=inds.get("macd"); ms_=inds.get("macd_signal")
    atr_v=inds.get("atr",20) or 20

    # ── SETUP A: Pullback auf Fib 38.2%–61.8% + Macro-Bias ──
    if bias=="LONG_BIAS" and market_structure=="TREND_UP" and price:
        fib=calc_fib(candles,40) if len(candles)>=40 else {}
        f38=fib.get("38.2"); f62=fib.get("61.8")
        if f38 and f62 and f62<=price<=f38:
            score+=5; signals.append(f"Setup A: Pullback in Fib-Zone {f62}–{f38}")
            direction="BUY"; setup_type="A_PULLBACK"
            if m and ms_ and m>ms_: score+=2; signals.append("MACD bullisch bestätigt")
            if r and r<55:          score+=1; signals.append(f"RSI={r} aus Rückgang erholt")

    elif bias=="SHORT_BIAS" and market_structure=="TREND_DOWN" and price:
        fib=calc_fib(candles,40) if len(candles)>=40 else {}
        f38=fib.get("38.2"); f62=fib.get("61.8")
        if f38 and f62 and f38<=price<=f62:
            score+=5; signals.append(f"Setup A: Rally in Fib-Zone {f38}–{f62} abverkaufen")
            direction="SELL"; setup_type="A_PULLBACK"
            if m and ms_ and m<ms_: score+=2; signals.append("MACD bearisch bestätigt")
            if r and r>45:          score+=1; signals.append(f"RSI={r} aus Rallye gesunken")

    # ── SETUP B: Ausbruch + Retest ──
    if not direction and len(candles)>=20 and price:
        prev=candles[-20:-3]; recent=candles[-3:]
        if prev and recent:
            ph=max(c["high"] for c in prev); pl=min(c["low"] for c in prev)
            if market_structure=="TREND_UP" and any(c["close"]>ph for c in recent) and abs(price-ph)<atr_v*1.5:
                score+=5; signals.append(f"Setup B: Ausbruch über {ph:.0f} + Retest")
                direction="BUY"; setup_type="B_BREAKOUT"
                if bias=="LONG_BIAS": score+=1; signals.append("Macro-Bias bestätigt")
            elif market_structure=="TREND_DOWN" and any(c["close"]<pl for c in recent) and abs(price-pl)<atr_v*1.5:
                score+=5; signals.append(f"Setup B: Ausbruch unter {pl:.0f} + Retest")
                direction="SELL"; setup_type="B_BREAKOUT"
                if bias=="SHORT_BIAS": score+=1; signals.append("Macro-Bias bestätigt")

    # ── SETUP C: Counter-Trend (Divergenz, halbe Größe) ──
    if not direction and r and price:
        if market_structure=="TREND_UP" and bias=="SHORT_BIAS" and r>72:
            score+=3; signals.append(f"Setup C: Counter-Trend BUY↑ vs SHORT_BIAS (RSI={r}) → 0.5× Größe")
            direction="SELL"; setup_type="C_COUNTER"
        elif market_structure=="TREND_DOWN" and bias=="LONG_BIAS" and r<28:
            score+=3; signals.append(f"Setup C: Counter-Trend SELL↓ vs LONG_BIAS (RSI={r}) → 0.5× Größe")
            direction="BUY"; setup_type="C_COUNTER"

    # Macro-Bias Bonus
    bs=macro_bias.get("score",0)
    if abs(bs)>=3: score+=1; signals.append(f"Macro-Score={bs:+d} (stark)")
    size_mult=0.5 if setup_type=="C_COUNTER" else 1.0
    return {"strategy":"MACRO_STRUCTURE","score":score,"direction":direction,
            "signals":signals,"setup_type":setup_type,"size_multiplier":size_mult}

# ═══════════════════════════════════════════════════════
# 3 BESTEHENDE STRATEGIEN
# ═══════════════════════════════════════════════════════
def strategy_mean_reversion(inds):
    sc=0; sg=[]; d=None
    r=inds.get("rsi"); sk=inds.get("stoch_k")
    bl=inds.get("bb_lower"); bu=inds.get("bb_upper"); p=inds.get("price"); adx=inds.get("adx",30) or 30
    if adx<25: sc+=2; sg.append(f"ADX={adx} Seitwärtsmarkt")
    sb=0
    if r and r<30: sb+=3; sg.append(f"RSI={r} stark überverkauft")
    elif r and r<40: sb+=2; sg.append(f"RSI={r} überverkauft")
    if sk and sk<20: sb+=2; sg.append(f"Stoch={sk} überverkauft")
    if bl and p and p<bl: sb+=3; sg.append("Preis unter BB-Unterkante")
    ss=0
    if r and r>70: ss+=3; sg.append(f"RSI={r} überkauft")
    if sk and sk>80: ss+=2; sg.append(f"Stoch={sk} überkauft")
    if bu and p and p>bu: ss+=3; sg.append("Preis über BB-Oberkante")
    if sb>=5 and sb>=ss: d="BUY"; sc+=sb
    elif ss>=5: d="SELL"; sc+=ss
    return {"strategy":"MEAN_REVERSION","score":sc,"direction":d,"signals":sg}

def strategy_trend_follow(inds):
    sc=0; sg=[]; d=None
    e20=inds.get("ema20"); e50=inds.get("ema50"); e200=inds.get("ema200")
    m=inds.get("macd"); ms_=inds.get("macd_signal"); adx=inds.get("adx",0) or 0
    r=inds.get("rsi"); p=inds.get("price"); mom=inds.get("momentum")
    if adx>25: sc+=2; sg.append(f"ADX={adx} Trend")
    if adx>40: sc+=1; sg.append("ADX>40 sehr stark")
    if e20 and e50 and e200 and p:
        if p>e20>e50>e200: sc+=3; sg.append("EMA-Stack bullish"); d="BUY"
        elif p<e20<e50<e200: sc+=3; sg.append("EMA-Stack bearish"); d="SELL"
    if m and ms_:
        if m>ms_ and d=="BUY": sc+=2; sg.append(f"MACD bullish")
        elif m<ms_ and d=="SELL": sc+=2; sg.append(f"MACD bearish")
    if r and d=="BUY" and 45<r<70: sc+=1; sg.append(f"RSI={r} Trend-Zone")
    if r and d=="SELL" and 30<r<55: sc+=1; sg.append(f"RSI={r} Trend-Zone")
    if mom and d=="BUY" and mom>0: sc+=1; sg.append(f"Mom={mom:+.1f}")
    if mom and d=="SELL" and mom<0: sc+=1; sg.append(f"Mom={mom:+.1f}")
    dxt=bot_state.get("dxy_trend","")
    if d=="SELL" and "STEIGT" in dxt: sc+=1; sg.append("DXY steigt → bärisch")
    if d=="BUY"  and "FÄLLT"  in dxt: sc+=1; sg.append("DXY fällt → bullisch")
    return {"strategy":"TREND_FOLLOW","score":sc,"direction":d,"signals":sg}

def strategy_breakout(inds,candles):
    sc=0; sg=[]; d=None
    if len(candles)<20: return {"strategy":"BREAKOUT","score":0,"direction":None,"signals":[]}
    p=inds.get("price"); rc=candles[-5:]; pv=candles[-20:-5]
    if not rc or not pv: return {"strategy":"BREAKOUT","score":0,"direction":None,"signals":[]}
    ph=max(c["high"] for c in pv); pl=min(c["low"] for c in pv)
    cv=sum(c["volume"] for c in rc)/len(rc); av=sum(c["volume"] for c in pv)/len(pv) if pv else 1
    vr=cv/av if av>0 else 1
    if p and p>ph: sc+=3; sg.append(f"Ausbruch über {ph:.0f}"); d="BUY"
    elif p and p<pl: sc+=3; sg.append(f"Ausbruch unter {pl:.0f}"); d="SELL"
    if vr>1.5: sc+=2; sg.append(f"Vol {vr:.1f}× bestätigt")
    elif vr<0.8 and sc>0: sc-=2; sg.append("⚠ Niedriges Volumen")
    sess=bot_state.get("session","")
    if sess in ["LONDON","NEW YORK","LONDON+NY"]: sc+=1; sg.append(f"Session {sess}")
    poc=inds.get("poc")
    if poc and d=="BUY" and p and p>poc: sc+=1
    if poc and d=="SELL" and p and p<poc: sc+=1
    return {"strategy":"BREAKOUT","score":sc,"direction":d,"signals":sg}

# ═══════════════════════════════════════════════════════
# CONFIRMATION SYSTEM
# ═══════════════════════════════════════════════════════
def check_confirmations(direction,inds,trade_type="SHORT"):
    r=inds.get("rsi"); adx=inds.get("adx",0) or 0
    m=inds.get("macd"); ms_=inds.get("macd_signal")
    e20=inds.get("ema20"); e50=inds.get("ema50"); p=inds.get("price")
    mom=inds.get("momentum"); sk=inds.get("stoch_k")
    t1h=bot_state["trends"].get("1h",""); t4h=bot_state["trends"].get("4h","")
    t1d=bot_state["trends"].get("1d",""); dxt=bot_state.get("dxy_trend","")
    yt=bot_state.get("yields_trend",""); willy=bot_state.get("willy_last")
    if direction=="BUY":
        all_c=[("1H Bullish","BULLISH" in t1h,f"1H: {t1h}"),
               ("4H Bullish","BULLISH" in t4h,f"4H: {t4h}"),
               ("Daily Bullish","BULLISH" in t1d,f"1D: {t1d}"),
               ("RSI<65",r is None or r<65,f"RSI={r}"),
               ("MACD bullish",bool(m and ms_ and m>ms_),f"MACD>{ms_}"),
               ("EMA Stack",bool(e20 and e50 and p and p>e20>e50),"Preis>EMA20>EMA50"),
               ("ADX>20",adx>20,f"ADX={adx}"),
               ("DXY fällt","FÄLLT" in dxt,f"DXY: {dxt}"),
               ("Yields fallen","FALL" in yt,f"Yields: {yt}"),
               ("Momentum+",bool(mom and mom>0),f"Mom={mom}"),
               ("Stoch<80",sk is None or sk<80,f"Stoch={sk}"),
               ("WillyAlgo BUY",bool(willy and "BUY" in willy.get("signal_type","")),"Willy: BUY")]
    else:
        all_c=[("1H Bearish","BEARISH" in t1h,f"1H: {t1h}"),
               ("4H Bearish","BEARISH" in t4h,f"4H: {t4h}"),
               ("Daily Bearish","BEARISH" in t1d,f"1D: {t1d}"),
               ("RSI>35",r is None or r>35,f"RSI={r}"),
               ("MACD bearish",bool(m and ms_ and m<ms_),f"MACD<{ms_}"),
               ("EMA Stack",bool(e20 and e50 and p and p<e20<e50),"Preis<EMA20<EMA50"),
               ("ADX>20",adx>20,f"ADX={adx}"),
               ("DXY steigt","STEIGT" in dxt,f"DXY: {dxt}"),
               ("Yields steigen","STEIG" in yt,f"Yields: {yt}"),
               ("Momentum-",bool(mom and mom<0),f"Mom={mom}"),
               ("Stoch>20",sk is None or sk>20,f"Stoch={sk}"),
               ("WillyAlgo SELL",bool(willy and "SELL" in willy.get("signal_type","")),"Willy: SELL")]
    passed=[(n,d) for n,ok,d in all_c if ok]
    failed=[(n,d) for n,ok,d in all_c if not ok]
    required=7 if trade_type=="LONG" else 5
    return passed,failed,required

def determine_trade_type(inds):
    adx=inds.get("adx",0) or 0; t4h=bot_state["trends"].get("4h",""); t1d=bot_state["trends"].get("1d","")
    if ("BULLISH" in t1d or "BEARISH" in t1d) and adx>30:
        t4b="BULLISH" in t4h; t1b="BULLISH" in t1d
        if t4b==t1b: return "LONG"
    return "SHORT"

# ═══════════════════════════════════════════════════════
# POSITIONSGRÖSSEN — 5% Risiko, 1:5 max Hebel
# ═══════════════════════════════════════════════════════
MIN_LOT=0.01; RISK_HARD_CAP=8.0

def calc_position_size(entry,sl,size_mult=1.0):
    da=bot_state["demo_account"]; bal=da["balance"]
    if not entry or bal<=0: return {"lot":0.0,"rejected":True,"reason":"Kein Kontostand"}
    risk_amt=bal*da["risk_per_trade_pct"]/100*size_mult
    pdiff=abs(entry-sl) if sl else max(entry*0.01,20)
    if pdiff==0: pdiff=20
    risk_lot=risk_amt/(pdiff*100)
    max_notional=bal*da["max_leverage"]; lev_lot=max_notional/(entry*100)
    lot=min(risk_lot,lev_lot)
    if lot<MIN_LOT:
        loss_min=pdiff*MIN_LOT*100; lpct=loss_min/bal*100
        if lpct<=RISK_HARD_CAP: lot=MIN_LOT
        else: return {"lot":0.0,"rejected":True,"reason":f"Risiko {lpct:.1f}%>{RISK_HARD_CAP}% Limit"}
    lot=round(min(lot,lev_lot),2)
    if lot<MIN_LOT: lot=MIN_LOT
    notional=round(lot*100*entry,2); lev_used=round(notional/bal,2)
    margin=round(notional/da["max_leverage"],2); risk_eur=round(pdiff*lot*100,2)
    return {"lot":lot,"rejected":False,"reason":"","notional":notional,
            "leverage_used":lev_used,"margin_used":margin,"risk_eur":risk_eur,
            "risk_pct":round(risk_eur/bal*100,2)}

def get_demo_snapshot():
    da=dict(bot_state["demo_account"]); p=bot_state.get("price"); ot=bot_state.get("open_trade")
    unreal=0.0
    if ot and p:
        pts=(p-ot["entry"]) if ot["direction"]=="BUY" else (ot["entry"]-p)
        unreal=round(pts*ot.get("lot_size",MIN_LOT)*100,2)
    da["unrealized_pnl_eur"]=unreal; da["equity"]=round(da["balance"]+unreal,2)
    da["free_margin"]=round(da["equity"]-da.get("margin_used",0.0),2)
    sb=da.get("starting_balance",1000) or 1000; da["return_pct"]=round((da["equity"]-sb)/sb*100,2)
    tt=da.get("total_trades",0); da["win_rate_pct"]=round(da["winning_trades"]/tt*100,1) if tt else 0.0
    return da

# ═══════════════════════════════════════════════════════
# SIGNAL ENGINE — alle 4 Strategien
# ═══════════════════════════════════════════════════════
def evaluate_signal(inds,candles):
    if not inds or not inds.get("price"): return "WARTEN",0,[],[],"—",{},[]
    if check_news_lock(): return "WARTEN",0,[],[],"NEWS-SPERRE",{},[]
    if not check_guardrails(): return "WARTEN",0,[],[],"GUARDRAIL",{},[]
    mr=strategy_mean_reversion(inds); tf=strategy_trend_follow(inds); bo=strategy_breakout(inds,candles)
    # Macro-Struktur Strategie
    macro_bias=calc_macro_bias(inds)
    ms_txt,ms_notes=classify_market_structure(candles)
    ms=strategy_macro_structure(inds,candles,macro_bias,ms_txt)
    bot_state["macro_state"].update({"bias":macro_bias["bias"],"bias_score":macro_bias["score"],
        "bias_notes":macro_bias["notes"],"market_structure":ms_txt,"structure_notes":ms_notes,
        "setup_type":ms.get("setup_type"),"size_multiplier":ms.get("size_multiplier",1.0),
        "last_updated":datetime.datetime.utcnow().strftime("%H:%M:%S")})
    bot_state["strategy_scores"]={"mean_reversion":mr["score"],"trend_follow":tf["score"],
                                   "breakout":bo["score"],"macro_structure":ms["score"]}
    all4=[mr,tf,bo,ms]; best=max(all4,key=lambda x:x["score"])
    bot_state["active_strategy"]=best["strategy"]
    direction=best["direction"]; score=best["score"]
    all_sigs=mr["signals"]+tf["signals"]+bo["signals"]+ms["signals"]
    bull=[s for s in all_sigs if any(w in s.lower() for w in ["bull","buy","steigt dxy nicht","fällt dxy","positiv","über","aufwärts"])]
    bear=[s for s in all_sigs if s not in bull]
    t1h=bot_state["trends"].get("1h",""); t4h=bot_state["trends"].get("4h",""); t1d=bot_state["trends"].get("1d","")
    tb=sum(1 for t in [t1h,t4h,t1d] if "BULLISH" in t); ts=sum(1 for t in [t1h,t4h,t1d] if "BEARISH" in t)
    if tb>=2: bull.append(f"Multi-TF: {tb}/3 bullish"); score+=1
    if ts>=2: bear.append(f"Multi-TF: {ts}/3 bearish"); score+=1
    if score<5 or not direction: return "WARTEN",round(score/14*100,1),bull,bear,"WARTEN",{},[]
    tt=determine_trade_type(inds)
    passed,failed,required=check_confirmations(direction,inds,tt)
    bot_state["confirmations"]={"passed":[p[0] for p in passed],"failed":[f[0] for f in failed],
                                 "count":len(passed),"required":required}
    if len(passed)<required:
        return "WARTEN",round(len(passed)/required*100,1),bull,bear,f"Nur {len(passed)}/{required} Conf.",{},failed
    conf=min(round(len(passed)/12*100,1),99)
    return direction,conf,bull,bear,best["strategy"],{"passed":passed,"failed":failed},failed

# ═══════════════════════════════════════════════════════
# LERNMODUL
# ═══════════════════════════════════════════════════════
def analyze_failed_trade(trade,inds):
    mist=[]; d=trade.get("direction")
    r=inds.get("rsi"); adx=inds.get("adx"); m=inds.get("macd"); ms_=inds.get("macd_signal")
    t4h=bot_state["trends"].get("4h",""); dxt=bot_state.get("dxy_trend","")
    if d=="BUY":
        if r and r>65:         mist.append({"rule":"BUY_HIGH_RSI",    "desc":f"BUY bei RSI={r}",       "avoid":"Kein BUY wenn RSI>65"})
        if adx and adx<20:     mist.append({"rule":"BUY_WEAK_ADX",    "desc":f"BUY bei ADX={adx}",     "avoid":"Kein BUY wenn ADX<20"})
        if "BEARISH" in t4h:   mist.append({"rule":"BUY_AGAINST_4H",  "desc":"BUY gegen 4H Bearish",   "avoid":"Kein BUY wenn 4H=BEARISH"})
        if m and ms_ and m<ms_:mist.append({"rule":"BUY_BEAR_MACD",   "desc":"BUY bei MACD bearish",   "avoid":"Kein BUY wenn MACD<Signal"})
        if "STEIGT" in dxt:    mist.append({"rule":"BUY_RISING_DXY",  "desc":"BUY bei steig. DXY",     "avoid":"Kein BUY wenn DXY steigt (extra Conf. nötig)"})
    elif d=="SELL":
        if r and r<35:         mist.append({"rule":"SELL_LOW_RSI",    "desc":f"SELL bei RSI={r}",      "avoid":"Kein SELL wenn RSI<35"})
        if adx and adx<20:     mist.append({"rule":"SELL_WEAK_ADX",   "desc":f"SELL bei ADX={adx}",    "avoid":"Kein SELL wenn ADX<20"})
        if "BULLISH" in t4h:   mist.append({"rule":"SELL_AGAINST_4H", "desc":"SELL gegen 4H Bullish",  "avoid":"Kein SELL wenn 4H=BULLISH"})
        if "FÄLLT" in dxt:     mist.append({"rule":"SELL_FALLING_DXY","desc":"SELL bei fall. DXY",     "avoid":"Kein SELL wenn DXY fällt (extra Conf. nötig)"})
    return mist

def update_rules(mist):
    rules=bot_state["learning"]["rules"]
    for m in mist:
        ex=next((r for r in rules if r["rule"]==m["rule"]),None)
        if ex: ex["count"]+=1; ex["last"]=datetime.datetime.utcnow().strftime("%d.%m %H:%M")
        else: rules.insert(0,{"rule":m["rule"],"desc":m["desc"],"avoid":m["avoid"],"count":1,"last":datetime.datetime.utcnow().strftime("%d.%m %H:%M")})
    if len(rules)>25: rules.pop()

def check_rules(signal,inds):
    violated=[]; r=inds.get("rsi"); adx=inds.get("adx"); m=inds.get("macd"); ms_=inds.get("macd_signal")
    t4h=bot_state["trends"].get("4h",""); dxt=bot_state.get("dxy_trend","")
    conf=bot_state["confirmations"]; extra=conf.get("count",0)>=conf.get("required",5)+2
    for rule in bot_state["learning"]["rules"]:
        if rule["count"]<2: continue
        k=rule["rule"]; vn=False
        if k=="BUY_HIGH_RSI"   and signal=="BUY"  and r   and r>65:        vn=True
        elif k=="BUY_WEAK_ADX" and signal=="BUY"  and adx and adx<20:      vn=True
        elif k=="BUY_AGAINST_4H" and signal=="BUY" and "BEARISH" in t4h:   vn=True
        elif k=="BUY_BEAR_MACD" and signal=="BUY" and m and ms_ and m<ms_: vn=True
        elif k=="BUY_RISING_DXY" and signal=="BUY" and "STEIGT" in dxt:    vn=not extra
        elif k=="SELL_LOW_RSI" and signal=="SELL" and r   and r<35:        vn=True
        elif k=="SELL_WEAK_ADX" and signal=="SELL" and adx and adx<20:     vn=True
        elif k=="SELL_AGAINST_4H" and signal=="SELL" and "BULLISH" in t4h: vn=True
        elif k=="SELL_FALLING_DXY" and signal=="SELL" and "FÄLLT" in dxt:  vn=not extra
        if vn: violated.append(rule["avoid"])
    return violated

# ═══════════════════════════════════════════════════════
# TRADE MANAGEMENT
# ═══════════════════════════════════════════════════════
MIN_HOLD_MIN=30

def open_trade(sig,price,atr_v,inds_snap,strategy,trade_type,passed_conf,size_mult=1.0):
    mult={"SHORT":1.5,"LONG":2.5}.get(trade_type,1.5); tp_m={"SHORT":1.5,"LONG":3.0}.get(trade_type,1.5)
    sl=round(price-mult*atr_v,2) if sig=="BUY" else round(price+mult*atr_v,2)
    tp1=round(price+tp_m*atr_v,2) if sig=="BUY" else round(price-tp_m*atr_v,2)
    tp2=round(price+tp_m*2*atr_v,2) if sig=="BUY" else round(price-tp_m*2*atr_v,2)
    tp3=round(price+tp_m*3*atr_v,2) if sig=="BUY" else round(price-tp_m*3*atr_v,2)
    sizing=calc_position_size(price,sl,size_mult)
    if sizing["rejected"]:
        bot_state["stats"]["rejected_by_risk"]+=1; bot_state["demo_account"]["rejected_trades"]+=1
        add_log(f"Trade ABGELEHNT: {sizing['reason']}","LEARN"); return False
    lot=sizing["lot"]
    bot_state["open_trade"]={"direction":sig,"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
        "lot_size":lot,"strategy":strategy,"trade_type":trade_type,"size_multiplier":size_mult,
        "open_time":datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "hold_min":0.0,"status":"OPEN","inds_at_entry":inds_snap,
        "willy_confirmed":bot_state["willy_last"] is not None,"confirmations_passed":len(passed_conf),
        "notional":sizing["notional"],"leverage_used":sizing["leverage_used"],
        "margin_used":sizing["margin_used"],"risk_eur":sizing["risk_eur"],"risk_pct":sizing["risk_pct"]}
    da=bot_state["demo_account"]; da["margin_used"]=sizing["margin_used"]; da["leverage_used"]=sizing["leverage_used"]
    add_log(f"{trade_type} {sig} @ {price} | SL:{sl} TP1:{tp1} TP2:{tp2} | Lot:{lot} | Hebel 1:{sizing['leverage_used']} | Risiko {sizing['risk_pct']}% (€{sizing['risk_eur']})","TRADE")
    return True

def check_trade(price):
    t=bot_state["open_trade"]
    if not t: return
    try:
        ot=datetime.datetime.strptime(t["open_time"],"%Y-%m-%d %H:%M:%S")
        hold_min=(datetime.datetime.utcnow()-ot).total_seconds()/60; t["hold_min"]=round(hold_min,1)
    except: hold_min=999
    res=None; pnl=0; all_tp=False
    if t["direction"]=="BUY":
        if price<=t["sl"]:                              res="LOSS"; pnl=round(t["sl"]-t["entry"],2)
        elif price>=t["tp3"]:                           res="WIN";  pnl=round(t["tp3"]-t["entry"],2); all_tp=True
        elif price>=t["tp2"] and hold_min>=MIN_HOLD_MIN: res="WIN";  pnl=round(t["tp2"]-t["entry"],2)
        elif price>=t["tp1"] and hold_min>=MIN_HOLD_MIN: res="WIN";  pnl=round(t["tp1"]-t["entry"],2)
    elif t["direction"]=="SELL":
        if price>=t["sl"]:                              res="LOSS"; pnl=round(t["entry"]-t["sl"],2)
        elif price<=t["tp3"]:                           res="WIN";  pnl=round(t["entry"]-t["tp3"],2); all_tp=True
        elif price<=t["tp2"] and hold_min>=MIN_HOLD_MIN: res="WIN";  pnl=round(t["entry"]-t["tp2"],2)
        elif price<=t["tp1"] and hold_min>=MIN_HOLD_MIN: res="WIN";  pnl=round(t["entry"]-t["tp1"],2)
    if not res: return
    lot=t.get("lot_size",MIN_LOT); eur_pnl=round(pnl*lot*100,2)
    t.update({"close_price":price,"pnl":pnl,"result":res,"eur_pnl":eur_pnl,
              "hold_min_final":round(hold_min,1),"all_tp_hit":all_tp,
              "close_time":datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")})
    bot_state["trades"].insert(0,{k:v for k,v in t.items() if k!="inds_at_entry"})
    if len(bot_state["trades"])>300: bot_state["trades"].pop()
    # Learning
    if res=="LOSS":
        mist=analyze_failed_trade(t,t.get("inds_at_entry",{}))
        if mist:
            bot_state["learning"]["mistakes"].insert(0,{"time":datetime.datetime.utcnow().strftime("%d.%m %H:%M"),
                "trade":f"{t['direction']} @ {t['entry']} [{t.get('strategy','')}]","mistakes":mist})
            if len(bot_state["learning"]["mistakes"])>30: bot_state["learning"]["mistakes"].pop()
            update_rules(mist)
        if t.get("confirmations_passed",0)>=5:
            bot_state["learning"]["confirmation_failures"].insert(0,{"time":datetime.datetime.utcnow().strftime("%d.%m %H:%M"),
                "trade":f"{t['direction']} @ {t['entry']}","conf_count":t.get("confirmations_passed",0),"pnl":pnl})
            if len(bot_state["learning"]["confirmation_failures"])>15: bot_state["learning"]["confirmation_failures"].pop()
    bot_state["open_trade"]=None
    # Global Stats
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
    # ── Pro-Strategie P&L ──
    strat_key=t.get("strategy","MEAN_REVERSION")
    if strat_key in bot_state["strategy_stats"]:
        ss=bot_state["strategy_stats"][strat_key]
        ss["trades"]+=1; ss["pnl"]=round(ss["pnl"]+pnl,2); ss["eur_pnl"]=round(ss["eur_pnl"]+eur_pnl,2)
        if res=="WIN":
            ss["wins"]+=1; ss["best"]=round(max(ss["best"],pnl),2)
        else:
            ss["losses"]+=1; ss["worst"]=round(min(ss["worst"],pnl),2)
        ss["win_rate"]=round(ss["wins"]/ss["trades"]*100,1) if ss["trades"]>0 else 0.0
    # Demo Konto
    da=bot_state["demo_account"]
    da["balance"]=round(max(da["balance"]+eur_pnl,0.0),2); da["total_trades"]+=1
    if res=="WIN": da["winning_trades"]+=1
    else: da["losing_trades"]+=1
    da["total_pnl_eur"]=round(da["total_pnl_eur"]+eur_pnl,2)
    da["peak_balance"]=round(max(da["peak_balance"],da["balance"]),2)
    if da["peak_balance"]>0:
        dd=round((da["peak_balance"]-da["balance"])/da["peak_balance"]*100,2)
        da["max_drawdown_pct"]=round(max(da["max_drawdown_pct"],dd),2)
    da["margin_used"]=0.0; da["leverage_used"]=0.0
    # Guardrail Update
    gr=bot_state["guardrails"]; gr["daily_pnl_eur"]=round(gr.get("daily_pnl_eur",0)+eur_pnl,2)
    gr["weekly_pnl_eur"]=round(gr.get("weekly_pnl_eur",0)+eur_pnl,2)
    update_performance()
    add_log(f"Trade {res}: {t['direction']} @ {t['entry']}→{price} | {pnl:+.2f}Pkt | €{eur_pnl:+.2f} | {strat_key} | {hold_min:.0f}Min","TRADE")

# ═══════════════════════════════════════════════════════
# HAUPTLOOP
# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════
# WILLYALGOTRADER — Signal-Tracking & Win-Rate Analyse
# ═══════════════════════════════════════════════════════
import uuid as _uuid

def _willy_direction(sig_type):
    """Erkennt ob ein Signal BUY, SELL oder ein TP/SL-Event ist."""
    s=sig_type.upper()
    if any(x in s for x in ["TP1","TP2","TP3","TP_1","TP_2","TP_3","TARGET"]): return "TP"
    if any(x in s for x in ["SL","STOP","STOPLOSS","LOSS_HIT"]): return "SL"
    if any(x in s for x in ["BUY","LONG","BULLISH"]): return "BUY"
    if any(x in s for x in ["SELL","SHORT","BEARISH"]): return "SELL"
    return None

def _willy_tp_level(sig_type):
    s=sig_type.upper()
    if "TP3" in s or "TP_3" in s or "TARGET3" in s: return 3
    if "TP2" in s or "TP_2" in s or "TARGET2" in s: return 2
    if "TP1" in s or "TP_1" in s or "TARGET1" in s: return 1
    return None

def _willy_score(sig_type):
    s=sig_type.upper()
    if "A+" in s or "APLUS" in s or "A_PLUS" in s or "SCORE_A" in s: return "A+"
    if "A"  in s and "B" not in s: return "A"
    if "B+" in s: return "B+"
    if "B"  in s: return "B"
    if "C"  in s: return "C"
    return "—"

def process_willy_signal(data):
    """Verarbeitet eingehende WillyAlgoTrader Webhooks komplett."""
    wa=bot_state["willy_analytics"]
    sig_type=data.get("signal","").upper()
    tf=data.get("timeframe","—")
    score=str(data.get("score","—"))
    pr=data.get("price") or data.get("close") or bot_state.get("price")
    try: entry_price=float(str(pr).replace(",",".")) if pr else None
    except: entry_price=None
    def _safe(v):
        try: return float(str(v).replace(",",".")) if v else None
        except: return None
    tp1=_safe(data.get("tp1")); tp2=_safe(data.get("tp2"))
    tp3=_safe(data.get("tp3")); sl=_safe(data.get("sl"))
    direction=_willy_direction(sig_type)
    tp_level=_willy_tp_level(sig_type)
    score_clean=_willy_score(sig_type)
    now_str=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # ── TP-Hit: offene Signale auflösen ──
    if direction=="TP" and tp_level:
        wa["tp1_hits" if tp_level==1 else "tp2_hits" if tp_level==2 else "tp3_hits"]+=1
        resolved=False
        for sig in wa["open_signals"]:
            if sig["status"]=="PENDING":
                sig["status"]=f"WIN_TP{tp_level}"
                sig["result"]="WIN"; sig["tp_level_hit"]=tp_level
                sig["close_time"]=now_str; sig["close_price"]=entry_price
                if entry_price and sig.get("entry"):
                    pts=abs(entry_price-sig["entry"])
                    sig["pips"]=round(pts,2)
                    wa["avg_pips_win"]=round((wa["avg_pips_win"]*wa["wins"]+pts)/(wa["wins"]+1),2)
                _close_willy_signal(sig,"WIN",tp_level)
                resolved=True; break
        if resolved: _recalc_willy_stats()
        return

    # ── SL-Hit: offene Signale als Verlust schließen ──
    if direction=="SL":
        wa["sl_hits"]+=1
        for sig in wa["open_signals"]:
            if sig["status"]=="PENDING":
                sig["status"]="LOSS_SL"; sig["result"]="LOSS"
                sig["close_time"]=now_str; sig["close_price"]=entry_price
                if entry_price and sig.get("entry"):
                    pts=abs(entry_price-sig["entry"])
                    sig["pips"]=-round(pts,2)
                    wa["avg_pips_loss"]=round((wa["avg_pips_loss"]*wa["losses"]+pts)/(wa["losses"]+1),2)
                _close_willy_signal(sig,"LOSS",None)
                break
        _recalc_willy_stats(); return

    # ── Neues BUY/SELL-Signal ──
    if direction in ["BUY","SELL"]:
        sig_id=str(_uuid.uuid4())[:8]
        new_sig={
            "id":sig_id,"signal_type":sig_type,"direction":direction,
            "timeframe":tf,"score":score_clean,"raw_score":score,
            "entry":entry_price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
            "open_time":now_str,"close_time":None,"close_price":None,
            "status":"PENDING","result":None,"tp_level_hit":None,"pips":None,
        }
        wa["open_signals"].insert(0,new_sig)
        if len(wa["open_signals"])>50: wa["open_signals"].pop()
        wa["total"]+=1; wa["pending"]+=1
        # By-Direction zählen
        dk=wa["by_direction"].get(direction,{"count":0,"wins":0,"losses":0,"pending":0,"win_rate":0.0,"tp1":0,"tp2":0,"tp3":0})
        dk["count"]+=1; dk["pending"]+=1; wa["by_direction"][direction]=dk
        # By-TF zählen
        if tf not in wa["by_tf"]: wa["by_tf"][tf]={"count":0,"wins":0,"losses":0,"pending":0,"win_rate":0.0,"tp1":0,"tp2":0,"tp3":0}
        wa["by_tf"][tf]["count"]+=1; wa["by_tf"][tf]["pending"]+=1
        # By-Score zählen
        if score_clean not in wa["by_score"]: wa["by_score"][score_clean]={"count":0,"wins":0,"losses":0,"pending":0,"win_rate":0.0}
        wa["by_score"][score_clean]["count"]+=1; wa["by_score"][score_clean]["pending"]+=1
        add_log(f"⭐ Willy {direction} [{tf}] Score:{score_clean} @ {entry_price} | TP1:{tp1} SL:{sl}","SIGNAL")
        _recalc_willy_stats()

def _close_willy_signal(sig,result,tp_level):
    """Bewegt Signal von open in closed, aktualisiert Statistiken."""
    wa=bot_state["willy_analytics"]
    wa["open_signals"]=[s for s in wa["open_signals"] if s["id"]!=sig["id"]]
    wa["closed_signals"].insert(0,sig)
    if len(wa["closed_signals"])>500: wa["closed_signals"].pop()
    wa["pending"]=max(0,wa["pending"]-1)
    if result=="WIN":
        wa["wins"]+=1
        d=wa["by_direction"].get(sig["direction"],{})
        d["wins"]=d.get("wins",0)+1; d["pending"]=max(0,d.get("pending",0)-1)
        if tp_level: d[f"tp{tp_level}"]=d.get(f"tp{tp_level}",0)+1
        tf=sig.get("timeframe","—"); sc=sig.get("score","—")
        if tf in wa["by_tf"]:
            wa["by_tf"][tf]["wins"]+=1; wa["by_tf"][tf]["pending"]=max(0,wa["by_tf"][tf]["pending"]-1)
            if tp_level: wa["by_tf"][tf][f"tp{tp_level}"]=wa["by_tf"][tf].get(f"tp{tp_level}",0)+1
        if sc in wa["by_score"]:
            wa["by_score"][sc]["wins"]+=1; wa["by_score"][sc]["pending"]=max(0,wa["by_score"][sc]["pending"]-1)
    else:
        wa["losses"]+=1
        d=wa["by_direction"].get(sig["direction"],{})
        d["losses"]=d.get("losses",0)+1; d["pending"]=max(0,d.get("pending",0)-1)
        tf=sig.get("timeframe","—"); sc=sig.get("score","—")
        if tf in wa["by_tf"]:
            wa["by_tf"][tf]["losses"]+=1; wa["by_tf"][tf]["pending"]=max(0,wa["by_tf"][tf]["pending"]-1)
        if sc in wa["by_score"]:
            wa["by_score"][sc]["losses"]+=1; wa["by_score"][sc]["pending"]=max(0,wa["by_score"][sc]["pending"]-1)

def _recalc_willy_stats():
    """Berechnet alle Win-Rates neu."""
    wa=bot_state["willy_analytics"]
    resolved=wa["wins"]+wa["losses"]
    wa["overall_win_rate"]=round(wa["wins"]/resolved*100,1) if resolved else 0.0
    for d in list(wa["by_direction"].values()):
        r=d.get("wins",0)+d.get("losses",0)
        d["win_rate"]=round(d.get("wins",0)/r*100,1) if r else 0.0
    for d in list(wa["by_tf"].values()):
        r=d.get("wins",0)+d.get("losses",0)
        d["win_rate"]=round(d.get("wins",0)/r*100,1) if r else 0.0
    for d in list(wa["by_score"].values()):
        r=d.get("wins",0)+d.get("losses",0)
        d["win_rate"]=round(d.get("wins",0)/r*100,1) if r else 0.0
    # Bestes/schlechtestes Signal
    if wa["by_score"]:
        scored={k:v for k,v in wa["by_score"].items() if (v.get("wins",0)+v.get("losses",0))>0}
        if scored:
            wa["best_signal_type"]=max(scored,key=lambda k:scored[k]["win_rate"])
            wa["worst_signal_type"]=min(scored,key=lambda k:scored[k]["win_rate"])

def check_willy_open_signals(price):
    """Prüft offene Willy-Signale gegen den aktuellen Preis auf TP/SL."""
    wa=bot_state["willy_analytics"]
    now=datetime.datetime.utcnow()
    to_close=[]
    for sig in wa["open_signals"]:
        if sig["status"]!="PENDING": continue
        try:
            ot=datetime.datetime.strptime(sig["open_time"],"%Y-%m-%d %H:%M:%S")
            age_h=(now-ot).total_seconds()/3600
        except: age_h=0
        entry=sig.get("entry"); tp1=sig.get("tp1"); tp2=sig.get("tp2"); tp3=sig.get("tp3"); sl=sig.get("sl")
        if not entry: continue
        result=None; tp_level=None; close_price=price
        if sig["direction"]=="BUY":
            if sl and price<=sl: result="LOSS"
            elif tp3 and price>=tp3: result="WIN"; tp_level=3
            elif tp2 and price>=tp2: result="WIN"; tp_level=2
            elif tp1 and price>=tp1: result="WIN"; tp_level=1
        elif sig["direction"]=="SELL":
            if sl and price>=sl: result="LOSS"
            elif tp3 and price<=tp3: result="WIN"; tp_level=3
            elif tp2 and price<=tp2: result="WIN"; tp_level=2
            elif tp1 and price<=tp1: result="WIN"; tp_level=1
        # Auto-expire nach 48h ohne Ergebnis
        if not result and age_h>48: result="EXPIRED"; sig["status"]="EXPIRED"
        if result and result!="EXPIRED":
            sig["status"]=f"WIN_TP{tp_level}" if result=="WIN" else "LOSS_SL"
            sig["result"]=result; sig["tp_level_hit"]=tp_level
            sig["close_time"]=now.strftime("%Y-%m-%d %H:%M:%S"); sig["close_price"]=close_price
            pips=abs(close_price-entry)
            sig["pips"]=round(pips,2) if result=="WIN" else -round(pips,2)
            if result=="WIN" and tp_level:
                wa[f"tp{tp_level}_hits"]+=1
            else:
                wa["sl_hits"]+=1
            to_close.append((sig,result,tp_level))
        elif result=="EXPIRED":
            to_close.append((sig,"LOSS",None))
    for sig,res,tp in to_close:
        _close_willy_signal(sig,res,tp)
    if to_close:
        _recalc_willy_stats()
        add_log(f"Willy: {len(to_close)} Signal(e) automatisch aufgelöst","INFO")

# ═══════════════════════════════════════════════════════
# SMART MONEY CONCEPTS (SMC) — Institutionelle Analyse
# ═══════════════════════════════════════════════════════

def find_order_blocks(candles, lookback=60):
    """
    Order Blocks: Letzte Gegenkerze vor einem starken Impuls.
    Institutionen platzieren dort ihre Orders → starke S/R-Zonen.
    Bullish OB: Letzte bearishe Kerze vor bullischem Impuls
    Bearish OB: Letzte bullishe Kerze vor bearischem Impuls
    """
    if len(candles) < 8: return []
    obs = []; sub = candles[-lookback:] if len(candles) > lookback else candles
    atr_proxy = sum(abs(sub[i]["close"]-sub[i-1]["close"]) for i in range(1,len(sub)))/len(sub) if len(sub)>1 else 10
    for i in range(1, len(sub)-3):
        c=sub[i]; n1=sub[i+1]; n2=sub[i+2]; n3=sub[i+3]
        body_c=abs(c["close"]-c["open"])
        # BULLISH OB: bearishe Kerze gefolgt von starkem bullischem Impuls
        if c["close"]<c["open"]:
            impulse=(n3["close"]-c["low"])
            if impulse > atr_proxy*2 and n1["close"]>n1["open"] and n2["close"]>n2["open"]:
                strength=round(min(impulse/atr_proxy/3,1.0)*100,0)
                obs.append({"type":"BULLISH_OB","high":c["high"],"low":c["low"],
                    "mid":round((c["high"]+c["low"])/2,2),"strength":strength,
                    "label":f"Bullish OB {c['low']:.2f}–{c['high']:.2f}","active":True,
                    "idx":i,"impulse":round(impulse,2)})
        # BEARISH OB: bullishe Kerze gefolgt von starkem bearischem Impuls
        if c["close"]>c["open"]:
            impulse=(c["high"]-n3["close"])
            if impulse > atr_proxy*2 and n1["close"]<n1["open"] and n2["close"]<n2["open"]:
                strength=round(min(impulse/atr_proxy/3,1.0)*100,0)
                obs.append({"type":"BEARISH_OB","high":c["high"],"low":c["low"],
                    "mid":round((c["high"]+c["low"])/2,2),"strength":strength,
                    "label":f"Bearish OB {c['low']:.2f}–{c['high']:.2f}","active":True,
                    "idx":i,"impulse":round(impulse,2)})
    # Nur die 8 stärksten behalten
    obs_sorted=sorted(obs,key=lambda x:x["strength"],reverse=True)
    return obs_sorted[:8]

def find_liquidity_zones(candles, price, lookback=60):
    """
    Liquiditätszonen: Wo liegen Stop-Orders konzentriert?
    - Buy-Side Liquidity (BSL): Stops über Swing-Highs / Equal Highs
    - Sell-Side Liquidity (SSL): Stops unter Swing-Lows / Equal Lows
    - Round Numbers: Psychologische Level (jeder 50er/100er)
    """
    if len(candles)<8 or not price: return []
    zones=[]; sub=candles[-lookback:] if len(candles)>lookback else candles
    tol=price*0.0008  # 0.08% Toleranz für Equal H/L
    # Swing Highs → BSL (Buy-Side Liquidity: Stops über den Hochs)
    sh_seen=set()
    for i in range(2,len(sub)-2):
        h=sub[i]["high"]
        if h>sub[i-1]["high"] and h>sub[i-2]["high"] and h>sub[i+1]["high"] and h>sub[i+2]["high"]:
            lv=round(h,1)
            if lv not in sh_seen:
                sh_seen.add(lv)
                zones.append({"type":"BSL","level":h,"direction":"ABOVE",
                    "label":f"Buy-Side Liq. (BSL) @ {h:.2f}",
                    "dist_pct":round((h-price)/price*100,2),"strength":60})
    # Swing Lows → SSL (Sell-Side Liquidity: Stops unter den Tiefs)
    sl_seen=set()
    for i in range(2,len(sub)-2):
        l=sub[i]["low"]
        if l<sub[i-1]["low"] and l<sub[i-2]["low"] and l<sub[i+1]["low"] and l<sub[i+2]["low"]:
            lv=round(l,1)
            if lv not in sl_seen:
                sl_seen.add(lv)
                zones.append({"type":"SSL","level":l,"direction":"BELOW",
                    "label":f"Sell-Side Liq. (SSL) @ {l:.2f}",
                    "dist_pct":round((price-l)/price*100,2),"strength":60})
    # Equal Highs / Equal Lows (doppelte Bestätigung = mehr Stops)
    highs=[c["high"] for c in sub]; lows=[c["low"] for c in sub]
    for i in range(len(sub)):
        for j in range(i+3,len(sub)):
            if abs(sub[i]["high"]-sub[j]["high"])<tol:
                lv=round((sub[i]["high"]+sub[j]["high"])/2,2)
                zones.append({"type":"EQH","level":lv,"direction":"ABOVE",
                    "label":f"Equal Highs (EQH) @ {lv:.2f} ← Hohe Liquidität!",
                    "dist_pct":round((lv-price)/price*100,2),"strength":85})
                break
            if abs(sub[i]["low"]-sub[j]["low"])<tol:
                lv=round((sub[i]["low"]+sub[j]["low"])/2,2)
                zones.append({"type":"EQL","level":lv,"direction":"BELOW",
                    "label":f"Equal Lows (EQL) @ {lv:.2f} ← Hohe Liquidität!",
                    "dist_pct":round((price-lv)/price*100,2),"strength":85})
                break
    # Round Numbers (psychologische Levels für Gold)
    for step in [50,100,250,500]:
        base=round(price/step)*step
        for offset in [-step*2,-step,0,step,step*2]:
            lv=base+offset
            if lv>0 and abs(lv-price)/price<0.025:
                zones.append({"type":"ROUND","level":float(lv),"direction":"ABOVE" if lv>price else "BELOW",
                    "label":f"Psych. Level @ {lv:.0f}",
                    "dist_pct":round(abs(lv-price)/price*100,2),"strength":50})
    # Sortieren nach Distanz, Duplikate entfernen
    seen=set(); unique=[]
    for z in sorted(zones,key=lambda x:abs(x.get("dist_pct",99))):
        k=round(z["level"]/5)*5
        if k not in seen: seen.add(k); unique.append(z)
    return unique[:12]

def find_fair_value_gaps(candles, lookback=40):
    """
    Fair Value Gaps (FVG) / Imbalances:
    3-Kerzen-Muster wo Angebot/Nachfrage unausgeglichen sind.
    Preis kehrt oft zurück um diese Lücken zu 'füllen'.
    Bullish FVG: c[i-1].high < c[i+1].low  (Gap nach oben)
    Bearish FVG: c[i-1].low  > c[i+1].high (Gap nach unten)
    """
    if len(candles)<5: return []
    fvgs=[]; sub=candles[-lookback:] if len(candles)>lookback else candles
    price=sub[-1]["close"]
    min_gap=max(price*0.0003,0.3)  # Mindestgröße relativ zum Preis
    for i in range(1,len(sub)-1):
        p=sub[i-1]; n=sub[i+1]
        # Bullish FVG
        if n["low"]>p["high"] and (n["low"]-p["high"])>min_gap:
            gap=round(n["low"]-p["high"],2)
            is_filled=p["high"]<=price<=n["low"]
            fvgs.append({"type":"BFVG","top":n["low"],"bottom":p["high"],
                "mid":round((n["low"]+p["high"])/2,2),"size":gap,
                "filled":price<p["high"],"in_zone":is_filled,
                "label":f"Bullish FVG {p['high']:.2f}–{n['low']:.2f} ({gap:.2f} Pkt)",
                "direction":"SUPPORT"})
        # Bearish FVG
        if p["low"]>n["high"] and (p["low"]-n["high"])>min_gap:
            gap=round(p["low"]-n["high"],2)
            is_filled=n["high"]<=price<=p["low"]
            fvgs.append({"type":"BAFVG","top":p["low"],"bottom":n["high"],
                "mid":round((p["low"]+n["high"])/2,2),"size":gap,
                "filled":price>p["low"],"in_zone":is_filled,
                "label":f"Bearish FVG {n['high']:.2f}–{p['low']:.2f} ({gap:.2f} Pkt)",
                "direction":"RESISTANCE"})
    # Unfüllte FVGs priorisieren, max 8
    unfilled=[f for f in fvgs if not f["filled"]]
    return sorted(unfilled,key=lambda x:x["size"],reverse=True)[:8]

def detect_bos_choch(candles):
    """
    Break of Structure (BOS): Strukturbruch in Trendrichtung → Fortsetzung
    Change of Character (CHoCH): Strukturbruch gegen Trend → potenzielle Umkehr!
    """
    if len(candles)<15: return {"bos":None,"choch":None,"structure":"UNDEFINED","last_high":None,"last_low":None}
    sub=candles[-25:] if len(candles)>25 else candles
    price=sub[-1]["close"]
    # Swing Highs/Lows finden
    sh=[]; sl_=[]
    for i in range(2,len(sub)-2):
        if sub[i]["high"]>sub[i-1]["high"] and sub[i]["high"]>sub[i-2]["high"] and \
           sub[i]["high"]>sub[i+1]["high"] and sub[i]["high"]>sub[i+2]["high"]:
            sh.append(round(sub[i]["high"],2))
        if sub[i]["low"]<sub[i-1]["low"] and sub[i]["low"]<sub[i-2]["low"] and \
           sub[i]["low"]<sub[i+1]["low"] and sub[i]["low"]<sub[i+2]["low"]:
            sl_.append(round(sub[i]["low"],2))
    if len(sh)<2 or len(sl_)<2:
        return {"bos":None,"choch":None,"structure":"UNDEFINED",
                "last_high":round(max(c["high"] for c in sub[-5:]),2),
                "last_low":round(min(c["low"] for c in sub[-5:]),2)}
    lh=sh[-1]; ph=sh[-2]; ll=sl_[-1]; pl=sl_[-2]
    hh=lh>ph; hl=ll>pl; lhigh=lh<ph; ll_=ll<pl
    bos=None; choch=None
    if hh and hl: structure="UPTREND ▲"
    elif lhigh and ll_: structure="DOWNTREND ▼"
    else: structure="RANGING ↔"
    # BOS/CHoCH erkennen
    if "UPTREND" in structure:
        if price>lh: bos={"label":f"BOS ↑ über {lh:.2f}","level":lh,"dir":"BUY","type":"BOS"}
        if price<ll: choch={"label":f"⚠ CHoCH! Unter {ll:.2f} → Umkehr bearish?","level":ll,"dir":"SELL","type":"CHoCH"}
    elif "DOWNTREND" in structure:
        if price<ll: bos={"label":f"BOS ↓ unter {ll:.2f}","level":ll,"dir":"SELL","type":"BOS"}
        if price>lh: choch={"label":f"⚠ CHoCH! Über {lh:.2f} → Umkehr bullish?","level":lh,"dir":"BUY","type":"CHoCH"}
    return {"bos":bos,"choch":choch,"structure":structure,
            "last_high":lh,"last_low":ll,"prev_high":ph,"prev_low":pl}

def calc_premium_discount(candles, price):
    """
    Premium/Discount Zone (SMC-Konzept):
    > 75% der Range = Premium (teuer → gut zum Verkaufen)
    50% = Equilibrium
    < 25% der Range = Discount (günstig → gut zum Kaufen)
    """
    if len(candles)<5 or not price:
        return {"zone":"UNBEKANNT","pct":50.0,"equilibrium":price}
    sub=candles[-30:] if len(candles)>30 else candles
    hi=max(c["high"] for c in sub); lo=min(c["low"] for c in sub)
    if hi==lo: return {"zone":"EQUILIBRIUM","pct":50.0,"high":hi,"low":lo,"equilibrium":round(hi,2)}
    pct=round((price-lo)/(hi-lo)*100,1)
    if pct>=75:   zone="PREMIUM 🔴 (Verkaufen)"
    elif pct>=60: zone="LEICHT PREMIUM"
    elif pct>=40: zone="EQUILIBRIUM ⚖"
    elif pct>=25: zone="LEICHT DISCOUNT"
    else:         zone="DISCOUNT 🟢 (Kaufen)"
    return {"zone":zone,"pct":pct,"high":round(hi,2),"low":round(lo,2),
            "equilibrium":round((hi+lo)/2,2),"range":round(hi-lo,2)}

def detect_institutional_moves(candles, inds):
    """
    Institutionelle Muster:
    - Stop Hunt / Liquidity Sweep: Spike über/unter Level, schnelle Umkehr
    - Impulse-Kerze: Starke Kerze mit wenig Docht = Institutioneller Kauf/Verkauf
    - Accumulation: Seitwärts mit verdichtetem Volumen (Range vor Ausbruch)
    - Rejection: Langer Docht = Preis wurde aktiv abgelehnt
    """
    if len(candles)<5: return []
    moves=[]; sub=candles[-15:] if len(candles)>15 else candles
    atr_v=inds.get("atr",20) or 20; price=inds.get("price") or sub[-1]["close"]
    for i in range(1,len(sub)):
        c=sub[i]; prev=sub[i-1]
        rng=c["high"]-c["low"]
        if rng==0: continue
        body=abs(c["close"]-c["open"])
        up_wick=c["high"]-max(c["close"],c["open"])
        dn_wick=min(c["close"],c["open"])-c["low"]
        body_ratio=body/rng
        # Stop Hunt nach oben (langer oberer Docht → bearish Umkehr)
        if up_wick>body*2.5 and rng>atr_v*0.6:
            moves.append({"type":"STOP_HUNT","dir":"BEARISH",
                "label":f"🔴 Stop Hunt ↑ @ {c['high']:.2f} (langer Docht oben → Umkehr möglich)",
                "level":c["high"],"strength":"HOCH"})
        # Stop Hunt nach unten (langer unterer Docht → bullish Umkehr)
        if dn_wick>body*2.5 and rng>atr_v*0.6:
            moves.append({"type":"STOP_HUNT","dir":"BULLISH",
                "label":f"🟢 Stop Hunt ↓ @ {c['low']:.2f} (langer Docht unten → Umkehr möglich)",
                "level":c["low"],"strength":"HOCH"})
        # Institutionelle Impulse-Kerze (großer Body, wenig Docht)
        if body>atr_v*1.5 and body_ratio>0.75:
            d="BULLISH ▲" if c["close"]>c["open"] else "BEARISH ▼"
            moves.append({"type":"IMPULSE","dir":d,
                "label":f"⚡ Institutioneller Impuls {d} ({body:.1f} Pkt, Body {body_ratio*100:.0f}%)",
                "level":c["close"],"strength":"MITTEL"})
        # Rejection Block (Preis wurde scharf abgelehnt)
        if (up_wick>atr_v*0.8 or dn_wick>atr_v*0.8) and body<rng*0.3:
            dir_="BEARISH" if up_wick>dn_wick else "BULLISH"
            lv=c["high"] if dir_=="BEARISH" else c["low"]
            moves.append({"type":"REJECTION","dir":dir_,
                "label":f"↩ Rejection {dir_} @ {lv:.2f} (Preis abgelehnt)",
                "level":lv,"strength":"MITTEL"})
    return moves[-6:] if len(moves)>6 else moves

def update_smc_analysis():
    """Führt alle SMC-Analysen durch und speichert Ergebnisse in bot_state."""
    price=bot_state.get("price")
    candles=bot_state["candles"].get("1h",[])
    candles_4h=bot_state["candles"].get("4h",[])
    inds=bot_state.get("indicators",{})
    if not price or len(candles)<10: return
    smc=bot_state["smc"]
    # Alle Analysen ausführen
    smc["order_blocks"]=find_order_blocks(candles,60)
    smc["liquidity_zones"]=find_liquidity_zones(candles,price,60)
    smc["fair_value_gaps"]=find_fair_value_gaps(candles,40)
    smc["bos_choch"]=detect_bos_choch(candles)
    smc["premium_discount"]=calc_premium_discount(candles,price)
    smc["institutional_moves"]=detect_institutional_moves(candles,inds)
    # Nächsten Order Block finden
    active_obs=[ob for ob in smc["order_blocks"] if ob["active"]]
    if active_obs:
        nearest=min(active_obs,key=lambda x:abs(x["mid"]-price))
        smc["nearest_ob"]=nearest
    else: smc["nearest_ob"]=None
    # Nächste Liquiditätszone
    if smc["liquidity_zones"]:
        smc["nearest_lz"]=smc["liquidity_zones"][0]
    # SMC-Bias bestimmen
    pd=smc["premium_discount"]; boc=smc["bos_choch"]; nob=smc["nearest_ob"]
    score=0
    if "DISCOUNT" in pd.get("zone",""): score+=2
    if "PREMIUM" in pd.get("zone",""): score-=2
    if boc.get("bos") and boc["bos"].get("dir")=="BUY": score+=2
    if boc.get("bos") and boc["bos"].get("dir")=="SELL": score-=2
    if boc.get("choch") and boc["choch"].get("dir")=="BUY": score+=1
    if boc.get("choch") and boc["choch"].get("dir")=="SELL": score-=1
    if nob and nob["type"]=="BULLISH_OB" and abs(price-nob["mid"])<10: score+=2
    if nob and nob["type"]=="BEARISH_OB" and abs(price-nob["mid"])<10: score-=2
    # Bullishe FVGs unter Preis (Preismagnet nach unten = kann zurückfallen)
    bfvg_below=[f for f in smc["fair_value_gaps"] if f["type"]=="BFVG" and f["mid"]<price]
    if bfvg_below: score+=1
    smc["smc_score"]=score
    if score>=3:    smc["smc_bias"]="BULLISH 🟢"
    elif score<=-3: smc["smc_bias"]="BEARISH 🔴"
    else:           smc["smc_bias"]="NEUTRAL ⚪"
    smc["last_updated"]=datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
    add_log(f"SMC: {smc['smc_bias']} | PD:{pd.get('zone','?')} | OBs:{len(active_obs)} | LZs:{len(smc['liquidity_zones'])} | FVGs:{len(smc['fair_value_gaps'])}","INFO")

def analysis_loop():
    add_log("XAUUSD KI-Bot v4.0 — 4 Strategien, Macro-Analyse, Guardrails, Tab-Dashboard","INFO")
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
                check_willy_open_signals(price)
                if len(bot_state["prices"])>=30:
                    c1h=bot_state["candles"].get("1h",[])
                    inds=build_indicators(bot_state["prices"],c1h); bot_state["indicators"]=inds
                    sig,conf,bull,bear,strategy,conf_data,failed=evaluate_signal(inds,c1h)
                    bot_state["stats"]["total_signals"]+=1
                    if sig=="BUY":  bot_state["stats"]["buy_signals"]+=1
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
                    size_mult=bot_state["macro_state"].get("size_multiplier",1.0) if strategy=="MACRO_STRUCTURE" else 1.0
                    entry={"time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                           "date":datetime.datetime.utcnow().strftime("%d.%m.%Y"),
                           "signal":sig,"confidence":conf,"price":price,"reasons":bull,"counter_reasons":bear,
                           "atr":atr_v,"strategy":strategy,"trade_type":tt,
                           "sl":round(price-1.5*atr_v,2) if sig=="BUY" else round(price+1.5*atr_v,2) if sig=="SELL" else None,
                           "tp1":round(price+1.5*atr_v,2) if sig=="BUY" else round(price-1.5*atr_v,2) if sig=="SELL" else None,
                           "tp2":round(price+3.0*atr_v,2) if sig=="BUY" else round(price-3.0*atr_v,2) if sig=="SELL" else None,
                           "confirmations_passed":len(passed),"willy_confirmed":bot_state["willy_last"] is not None,
                           "session":bot_state["session"],"dxy":bot_state.get("dxy"),"yields":bot_state.get("yields_10y")}
                    bot_state["last_signal"]=entry; bot_state["signals"].insert(0,entry)
                    if len(bot_state["signals"])>500: bot_state["signals"].pop()
                    if sig!="WARTEN" and not bot_state["open_trade"]:
                        open_trade(sig,price,atr_v,dict(inds),strategy,tt,passed,size_mult)
                    bot_state["learning"]["total"]+=1
                    if sig in ["BUY","SELL"]: bot_state["learning"]["wins"]+=1
                    t2=bot_state["learning"]["total"]
                    bot_state["learning"]["accuracy"]=round(bot_state["learning"]["wins"]/t2*100,1) if t2>0 else 0
                    add_log(f"{sig} [{strategy}] {tt} | {conf}% | {price} | Conf:{len(passed)}/{bot_state['confirmations'].get('required',5)} | {bot_state['session']}","SIGNAL" if sig!="WARTEN" else "INFO")
                else:
                    add_log(f"Preis:{price} | Sammle Daten ({len(bot_state['prices'])}/30)","INFO")
        except Exception as e:
            add_log(f"Loop-Fehler: {e}","ERROR")
        time.sleep(300)

# ═══════════════════════════════════════════════════════
# DASHBOARD v4.0 — 5 Tabs (Gesamt + 4 Strategien)
# ═══════════════════════════════════════════════════════
DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD KI-Bot v4.0</title>
<style>
:root{--bg:#0b0f1a;--pn:#111827;--bd:#1f2d45;--tx:#e8edf5;--dm:#8899b0;--ft:#4b5a70;
  --gr:#34d399;--rd:#f87171;--am:#fbbf24;--bl:#60a5fa;--pu:#c084fc;--tl:#2dd4bf;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,"Helvetica Neue",Helvetica,sans-serif;background:var(--bg);color:var(--tx);
  font-size:14px;line-height:1.55;padding:16px;-webkit-font-smoothing:antialiased;}
/* Header */
.hdr{background:var(--pn);border:1px solid var(--bd);border-radius:10px;padding:12px 18px;
  margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;}
.logo{font-size:17px;font-weight:700;color:var(--am);}
.sub{font-size:11px;color:var(--ft);margin-top:2px;}
.bdg{display:flex;gap:5px;flex-wrap:wrap;}
.b{padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;}
.bg{background:#0a2017;color:var(--gr);border:1px solid #1a5035;}
.bb{background:#0c1a35;color:var(--bl);border:1px solid #1e3a6a;}
.ba{background:#271c06;color:var(--am);border:1px solid #66480f;}
.br{background:#270f0f;color:var(--rd);border:1px solid #6b1e1e;}
.bp{background:#1e1030;color:var(--pu);border:1px solid #5b2d8a;}
.bc{background:#0a2220;color:var(--tl);border:1px solid #1a5550;}
/* Tab-Navigation */
.tabs{display:flex;gap:4px;margin-bottom:14px;flex-wrap:wrap;}
.tab{padding:9px 18px;border-radius:7px;font-size:13px;font-weight:700;cursor:pointer;
  background:var(--pn);border:1px solid var(--bd);color:var(--dm);transition:.2s;}
.tab:hover{color:var(--tx);border-color:var(--dm);}
.tab.active{color:var(--tx);border-color:var(--am);background:#1a1400;}
.tab-mr.active{border-color:var(--bl);background:#0c1430;}
.tab-tf.active{border-color:var(--gr);background:#0a1f14;}
.tab-bo.active{border-color:var(--am);background:#1a1400;}
.tab-ms.active{border-color:var(--pu);background:#150e28;}
.tab-st.active{border-color:var(--tl);background:#0a1a18;}
.tc{display:none;}.tc.active{display:block;}
/* Layout */
.g5{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:12px;}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px;}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;}
.pn{background:var(--pn);border:1px solid var(--bd);border-radius:9px;padding:14px;}
.pt{font-size:10.5px;font-weight:700;color:var(--ft);letter-spacing:1px;text-transform:uppercase;
  margin-bottom:10px;display:flex;align-items:center;gap:6px;}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.dg{background:var(--gr);box-shadow:0 0 5px var(--gr);}
.da{background:var(--am);box-shadow:0 0 5px var(--am);}
.db{background:var(--bl);box-shadow:0 0 5px var(--bl);}
.dp{background:var(--pu);box-shadow:0 0 5px var(--pu);}
.dc{background:var(--tl);box-shadow:0 0 5px var(--tl);}
.big{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;}
.sv{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;}
.pos{color:var(--gr);}.neg{color:var(--rd);}.neu{color:var(--dm);}.amr{color:var(--am);}
.pur{color:var(--pu);}.cyn{color:var(--tl);}.blu{color:var(--bl);}
.sm{text-align:center;}
.lbl{font-size:10.5px;color:var(--ft);letter-spacing:.4px;margin-bottom:5px;}
.meta{font-size:12px;color:var(--dm);margin-top:4px;}
.row{display:flex;justify-content:space-between;align-items:center;
  padding:7px 0;border-bottom:1px solid var(--bd);font-size:13px;}
.row:last-child{border-bottom:none;}
.rk{color:var(--dm);}.rv{font-weight:600;font-variant-numeric:tabular-nums;}
.pb{background:var(--bd);border-radius:4px;height:6px;margin:5px 0;overflow:hidden;}
.pf{height:100%;border-radius:4px;transition:width .5s;}
.pg{background:linear-gradient(90deg,#1a5035,#34d399);}
.pr{background:linear-gradient(90deg,#6b1e1e,#f87171);}
.pb2{background:linear-gradient(90deg,#1e3a6a,#60a5fa);}
.pa{background:linear-gradient(90deg,#66480f,#fbbf24);}
.pp{background:linear-gradient(90deg,#5b2d8a,#c084fc);}
.sbox{padding:12px;border-radius:7px;border:1px solid;margin-bottom:6px;}
.sbuy{background:#0a2017;border-color:#1a5035;}
.ssell{background:#270f0f;border-color:#6b1e1e;}
.swait{background:#1f1800;border-color:#66480f;}
.dk{background:#0d1625;border:1px solid var(--bd);border-radius:8px;padding:12px;text-align:center;}
.dk .dv{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:4px;}
.sec{font-size:11px;font-weight:700;letter-spacing:1.2px;color:var(--ft);text-transform:uppercase;
  padding:14px 0 8px;border-bottom:1px solid var(--bd);margin-bottom:12px;}
.cfp{display:inline-block;background:#0a2017;color:var(--gr);border:1px solid #1a5035;
  border-radius:4px;font-size:11px;padding:2px 7px;margin:2px;}
.cff{display:inline-block;background:#270f0f;color:var(--rd);border:1px solid #6b1e1e;
  border-radius:4px;font-size:11px;padding:2px 7px;margin:2px;}
.strat-card{background:var(--pn);border:2px solid var(--bd);border-radius:10px;padding:16px;}
.strat-card.mr{border-color:#1e3a6a;}.strat-card.tf{border-color:#1a5035;}
.strat-card.bo{border-color:#66480f;}.strat-card.ms{border-color:#5b2d8a;}
.pnl-big{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;margin:8px 0;}
.alert{display:none;border:1px solid #6b1e1e;background:#270f0f;border-radius:7px;
  padding:10px 14px;margin-bottom:12px;font-size:13px;color:var(--rd);font-weight:600;}
.gd-ok{color:var(--gr);}.gd-warn{color:var(--am);}.gd-stop{color:var(--rd);}
.tw{overflow-x:auto;}
table{width:100%;border-collapse:collapse;font-size:12.5px;min-width:640px;}
th{color:var(--ft);font-weight:700;padding:7px 8px;border-bottom:1px solid var(--bd);
  text-align:left;font-size:11px;letter-spacing:.5px;white-space:nowrap;}
td{padding:7px 8px;border-bottom:1px solid #0d1420;font-variant-numeric:tabular-nums;white-space:nowrap;}
.le{font-size:12px;padding:5px 0;border-bottom:1px solid #0d1420;line-height:1.5;}
.le .t{color:var(--ft);margin-right:6px;}
.pulse{animation:pulse 2s infinite;}
.blink{animation:blink 1s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
@media(max-width:900px){.g5,.g4{grid-template-columns:repeat(2,1fr);}.g3{grid-template-columns:1fr 1fr;}.g2{grid-template-columns:1fr;}}
</style>
</head>
<body>

<!-- HEADER -->
<div class="hdr">
  <div>
    <div class="logo">⚡ XAUUSD KI-Bot v4.0</div>
    <div class="sub">4 Strategien · Macro-Struktur-Analyse · Guardrails · Confirmations · SHORT/LONG · Demo-Konto €1.000</div>
  </div>
  <div class="bdg">
    <span class="b bg"><span class="blink">●</span> LIVE</span>
    <span class="b bb" id="clk">—</span>
    <span class="b ba" id="sess-b">—</span>
    <span class="b ba" id="last-upd">Warte...</span>
    <span class="b bp" id="willy-b">WILLY: —</span>
    <span class="b bc" id="gr-status">GUARDRAIL: OK</span>
  </div>
</div>

<div class="alert" id="news-alert">⚠ News-Sperre: <span id="news-reason">—</span></div>

<!-- TAB NAVIGATION -->
<div class="tabs">
  <button class="tab active"        onclick="showTab('t-gesamt',this)">📊 Gesamt</button>
  <button class="tab tab-mr"        onclick="showTab('t-mr',this)">🔵 Mean Reversion</button>
  <button class="tab tab-tf"        onclick="showTab('t-tf',this)">🟢 Trend Follow</button>
  <button class="tab tab-bo"        onclick="showTab('t-bo',this)">🟡 Breakout</button>
  <button class="tab tab-ms"        onclick="showTab('t-ms',this)">🟣 Macro Struktur</button>
  <button class="tab"               onclick="showTab('t-willy',this)" style="border-color:#f59e0b">⭐ WillyAlgoTrader</button>
  <button class="tab tab-st"        onclick="showTab('t-stats',this)">📈 Statistiken</button>
</div>

<!-- ══════════════════════════════════════
     TAB 1: GESAMT
══════════════════════════════════════ -->
<div id="t-gesamt" class="tc active">
<div class="sec">Markt &amp; Aktuelles Signal</div>
<div class="g5">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>XAUUSD Preis</div>
    <div class="big amr" id="price">—</div>
    <div class="meta">ATR <b id="atr">—</b> · ADX <b id="adx">—</b></div>
    <div class="meta" id="ov-trend">Gesamttrend: —</div>
    <div style="font-size:10.5px;color:var(--ft);margin-top:4px" id="price-src">—</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>Signal</div>
    <div id="sig-box" class="sbox swait">
      <div style="font-size:16px;font-weight:700" id="sig-t">WARTEN</div>
      <div style="font-size:12px;color:var(--dm);margin-top:3px" id="sig-c">Warte...</div>
      <div style="font-size:12px;margin-top:3px" id="sig-lvl"></div>
    </div>
    <div class="meta" id="sig-meta">Typ: — · Strategie: —</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Win Rate (Gesamt)</div>
    <div class="big pos" id="winrate">—</div>
    <div class="pb"><div class="pf pg" id="wr-bar" style="width:0%"></div></div>
    <div class="meta"><b id="wins">0</b>W · <b id="losses">0</b>L · <b id="total-t">0</b> Trades</div>
    <div class="meta pur">Vermieden: <b id="avoided">0</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg"></span>P&amp;L Gesamt (Punkte)</div>
    <div class="big" id="total-pnl">+0.00 Pkt</div>
    <div class="meta">Best <b id="best" class="pos">—</b> · Worst <b id="worst" class="neg">—</b></div>
    <div class="meta">SHORT <b id="sh-t">0</b> · LONG <b id="lo-t">0</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dc"></span>Intermarket</div>
    <div class="row"><span class="rk">DXY</span><span class="rv amr" id="dxy">—</span></div>
    <div class="row"><span class="rk">DXY Trend</span><span class="rv" id="dxy-trend">—</span></div>
    <div class="row"><span class="rk">10Y Yields</span><span class="rv amr" id="yields">—</span></div>
    <div class="row"><span class="rk">Yields Trend</span><span class="rv" id="yields-trend">—</span></div>
    <div class="row"><span class="rk">Gold/DXY Korr.</span><span class="rv neu" id="corr">—</span></div>
  </div>
</div>

<div class="sec">Demo-Konto · €1.000 Start · 5% Risiko/Trade · Max. 1:5 Hebel</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g5" style="margin-bottom:10px">
    <div class="dk"><div class="lbl">Kontostand</div><div class="dv" id="da-balance">€1.000,00</div></div>
    <div class="dk"><div class="lbl">Eigenkapital (live)</div><div class="dv" id="da-equity">€1.000,00</div></div>
    <div class="dk"><div class="lbl">Gesamt P&amp;L</div><div class="dv" id="da-pnl">+0,00€</div></div>
    <div class="dk"><div class="lbl">Rendite seit Start</div><div class="dv" id="da-return">+0,00%</div></div>
    <div class="dk"><div class="lbl">Max. Drawdown</div><div class="dv" id="da-dd">0,00%</div></div>
  </div>
  <div class="g4" style="margin-bottom:8px">
    <div class="row" style="padding:5px 0"><span class="rk">Hebel</span><span class="rv" id="da-lev">1:0 / max 1:5</span></div>
    <div class="row" style="padding:5px 0"><span class="rk">Margin verw./frei</span><span class="rv" id="da-margin">—</span></div>
    <div class="row" style="padding:5px 0"><span class="rk">Trades · Win-Rate</span><span class="rv" id="da-stats">0 · —</span></div>
    <div class="row" style="padding:5px 0"><span class="rk">Abgelehnte Trades</span><span class="rv neg" id="da-rejected">0</span></div>
  </div>
  <div style="font-size:11px;color:var(--ft);border-top:1px solid var(--bd);padding-top:8px">
    1 USD ≈ 1 EUR (vereinfacht) · 1 Lot = 100 oz · 5% Risiko, Max. 1:5 Hebel strikt eingehalten
  </div>
</div>

<div class="sec">Guardrails &amp; Confirmations</div>
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>Guardrails (Sicherheits-Ebene)</div>
    <div class="row"><span class="rk">Status</span><span class="rv" id="gr-stat-txt">OK</span></div>
    <div class="row"><span class="rk">Tages-Drawdown</span><span class="rv" id="gr-daily">0,00%</span></div>
    <div class="row"><span class="rk">Wochen-Drawdown</span><span class="rv" id="gr-weekly">0,00%</span></div>
    <div class="row"><span class="rk">Tages P&amp;L (€)</span><span class="rv" id="gr-day-pnl">+0,00€</span></div>
    <div class="row"><span class="rk">Wochen P&amp;L (€)</span><span class="rv" id="gr-week-pnl">+0,00€</span></div>
    <div style="font-size:11px;color:var(--ft);margin-top:8px">Tagesverlust ≥3% → Pause · Wochenverlust ≥6% → Review</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg"></span>Bestätigungs-System (<span id="conf-count-g">0</span>/<span id="conf-req-g">5</span>)</div>
    <div class="pb"><div class="pf pg" id="conf-bar-g" style="width:0%"></div></div>
    <div id="conf-passed-g" style="margin-top:6px"></div>
    <div id="conf-failed-g" style="margin-top:4px"></div>
  </div>
</div>

<div class="sec">Offener Trade &amp; WillyAlgoTrader</div>
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Offener Trade</div>
    <div id="open-trade" style="font-size:13px;color:var(--dm)">Kein offener Trade</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dp"></span>WillyAlgoTrader</div>
    <div class="g4" style="margin-bottom:6px">
      <div class="sm"><div class="sv" id="w-sig" style="font-size:15px">—</div><div class="lbl">Signal</div></div>
      <div class="sm"><div class="sv neu" id="w-tf">—</div><div class="lbl">TF</div></div>
      <div class="sm"><div class="sv neu" id="w-sc">—</div><div class="lbl">Score</div></div>
      <div class="sm"><div class="sv amr" id="w-cnt">0</div><div class="lbl">Total</div></div>
    </div>
    <div style="font-size:12px;color:var(--ft)" id="w-tps">—</div>
  </div>
</div>
</div><!-- /t-gesamt -->

<!-- ══════════════════════════════════════
     TAB 2: MEAN REVERSION
══════════════════════════════════════ -->
<div id="t-mr" class="tc">
<div class="sec">Mean Reversion — Seitwärtsstrategie · BB + RSI + Stochastic</div>
<div class="g3">
  <div class="strat-card mr">
    <div class="lbl" style="color:var(--bl)">MEAN REVERSION — EIGENER P&amp;L</div>
    <div class="pnl-big blu" id="mr-pnl">+0.00 Pkt</div>
    <div class="meta">In Euro: <b id="mr-eur">+0.00€</b></div>
    <div class="pb"><div class="pf pb2" id="mr-wr-bar" style="width:0%"></div></div>
    <div class="meta"><b id="mr-wins">0</b>W · <b id="mr-losses">0</b>L · <b id="mr-trades">0</b> Trades · Win-Rate: <b id="mr-wr">—</b></div>
    <div class="meta">Best: <b id="mr-best" class="pos">—</b> · Worst: <b id="mr-worst" class="neg">—</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Score &amp; Indikatoren</div>
    <div class="sm" style="margin-bottom:10px">
      <div class="lbl" style="color:var(--bl)">AKTUELLER SCORE</div>
      <div class="big blu" id="sc-mr">0</div>
      <div class="pb"><div class="pf pb2" id="bar-mr" style="width:0%"></div></div>
    </div>
    <div class="row"><span class="rk">RSI (14)</span><span class="rv" id="mr-rsi">—</span></div>
    <div class="row"><span class="rk">Stochastic K/D</span><span class="rv" id="mr-stoch">—</span></div>
    <div class="row"><span class="rk">BB Oben/Mitte/Unten</span><span class="rv" id="mr-bb">—</span></div>
    <div class="row"><span class="rk">ADX</span><span class="rv" id="mr-adx">—</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>Erklärung</div>
    <div style="font-size:13px;color:var(--dm);line-height:1.8">
      <b style="color:var(--tx)">Wann aktiv:</b> Seitwärts­phasen (ADX &lt; 25)<br>
      <b style="color:var(--tx)">BUY-Signal:</b> Preis unter BB-Unterkante + RSI &lt; 30 + Stoch &lt; 20<br>
      <b style="color:var(--tx)">SELL-Signal:</b> Preis über BB-Oberkante + RSI &gt; 70 + Stoch &gt; 80<br>
      <b style="color:var(--tx)">Idee:</b> Gold kehrt zum Mittelwert zurück, besonders in der Asien-Session
    </div>
    <div style="border-top:1px solid var(--bd);margin-top:10px;padding-top:10px">
      <div class="lbl">SIGNAL-GRÜNDE (aktuell)</div>
      <div id="mr-sigs" style="font-size:13px;color:var(--bl);line-height:1.8;margin-top:4px">—</div>
    </div>
  </div>
</div>
</div><!-- /t-mr -->

<!-- ══════════════════════════════════════
     TAB 3: TREND FOLLOW
══════════════════════════════════════ -->
<div id="t-tf" class="tc">
<div class="sec">Trend Follow — Momentum-Strategie · EMA-Stack + MACD + ADX</div>
<div class="g3">
  <div class="strat-card tf">
    <div class="lbl" style="color:var(--gr)">TREND FOLLOW — EIGENER P&amp;L</div>
    <div class="pnl-big pos" id="tf-pnl">+0.00 Pkt</div>
    <div class="meta">In Euro: <b id="tf-eur">+0.00€</b></div>
    <div class="pb"><div class="pf pg" id="tf-wr-bar" style="width:0%"></div></div>
    <div class="meta"><b id="tf-wins">0</b>W · <b id="tf-losses">0</b>L · <b id="tf-trades">0</b> Trades · Win-Rate: <b id="tf-wr">—</b></div>
    <div class="meta">Best: <b id="tf-best" class="pos">—</b> · Worst: <b id="tf-worst" class="neg">—</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg"></span>Score &amp; Indikatoren</div>
    <div class="sm" style="margin-bottom:10px">
      <div class="lbl" style="color:var(--gr)">AKTUELLER SCORE</div>
      <div class="big pos" id="sc-tf">0</div>
      <div class="pb"><div class="pf pg" id="bar-tf" style="width:0%"></div></div>
    </div>
    <div class="row"><span class="rk">EMA 20/50/200</span><span class="rv" id="tf-emas">—</span></div>
    <div class="row"><span class="rk">MACD / Signal</span><span class="rv" id="tf-macd">—</span></div>
    <div class="row"><span class="rk">ADX</span><span class="rv" id="tf-adx">—</span></div>
    <div class="row"><span class="rk">Momentum</span><span class="rv" id="tf-mom">—</span></div>
    <div class="row"><span class="rk">DXY Trend</span><span class="rv" id="tf-dxy">—</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>Erklärung</div>
    <div style="font-size:13px;color:var(--dm);line-height:1.8">
      <b style="color:var(--tx)">Wann aktiv:</b> Klare Trends (ADX &gt; 25)<br>
      <b style="color:var(--tx)">BUY-Signal:</b> Preis &gt; EMA20 &gt; EMA50 &gt; EMA200 + MACD bullish<br>
      <b style="color:var(--tx)">SELL-Signal:</b> Preis &lt; EMA20 &lt; EMA50 &lt; EMA200 + MACD bearish<br>
      <b style="color:var(--tx)">Idee:</b> Auf laufende Trends aufspringen, DXY als Bestätigung
    </div>
    <div style="border-top:1px solid var(--bd);margin-top:10px;padding-top:10px">
      <div class="lbl">SIGNAL-GRÜNDE (aktuell)</div>
      <div id="tf-sigs" style="font-size:13px;color:var(--gr);line-height:1.8;margin-top:4px">—</div>
    </div>
  </div>
</div>
</div><!-- /t-tf -->

<!-- ══════════════════════════════════════
     TAB 4: BREAKOUT
══════════════════════════════════════ -->
<div id="t-bo" class="tc">
<div class="sec">Breakout — Ausbruchsstrategie · Volumen-Filter + Session + Levels</div>
<div class="g3">
  <div class="strat-card bo">
    <div class="lbl" style="color:var(--am)">BREAKOUT — EIGENER P&amp;L</div>
    <div class="pnl-big amr" id="bo-pnl">+0.00 Pkt</div>
    <div class="meta">In Euro: <b id="bo-eur">+0.00€</b></div>
    <div class="pb"><div class="pf pa" id="bo-wr-bar" style="width:0%"></div></div>
    <div class="meta"><b id="bo-wins">0</b>W · <b id="bo-losses">0</b>L · <b id="bo-trades">0</b> Trades · Win-Rate: <b id="bo-wr">—</b></div>
    <div class="meta">Best: <b id="bo-best" class="pos">—</b> · Worst: <b id="bo-worst" class="neg">—</b></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot da"></span>Score &amp; Indikatoren</div>
    <div class="sm" style="margin-bottom:10px">
      <div class="lbl" style="color:var(--am)">AKTUELLER SCORE</div>
      <div class="big amr" id="sc-bo">0</div>
      <div class="pb"><div class="pf pa" id="bar-bo" style="width:0%"></div></div>
    </div>
    <div class="row"><span class="rk">Session</span><span class="rv amr" id="bo-sess">—</span></div>
    <div class="row"><span class="rk">Volumen-Ratio</span><span class="rv" id="bo-vol">—</span></div>
    <div class="row"><span class="rk">POC</span><span class="rv amr" id="bo-poc">—</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot da pulse"></span>Erklärung</div>
    <div style="font-size:13px;color:var(--dm);line-height:1.8">
      <b style="color:var(--tx)">BUY:</b> Ausbruch über Vorperioden-Hoch + Vol &gt;1.5× Ø<br>
      <b style="color:var(--tx)">SELL:</b> Ausbruch unter Vorperioden-Tief + Bestätigung<br>
      <b style="color:var(--tx)">Fake-Ausbruch-Filter:</b> Bei Volumen &lt; 0.8× Ø wird Score reduziert<br>
      <b style="color:var(--tx)">Session-Bonus:</b> London/NY-Open für höheren Impuls
    </div>
    <div style="border-top:1px solid var(--bd);margin-top:10px;padding-top:10px">
      <div class="lbl">SIGNAL-GRÜNDE (aktuell)</div>
      <div id="bo-sigs" style="font-size:13px;color:var(--am);line-height:1.8;margin-top:4px">—</div>
    </div>
  </div>
</div>
</div><!-- /t-bo -->

<!-- ══════════════════════════════════════
     TAB 5: MACRO STRUKTUR (NEU)
══════════════════════════════════════ -->
<div id="t-ms" class="tc">
<div class="sec">Macro-Struktur — Neue Strategie nach System-Spezifikation · Bias + Struktur + Setup A/B/C</div>
<div class="g3" style="margin-bottom:12px">
  <div class="strat-card ms">
    <div class="lbl" style="color:var(--pu)">MACRO STRUKTUR — EIGENER P&amp;L</div>
    <div class="pnl-big pur" id="ms-pnl">+0.00 Pkt</div>
    <div class="meta">In Euro: <b id="ms-eur">+0.00€</b></div>
    <div class="pb"><div class="pf pp" id="ms-wr-bar" style="width:0%"></div></div>
    <div class="meta"><b id="ms-wins">0</b>W · <b id="ms-losses">0</b>L · <b id="ms-trades">0</b> Trades · Win-Rate: <b id="ms-wr">—</b></div>
    <div class="meta">Best: <b id="ms-best" class="pos">—</b> · Worst: <b id="ms-worst" class="neg">—</b></div>
    <div style="margin-top:10px;border-top:1px solid var(--bd);padding-top:8px">
      <div class="lbl">AKTUELLER SCORE</div>
      <div class="big pur" id="sc-ms">0</div>
      <div class="pb"><div class="pf pp" id="bar-ms" style="width:0%"></div></div>
    </div>
  </div>

  <div class="pn">
    <div class="pt"><span class="dot dp"></span>Macro-Bias (Spec 4.1)</div>
    <div class="row"><span class="rk">Bias</span><span class="rv" id="ms-bias">—</span></div>
    <div class="row"><span class="rk">Bias-Score</span><span class="rv" id="ms-bias-score">—</span></div>
    <div class="row"><span class="rk">10Y Yields Trend</span><span class="rv" id="ms-yields">—</span></div>
    <div class="row"><span class="rk">DXY Trend</span><span class="rv" id="ms-dxy">—</span></div>
    <div class="row"><span class="rk">RSI (COT-Proxy)</span><span class="rv" id="ms-rsi">—</span></div>
    <div style="border-top:1px solid var(--bd);margin-top:10px;padding-top:8px">
      <div class="lbl">Bias-Begründung</div>
      <div id="ms-bias-notes" style="font-size:12px;color:var(--dm);line-height:1.8;margin-top:4px">—</div>
    </div>
  </div>

  <div class="pn">
    <div class="pt"><span class="dot dp pulse"></span>Marktstruktur (Spec 4.2)</div>
    <div style="font-size:22px;font-weight:700;margin-bottom:8px" id="ms-struct">—</div>
    <div id="ms-struct-notes" style="font-size:13px;color:var(--dm);line-height:1.8;margin-bottom:10px">—</div>
    <div class="lbl">Aktives Setup (Spec 4.3)</div>
    <div style="font-size:18px;font-weight:700;margin:6px 0" id="ms-setup">—</div>
    <div style="font-size:12px;color:var(--dm)" id="ms-setup-info">
      <b>Setup A:</b> Pullback in Fib 38.2%–61.8% + Macro-Bestätigung<br>
      <b>Setup B:</b> Ausbruch + Retest (strukturell bestätigt)<br>
      <b>Setup C:</b> Counter-Trend bei Divergenz (0.5× Größe)
    </div>
  </div>
</div>

<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot dp"></span>Signal-Gründe (aktuell)</div>
    <div id="ms-sigs" style="font-size:13px;color:var(--pu);line-height:1.9">—</div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot da"></span>Systemspezifikation — Entscheidungspipeline</div>
    <div style="font-size:12.5px;color:var(--dm);line-height:1.9">
      <span style="color:var(--tx);font-weight:700">1. Guardrails</span> prüfen → bei Verstoß sofort STOP<br>
      <span style="color:var(--tx);font-weight:700">2. Macro-Bias</span> bestimmen (Yields, DXY, COT-Proxy, Momentum)<br>
      <span style="color:var(--tx);font-weight:700">3. Marktstruktur</span> klassifizieren (TREND_UP/DOWN/RANGE)<br>
      <span style="color:var(--tx);font-weight:700">4. Setup-Matching</span> (A: Pullback · B: Breakout · C: Counter)<br>
      <span style="color:var(--tx);font-weight:700">5. Risiko-Veto</span> (Positionsgröße, 5% Limit, 1:5 Hebel)<br>
      <span style="color:var(--tx);font-weight:700">6. Confirmations</span> ≥5 (SHORT) / ≥7 (LONG) erforderlich<br>
      <span style="color:var(--tx);font-weight:700">7. Logging</span> jeder Entscheidung mit Begründung<br>
      <span style="color:var(--ft);font-size:11px">RANGE/UNDEFINED → Kein Trade (konservatives Default)</span>
    </div>
  </div>
</div>
</div><!-- /t-ms -->

<!-- ══════════════════════════════════════
     TAB: WILLYALGOTRADER
══════════════════════════════════════ -->
<div id="t-willy" class="tc">
<div class="sec">⭐ WillyAlgoTrader — Signal-Analyse &amp; Win-Rate Tracking</div>

<!-- Gesamt-Stats -->
<div class="g5" style="margin-bottom:12px">
  <div class="dk">
    <div class="lbl">Gesamt-Signale</div>
    <div class="dv amr" id="wa-total">0</div>
  </div>
  <div class="dk">
    <div class="lbl">Win-Rate (gesamt)</div>
    <div class="dv" id="wa-wr">—</div>
  </div>
  <div class="dk">
    <div class="lbl">Gewonnen / Verloren</div>
    <div class="dv" id="wa-wl">0 / 0</div>
  </div>
  <div class="dk">
    <div class="lbl">Noch offen</div>
    <div class="dv amr" id="wa-pending">0</div>
  </div>
  <div class="dk">
    <div class="lbl">Bestes Signal</div>
    <div class="dv pur" id="wa-best">—</div>
  </div>
</div>

<!-- TP/SL Distribution -->
<div class="pn" style="margin-bottom:12px">
  <div class="pt"><span class="dot da"></span>TP/SL Verteilung — Wie weit läuft der Trade?</div>
  <div class="g4" style="margin-bottom:0">
    <div class="sm">
      <div class="lbl" style="color:var(--gr)">TP1 HITS</div>
      <div class="sv pos" id="wa-tp1">0</div>
      <div class="pb"><div class="pf pg" id="wa-tp1-bar" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div class="lbl" style="color:var(--gr)">TP2 HITS</div>
      <div class="sv pos" id="wa-tp2">0</div>
      <div class="pb"><div class="pf pg" id="wa-tp2-bar" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div class="lbl" style="color:var(--gr)">TP3 HITS</div>
      <div class="sv pos" id="wa-tp3">0</div>
      <div class="pb"><div class="pf pg" id="wa-tp3-bar" style="width:0%"></div></div>
    </div>
    <div class="sm">
      <div class="lbl" style="color:var(--rd)">SL HITS</div>
      <div class="sv neg" id="wa-sl">0</div>
      <div class="pb"><div class="pf pr" id="wa-sl-bar" style="width:0%"></div></div>
    </div>
  </div>
</div>

<!-- BUY vs SELL Win-Rate -->
<div class="g2" style="margin-bottom:12px">
  <div class="pn">
    <div class="pt"><span class="dot dg"></span>BUY-Signale Win-Rate</div>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <div class="big pos" id="wa-buy-wr">—</div>
      <div>
        <div class="meta">Signale: <b id="wa-buy-count">0</b></div>
        <div class="meta">Gewonnen: <b id="wa-buy-wins" class="pos">0</b> · Verloren: <b id="wa-buy-losses" class="neg">0</b></div>
      </div>
    </div>
    <div class="pb"><div class="pf pg" id="wa-buy-bar" style="width:0%"></div></div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px;font-size:12px;text-align:center">
      <div><div class="lbl">TP1</div><b class="pos" id="wa-buy-tp1">0</b></div>
      <div><div class="lbl">TP2</div><b class="pos" id="wa-buy-tp2">0</b></div>
      <div><div class="lbl">TP3</div><b class="pos" id="wa-buy-tp3">0</b></div>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot" style="background:var(--rd)"></span>SELL-Signale Win-Rate</div>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <div class="big neg" id="wa-sell-wr">—</div>
      <div>
        <div class="meta">Signale: <b id="wa-sell-count">0</b></div>
        <div class="meta">Gewonnen: <b id="wa-sell-wins" class="pos">0</b> · Verloren: <b id="wa-sell-losses" class="neg">0</b></div>
      </div>
    </div>
    <div class="pb"><div class="pf pr" id="wa-sell-bar" style="width:0%"></div></div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px;font-size:12px;text-align:center">
      <div><div class="lbl">TP1</div><b class="pos" id="wa-sell-tp1">0</b></div>
      <div><div class="lbl">TP2</div><b class="pos" id="wa-sell-tp2">0</b></div>
      <div><div class="lbl">TP3</div><b class="pos" id="wa-sell-tp3">0</b></div>
    </div>
  </div>
</div>

<!-- Win-Rate nach Timeframe & Score -->
<div class="g2" style="margin-bottom:12px">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Win-Rate nach Timeframe</div>
    <div id="wa-by-tf" style="font-size:13px;line-height:2">
      <span style="color:var(--ft)">Noch keine Daten — warte auf Signale</span>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dp"></span>Win-Rate nach Score/Qualität</div>
    <div id="wa-by-score" style="font-size:13px;line-height:2">
      <span style="color:var(--ft)">Noch keine Daten</span>
    </div>
  </div>
</div>

<!-- Offene Signale -->
<div class="pn" style="margin-bottom:12px">
  <div class="pt"><span class="dot da pulse"></span>Offene Signale — warten auf TP/SL</div>
  <div id="wa-open" style="font-size:13px;color:var(--dm);line-height:2">Keine offenen Signale</div>
</div>

<!-- Letzte abgeschlossene Signale -->
<div class="pn">
  <div class="pt"><span class="dot db"></span>Letzte abgeschlossene Signale</div>
  <div class="tw" style="max-height:260px;overflow-y:auto">
  <table>
    <thead><tr>
      <th>Zeit</th><th>Richtung</th><th>TF</th><th>Score</th>
      <th>Entry</th><th>TP1</th><th>TP2</th><th>SL</th>
      <th>Close</th><th>Pips</th><th>TP Hit</th><th>Ergebnis</th>
    </tr></thead>
    <tbody id="wa-history"><tr><td colspan="12" style="text-align:center;padding:10px;color:var(--ft)">Noch keine abgeschlossenen Signale</td></tr></tbody>
  </table>
  </div>
</div>
</div><!-- /t-willy -->

<!-- ══════════════════════════════════════
     TAB: STATISTIKEN
══════════════════════════════════════ -->
<div id="t-stats" class="tc">
<div class="sec">Performance-Metriken (Spec 6.1)</div>
<div class="g4" style="margin-bottom:12px">
  <div class="dk"><div class="lbl">Erwartungswert</div><div class="dv" id="perf-exp">—</div><div style="font-size:10.5px;color:var(--ft);margin-top:4px">Ø Gewinn/Verlust pro Trade</div></div>
  <div class="dk"><div class="lbl">Profit Factor</div><div class="dv" id="perf-pf">—</div><div style="font-size:10.5px;color:var(--ft);margin-top:4px">Bruttogewinn / Bruttoverlust</div></div>
  <div class="dk"><div class="lbl">Ø CRV</div><div class="dv" id="perf-crv">—</div><div style="font-size:10.5px;color:var(--ft);margin-top:4px">Durchschn. Chance/Risiko</div></div>
  <div class="dk"><div class="lbl">Win-Rate</div><div class="dv" id="perf-wr">—</div><div style="font-size:10.5px;color:var(--ft);margin-top:4px">Gewinn-Trades / Gesamt</div></div>
</div>

<div class="sec">Multi-Timeframe Trend</div>
<div class="pn" style="margin-bottom:12px">
  <div class="g4" style="margin-bottom:0">
    <div class="sm"><div class="lbl">1 STUNDE</div><div class="sv" id="t-1h">—</div>
      <div class="meta">RSI <b id="t1h-rsi">—</b> · POC <b id="t1h-poc" class="amr">—</b></div></div>
    <div class="sm"><div class="lbl">4 STUNDEN</div><div class="sv" id="t-4h">—</div>
      <div class="meta">RSI <b id="t4h-rsi">—</b> · POC <b id="t4h-poc" class="amr">—</b></div></div>
    <div class="sm"><div class="lbl">TÄGLICH</div><div class="sv" id="t-1d">—</div>
      <div class="meta">RSI <b id="t1d-rsi">—</b> · EMA200 <b id="t1d-e200" class="amr">—</b></div></div>
    <div class="sm"><div class="lbl">GESAMT</div><div class="sv" id="t-overall">—</div>
      <div class="meta">Strategie: <b id="active-strat">—</b></div></div>
  </div>
</div>

<div class="sec">Alle Indikatoren · Lernmodul · Wochenanalyse</div>
<div class="g3" style="margin-bottom:12px">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>Indikatoren</div>
    <div class="row"><span class="rk">EMA 9/20/50/100/200</span><span class="rv neu" id="emas">—</span></div>
    <div class="row"><span class="rk">RSI / MACD</span><span class="rv neu" id="rsi-macd">—</span></div>
    <div class="row"><span class="rk">BB O/M/U</span><span class="rv neu" id="bb">—</span></div>
    <div class="row"><span class="rk">Stoch / Williams%R</span><span class="rv neu" id="stoch-wr">—</span></div>
    <div class="row"><span class="rk">CCI / VWAP</span><span class="rv neu" id="cci-vwap">—</span></div>
    <div class="row"><span class="rk">ATR / ADX</span><span class="rv neu" id="atr-adx">—</span></div>
    <div class="row"><span class="rk">POC / VAH / VAL</span><span class="rv amr" id="vpoc">—</span></div>
    <div class="row"><span class="rk">Momentum 10/5</span><span class="rv neu" id="mom">—</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dp"></span>Lernmodul</div>
    <div class="lbl">AKTIVE REGELN (ab 2× Fehler)</div>
    <div id="l-rules" style="font-size:13px;color:var(--pu);line-height:1.9;margin-top:4px">—</div>
    <div style="border-top:1px solid var(--bd);margin-top:10px;padding-top:8px">
      <div class="lbl">CONFIRMATION-FEHLER (Trade mit Conf. verloren)</div>
      <div id="l-conf-fail" style="font-size:12px;color:var(--am);line-height:1.8;margin-top:4px">—</div>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dc"></span>Wochenanalyse</div>
    <div style="font-size:15px;font-weight:700" id="w-trend">—</div>
    <div style="font-size:13px;font-weight:700;margin:6px 0" id="w-forecast">—</div>
    <div class="meta" id="w-updated">—</div>
    <div style="border-top:1px solid var(--bd);margin-top:10px;padding-top:8px">
      <div class="lbl">KEY LEVELS</div>
      <div id="w-levels" style="font-size:13px;color:var(--am);line-height:1.9;margin-top:4px">—</div>
    </div>
  </div>
</div>

<div class="sec">Trade-Verlauf &amp; System-Log</div>
<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>Trade-Historie</div>
    <div class="tw" style="max-height:240px;overflow-y:auto">
    <table>
      <thead><tr><th>Zeit</th><th>Typ</th><th>Dir</th><th>Entry</th><th>Close</th>
        <th>Pkt</th><th>€ P&amp;L</th><th>Hebel</th><th>Min</th><th>Strategie</th><th>Conf</th><th>Erg.</th></tr></thead>
      <tbody id="t-body"><tr><td colspan="12" style="text-align:center;padding:10px;color:var(--ft)">Noch keine Trades</td></tr></tbody>
    </table>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db pulse"></span>System-Log</div>
    <div id="log-box" style="max-height:280px;overflow-y:auto"></div>
  </div>
</div>
</div><!-- /t-stats -->

<script>
const fmt=v=>(v===null||v===undefined)?'—':v;
const tc=t=>t&&t.includes('BULLISH')?'pos':t&&t.includes('BEARISH')?'neg':'neu';
const eur=(v,d=2)=>v===null||v===undefined?'—':(v>=0?'+':'')+v.toFixed(d)+'€';
const pkt=(v,d=2)=>v===null||v===undefined?'—':(v>=0?'+':'')+v.toFixed(d)+' Pkt';

function showTab(id,btn){
  document.querySelectorAll('.tc').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}

async function refresh(){
  try{
    const[sr,tr]=await Promise.all([fetch('/state'),fetch('/trades')]);
    const d=await sr.json(),trades=await tr.json();
    const i=d.indicators||{},s=d.stats||{},sig=d.last_signal||{};
    const w=d.willy_last||null,trends=d.trends||{},learn=d.learning||{};
    const wa=d.weekly_analysis||{},ss=d.strategy_scores||{};
    const da=d.demo_account||{},conf=d.confirmations||{};
    const gr=d.guardrails||{},perf=d.performance||{};
    const ms_state=d.macro_state||{};
    const t1h=d.indicators_1h||{},t4h=d.indicators_4h||{},t1d=d.indicators_1d||{};
    const sstats=d.strategy_stats||{};
    const p=d.price;

    // ── Header ──
    document.getElementById('clk').textContent=new Date().toUTCString().slice(17,25)+' UTC';
    document.getElementById('last-upd').textContent=d.last_update||'Warte...';
    document.getElementById('sess-b').textContent=d.session||'—';
    const grEl=document.getElementById('gr-status');
    grEl.textContent='GUARDRAIL: '+(gr.status||'OK');
    grEl.className='b '+(gr.status==='OK'?'bg':gr.status==='PAUSE_TAG'?'ba':'br');

    // News
    const na=document.getElementById('news-alert');
    if(d.news_lock){na.style.display='block';document.getElementById('news-reason').textContent=d.news_lock_reason||'';}
    else na.style.display='none';

    // ── TAB 1: GESAMT ──
    if(p) document.getElementById('price').textContent=p.toFixed(2);
    document.getElementById('atr').textContent=fmt(i.atr);
    document.getElementById('adx').textContent=fmt(i.adx);
    document.getElementById('price-src').textContent=d.price_source||'—';
    const ov=trends.overall||'—',ote=document.getElementById('ov-trend');
    ote.textContent='Gesamttrend: '+ov; ote.className='meta '+tc(ov);

    const st=sig.signal||'WARTEN';
    document.getElementById('sig-box').className='sbox '+(st==='BUY'?'sbuy':st==='SELL'?'ssell':'swait');
    const ste=document.getElementById('sig-t');
    ste.textContent=st+(sig.willy_confirmed?' ⭐':'');
    ste.style.color=st==='BUY'?'var(--gr)':st==='SELL'?'var(--rd)':'var(--am)';
    document.getElementById('sig-c').textContent=sig.confidence
      ?`Konfidenz: ${sig.confidence}% · ${sig.price} · Conf: ${sig.confirmations_passed||0}/${conf.required||5}`:'Warte...';
    document.getElementById('sig-lvl').innerHTML=sig.sl
      ?`<span style="color:var(--rd)">SL ${sig.sl}</span> &nbsp; <span style="color:var(--gr)">TP1 ${sig.tp1} · TP2 ${sig.tp2}</span>`:''
    document.getElementById('sig-meta').textContent=`Typ: ${sig.trade_type||d.trade_type||'—'} · Strat: ${sig.strategy||'—'}`;

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
    pe.textContent=pkt(pnl); pe.className='big '+(pnl>=0?'pos':'neg');
    document.getElementById('best').textContent=(s.best_trade||0).toFixed(2);
    document.getElementById('worst').textContent=(s.worst_trade||0).toFixed(2);

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

    // Demo
    const sb=da.starting_balance||1000;
    const bE=document.getElementById('da-balance');
    bE.textContent=da.balance!==undefined?'€'+da.balance.toFixed(2):'—';
    const eE=document.getElementById('da-equity');
    eE.textContent=da.equity!==undefined?'€'+da.equity.toFixed(2):'—';
    eE.className='dv '+(da.equity>=sb?'pos':'neg');
    const pE=document.getElementById('da-pnl');
    pE.textContent=eur(da.total_pnl_eur); pE.className='dv '+(da.total_pnl_eur>=0?'pos':'neg');
    const rE=document.getElementById('da-return');
    rE.textContent=da.return_pct!==undefined?(da.return_pct>=0?'+':'')+da.return_pct+'%':'—';
    rE.className='dv '+(da.return_pct>=0?'pos':'neg');
    const ddE=document.getElementById('da-dd');
    ddE.textContent=da.max_drawdown_pct!==undefined?'-'+da.max_drawdown_pct+'%':'—';
    ddE.className='dv '+(da.max_drawdown_pct>10?'neg':da.max_drawdown_pct>5?'amr':'pos');
    document.getElementById('da-lev').textContent='1:'+(da.leverage_used||0).toFixed(1)+' / max 1:'+(da.max_leverage||5);
    document.getElementById('da-margin').textContent='€'+(da.margin_used||0).toFixed(2)+' / €'+(da.free_margin||0).toFixed(2);
    document.getElementById('da-stats').textContent=(da.total_trades||0)+' · '+(da.win_rate_pct!==undefined?da.win_rate_pct+'%':'—');
    document.getElementById('da-rejected').textContent=da.rejected_trades||0;

    // Guardrails
    const grSt=document.getElementById('gr-stat-txt');
    grSt.textContent=gr.status||'OK';
    grSt.className=(gr.status==='OK'?'rv pos':gr.status==='PAUSE_TAG'?'rv amr':'rv neg');
    document.getElementById('gr-daily').textContent=(gr.daily_drawdown_pct||0).toFixed(2)+'%';
    document.getElementById('gr-daily').className='rv '+(gr.daily_drawdown_pct>=3?'neg':gr.daily_drawdown_pct>=2?'amr':'pos');
    document.getElementById('gr-weekly').textContent=(gr.weekly_drawdown_pct||0).toFixed(2)+'%';
    document.getElementById('gr-weekly').className='rv '+(gr.weekly_drawdown_pct>=6?'neg':gr.weekly_drawdown_pct>=4?'amr':'pos');
    const gdp=gr.daily_pnl_eur||0,gwp=gr.weekly_pnl_eur||0;
    document.getElementById('gr-day-pnl').textContent=eur(gdp);
    document.getElementById('gr-day-pnl').className='rv '+(gdp>=0?'pos':'neg');
    document.getElementById('gr-week-pnl').textContent=eur(gwp);
    document.getElementById('gr-week-pnl').className='rv '+(gwp>=0?'pos':'neg');

    // Confirmations
    const cp=conf.passed||[],cf=conf.failed||[],cc=conf.count||0,cr=conf.required||5;
    document.getElementById('conf-count-g').textContent=cc;
    document.getElementById('conf-req-g').textContent=cr;
    document.getElementById('conf-bar-g').style.width=Math.min(cc/cr*100,100)+'%';
    document.getElementById('conf-bar-g').className='pf '+(cc>=cr?'pg':'pr');
    document.getElementById('conf-passed-g').innerHTML=cp.length
      ?cp.map(c=>`<span class="cfp">✓ ${c}</span>`).join(''):'<span style="color:var(--ft);font-size:12px">—</span>';
    document.getElementById('conf-failed-g').innerHTML=cf.length
      ?cf.map(c=>`<span class="cff">✗ ${c}</span>`).join(''):'';

    // Open Trade
    const ot=d.open_trade;
    if(ot){
      const upnl=ot.direction==='BUY'?(p||0)-ot.entry:ot.entry-(p||0);
      const upE=upnl*(ot.lot_size||0.01)*100;
      document.getElementById('open-trade').innerHTML=
        `<span class="${ot.direction==='BUY'?'pos':'neg'}" style="font-weight:700">[${ot.trade_type||''}] ${ot.direction}</span>`+
        ` @ ${ot.entry} · SL ${ot.sl} · TP1 ${ot.tp1} · TP2 ${ot.tp2} · TP3 ${ot.tp3||'—'}<br>`+
        `Lot ${ot.lot_size||'—'} · Hebel 1:${ot.leverage_used||'—'} · ${ot.risk_pct||'—'}% (€${ot.risk_eur||'—'}) · ${ot.strategy||'—'}<br>`+
        `Gehalten: ${ot.hold_min||0} Min · Conf: ${ot.confirmations_passed||0} · `+
        `Unrealisiert: <span class="${upnl>=0?'pos':'neg'}">${upnl>=0?'+':''}${upnl.toFixed(2)} Pkt (${upE>=0?'+':''}${upE.toFixed(2)}€)</span>`;
    } else document.getElementById('open-trade').textContent='Kein offener Trade';

    // Willy
    if(w){
      const wd=w.signal_type||'—';
      document.getElementById('w-sig').textContent=wd;
      document.getElementById('w-sig').className='sv '+(wd.includes('BUY')?'pos':wd.includes('SELL')?'neg':'pur');
      document.getElementById('w-tf').textContent=w.timeframe||'—';
      document.getElementById('w-sc').textContent=w.score||'—';
      document.getElementById('willy-b').textContent='WILLY: '+wd;
      document.getElementById('willy-b').className='b '+(wd.includes('BUY')?'bg':wd.includes('SELL')?'br':'bp');
      document.getElementById('w-tps').textContent=`Entry ${w.entry||'—'} · TP1 ${w.tp1||'—'} · TP2 ${w.tp2||'—'} · TP3 ${w.tp3||'—'}`;
    }
    document.getElementById('w-cnt').textContent=d.willy_signals_count||0;

    // ── Strategie-Scores ──
    const mx=Math.max(ss.mean_reversion||0,ss.trend_follow||0,ss.breakout||0,ss.macro_structure||0,1);
    document.getElementById('sc-mr').textContent=ss.mean_reversion||0;
    document.getElementById('sc-tf').textContent=ss.trend_follow||0;
    document.getElementById('sc-bo').textContent=ss.breakout||0;
    document.getElementById('sc-ms').textContent=ss.macro_structure||0;
    document.getElementById('bar-mr').style.width=Math.min((ss.mean_reversion||0)/mx*100,100)+'%';
    document.getElementById('bar-tf').style.width=Math.min((ss.trend_follow||0)/mx*100,100)+'%';
    document.getElementById('bar-bo').style.width=Math.min((ss.breakout||0)/mx*100,100)+'%';
    document.getElementById('bar-ms').style.width=Math.min((ss.macro_structure||0)/mx*100,100)+'%';

    // ── TAB: WILLYALGOTRADER ──
    // Umbenennung zu willy_a (wa war schon für weekly_analysis vergeben → JS-Fehler behoben)
    const willy_a=d.willy_analytics||{};
    const waTotal=willy_a.total||0,waWins=willy_a.wins||0,waLosses=willy_a.losses||0;
    document.getElementById('wa-total').textContent=waTotal;
    const waWrEl=document.getElementById('wa-wr');
    waWrEl.textContent=willy_a.overall_win_rate?willy_a.overall_win_rate+'%':'—';
    waWrEl.className='dv '+(willy_a.overall_win_rate>=55?'pos':willy_a.overall_win_rate>=45?'amr':'neg');
    document.getElementById('wa-wl').textContent=waWins+' / '+waLosses;
    document.getElementById('wa-wl').className='dv '+(waWins>waLosses?'pos':waWins<waLosses?'neg':'neu');
    document.getElementById('wa-pending').textContent=willy_a.pending||0;
    document.getElementById('wa-best').textContent=willy_a.best_signal_type||'—';
    // TP/SL Distribution
    const tp1h=willy_a.tp1_hits||0,tp2h=willy_a.tp2_hits||0,tp3h=willy_a.tp3_hits||0,slh=willy_a.sl_hits||0;
    const tpMax=Math.max(tp1h,tp2h,tp3h,slh,1);
    document.getElementById('wa-tp1').textContent=tp1h;
    document.getElementById('wa-tp2').textContent=tp2h;
    document.getElementById('wa-tp3').textContent=tp3h;
    document.getElementById('wa-sl').textContent=slh;
    document.getElementById('wa-tp1-bar').style.width=Math.min(tp1h/tpMax*100,100)+'%';
    document.getElementById('wa-tp2-bar').style.width=Math.min(tp2h/tpMax*100,100)+'%';
    document.getElementById('wa-tp3-bar').style.width=Math.min(tp3h/tpMax*100,100)+'%';
    document.getElementById('wa-sl-bar').style.width=Math.min(slh/tpMax*100,100)+'%';
    // BUY/SELL
    const buyD=(willy_a.by_direction||{}).BUY||{};
    const sellD=(willy_a.by_direction||{}).SELL||{};
    document.getElementById('wa-buy-wr').textContent=buyD.win_rate?buyD.win_rate+'%':'—';
    document.getElementById('wa-buy-count').textContent=buyD.count||0;
    document.getElementById('wa-buy-wins').textContent=buyD.wins||0;
    document.getElementById('wa-buy-losses').textContent=buyD.losses||0;
    document.getElementById('wa-buy-bar').style.width=(buyD.win_rate||0)+'%';
    document.getElementById('wa-buy-tp1').textContent=buyD.tp1||0;
    document.getElementById('wa-buy-tp2').textContent=buyD.tp2||0;
    document.getElementById('wa-buy-tp3').textContent=buyD.tp3||0;
    document.getElementById('wa-sell-wr').textContent=sellD.win_rate?sellD.win_rate+'%':'—';
    document.getElementById('wa-sell-count').textContent=sellD.count||0;
    document.getElementById('wa-sell-wins').textContent=sellD.wins||0;
    document.getElementById('wa-sell-losses').textContent=sellD.losses||0;
    document.getElementById('wa-sell-bar').style.width=(sellD.win_rate||0)+'%';
    document.getElementById('wa-sell-tp1').textContent=sellD.tp1||0;
    document.getElementById('wa-sell-tp2').textContent=sellD.tp2||0;
    document.getElementById('wa-sell-tp3').textContent=sellD.tp3||0;
    // By TF
    const byTf=willy_a.by_tf||{};
    document.getElementById('wa-by-tf').innerHTML=Object.keys(byTf).length
      ?Object.entries(byTf).sort((a,b)=>b[1].count-a[1].count).map(([tf2,v])=>{
        const rtf=v.wins+v.losses; const wrtf=rtf>0?v.win_rate:null;
        return `<div class="row" style="padding:5px 0">
          <span class="rk" style="font-size:13px;font-weight:700">${tf2}</span>
          <span>
            <span class="${wrtf>=55?'pos':wrtf>=45?'amr':'neg'}" style="font-size:15px;font-weight:700">${wrtf!==null?wrtf+'%':'—'}</span>
            <span class="meta" style="display:inline;margin-left:8px">${v.wins}W / ${v.losses}L / ${v.pending||0}⏳ (${v.count} total)</span>
            ${v.tp1?`<span class="cfp" style="margin-left:4px">TP1:${v.tp1}</span>`:''}
            ${v.tp2?`<span class="cfp">TP2:${v.tp2}</span>`:''}
            ${v.tp3?`<span class="cfp">TP3:${v.tp3}</span>`:''}
          </span>
        </div>`;}).join('')
      :'<span style="color:var(--ft)">Noch keine Daten — warte auf Signale</span>';
    // By Score
    const byScore=willy_a.by_score||{};
    document.getElementById('wa-by-score').innerHTML=Object.keys(byScore).length
      ?Object.entries(byScore).sort((a,b)=>b[1].count-a[1].count).map(([sc,v])=>{
        const rsc=v.wins+v.losses; const wrsc=rsc>0?v.win_rate:null;
        return `<div class="row" style="padding:5px 0">
          <span class="rk" style="font-size:13px;font-weight:700">Score: ${sc}</span>
          <span>
            <span class="${wrsc>=55?'pos':wrsc>=45?'amr':'neg'}" style="font-size:15px;font-weight:700">${wrsc!==null?wrsc+'%':'—'}</span>
            <span class="meta" style="display:inline;margin-left:8px">${v.wins}W / ${v.losses}L / ${v.pending||0}⏳</span>
          </span>
        </div>`;}).join('')
      :'<span style="color:var(--ft)">Noch keine Daten</span>';
    // Offene Signale
    const openSigs=(willy_a.open_signals||[]).filter(s=>s.status==='PENDING');
    document.getElementById('wa-open').innerHTML=openSigs.length
      ?openSigs.map(s=>`<span class="${s.direction==='BUY'?'pos':'neg'}" style="font-weight:700">${s.direction}</span>`+
        ` [${s.timeframe||'—'}] Score:${s.score||'—'} @ ${s.entry||'—'}`+
        ` · TP1:${s.tp1||'—'} TP2:${s.tp2||'—'} TP3:${s.tp3||'—'} SL:${s.sl||'—'}`+
        ` · <span style="color:var(--ft)">${(s.open_time||'').slice(11,16)} UTC</span>`
        ).join('<br>')
      :'Keine offenen Signale';
    // Verlauf
    const closedSigs=(willy_a.closed_signals||[]).slice(0,20);
    document.getElementById('wa-history').innerHTML=closedSigs.length
      ?closedSigs.map(s=>{
        const res=s.result||s.status||'—';
        const pip=s.pips!==null&&s.pips!==undefined?(s.pips>=0?'+':'')+s.pips:'—';
        return `<tr>
          <td>${(s.open_time||'').slice(11,16)}</td>
          <td class="${s.direction==='BUY'?'pos':'neg'}" style="font-weight:700">${s.direction}</td>
          <td>${s.timeframe||'—'}</td>
          <td class="pur">${s.score||'—'}</td>
          <td>${s.entry||'—'}</td>
          <td class="pos">${s.tp1||'—'}</td>
          <td class="pos">${s.tp2||'—'}</td>
          <td class="neg">${s.sl||'—'}</td>
          <td>${s.close_price||'—'}</td>
          <td class="${(s.pips||0)>=0?'pos':'neg'}">${pip}</td>
          <td class="amr">${s.tp_level_hit?'TP'+s.tp_level_hit:'—'}</td>
          <td class="${res==='WIN'?'pos':res==='LOSS'?'neg':'neu'}" style="font-weight:700">${res}</td>
        </tr>`;}).join('')
      :'<tr><td colspan="12" style="text-align:center;padding:10px;color:var(--ft)">Noch keine abgeschlossenen Signale</td></tr>';

    // ── TAB 2: MEAN REVERSION ──
    const mr=sstats.MEAN_REVERSION||{};
    const mrPnl=mr.pnl||0;
    document.getElementById('mr-pnl').textContent=pkt(mrPnl);
    document.getElementById('mr-pnl').className='pnl-big '+(mrPnl>=0?'blu':'neg');
    document.getElementById('mr-eur').textContent=eur(mr.eur_pnl);
    document.getElementById('mr-eur').className=mr.eur_pnl>=0?'pos':'neg';
    document.getElementById('mr-wr-bar').style.width=(mr.win_rate||0)+'%';
    document.getElementById('mr-wins').textContent=mr.wins||0;
    document.getElementById('mr-losses').textContent=mr.losses||0;
    document.getElementById('mr-trades').textContent=mr.trades||0;
    document.getElementById('mr-wr').textContent=mr.win_rate?mr.win_rate+'%':'—';
    document.getElementById('mr-best').textContent=(mr.best||0).toFixed(2);
    document.getElementById('mr-worst').textContent=(mr.worst||0).toFixed(2);
    document.getElementById('mr-rsi').textContent=fmt(i.rsi);
    document.getElementById('mr-rsi').className='rv '+(i.rsi<35?'pos':i.rsi>65?'neg':'neu');
    document.getElementById('mr-stoch').textContent=`${fmt(i.stoch_k)} / ${fmt(i.stoch_d)}`;
    document.getElementById('mr-bb').textContent=`${fmt(i.bb_upper)} / ${fmt(i.bb_mid)} / ${fmt(i.bb_lower)}`;
    document.getElementById('mr-adx').textContent=fmt(i.adx);
    document.getElementById('mr-sigs').innerHTML=
      (trades.filter(t=>t.strategy==='MEAN_REVERSION').slice(0,3).map(t=>
        `<span class="${t.result==='WIN'?'pos':'neg'}">${t.result}</span> ${t.direction} @ ${t.entry} → ${t.close_price||'—'} (${t.pnl>=0?'+':''}${t.pnl} Pkt)`
      ).join('<br>')) || 'Keine Trades von dieser Strategie';

    // ── TAB 3: TREND FOLLOW ──
    const tf=sstats.TREND_FOLLOW||{};
    const tfPnl=tf.pnl||0;
    document.getElementById('tf-pnl').textContent=pkt(tfPnl);
    document.getElementById('tf-pnl').className='pnl-big '+(tfPnl>=0?'pos':'neg');
    document.getElementById('tf-eur').textContent=eur(tf.eur_pnl);
    document.getElementById('tf-eur').className=tf.eur_pnl>=0?'pos':'neg';
    document.getElementById('tf-wr-bar').style.width=(tf.win_rate||0)+'%';
    document.getElementById('tf-wins').textContent=tf.wins||0;
    document.getElementById('tf-losses').textContent=tf.losses||0;
    document.getElementById('tf-trades').textContent=tf.trades||0;
    document.getElementById('tf-wr').textContent=tf.win_rate?tf.win_rate+'%':'—';
    document.getElementById('tf-best').textContent=(tf.best||0).toFixed(2);
    document.getElementById('tf-worst').textContent=(tf.worst||0).toFixed(2);
    document.getElementById('tf-emas').textContent=`${fmt(i.ema20)} / ${fmt(i.ema50)} / ${fmt(i.ema200)}`;
    document.getElementById('tf-macd').textContent=`${fmt(i.macd)} / ${fmt(i.macd_signal)}`;
    document.getElementById('tf-adx').textContent=fmt(i.adx);
    document.getElementById('tf-mom').textContent=fmt(i.momentum);
    document.getElementById('tf-dxy').textContent=d.dxy_trend||'—';
    document.getElementById('tf-sigs').innerHTML=
      (trades.filter(t=>t.strategy==='TREND_FOLLOW').slice(0,3).map(t=>
        `<span class="${t.result==='WIN'?'pos':'neg'}">${t.result}</span> ${t.direction} @ ${t.entry} → ${t.close_price||'—'} (${t.pnl>=0?'+':''}${t.pnl} Pkt)`
      ).join('<br>')) || 'Keine Trades von dieser Strategie';

    // ── TAB 4: BREAKOUT ──
    const bo=sstats.BREAKOUT||{};
    const boPnl=bo.pnl||0;
    document.getElementById('bo-pnl').textContent=pkt(boPnl);
    document.getElementById('bo-pnl').className='pnl-big '+(boPnl>=0?'amr':'neg');
    document.getElementById('bo-eur').textContent=eur(bo.eur_pnl);
    document.getElementById('bo-eur').className=bo.eur_pnl>=0?'pos':'neg';
    document.getElementById('bo-wr-bar').style.width=(bo.win_rate||0)+'%';
    document.getElementById('bo-wins').textContent=bo.wins||0;
    document.getElementById('bo-losses').textContent=bo.losses||0;
    document.getElementById('bo-trades').textContent=bo.trades||0;
    document.getElementById('bo-wr').textContent=bo.win_rate?bo.win_rate+'%':'—';
    document.getElementById('bo-best').textContent=(bo.best||0).toFixed(2);
    document.getElementById('bo-worst').textContent=(bo.worst||0).toFixed(2);
    document.getElementById('bo-sess').textContent=d.session||'—';
    document.getElementById('bo-vol').textContent='—';
    document.getElementById('bo-poc').textContent=fmt(i.poc);
    document.getElementById('bo-sigs').innerHTML=
      (trades.filter(t=>t.strategy==='BREAKOUT').slice(0,3).map(t=>
        `<span class="${t.result==='WIN'?'pos':'neg'}">${t.result}</span> ${t.direction} @ ${t.entry} → ${t.close_price||'—'} (${t.pnl>=0?'+':''}${t.pnl} Pkt)`
      ).join('<br>')) || 'Keine Trades von dieser Strategie';

    // ── TAB 5: MACRO STRUKTUR ──
    const ms=sstats.MACRO_STRUCTURE||{};
    const msPnl=ms.pnl||0;
    document.getElementById('ms-pnl').textContent=pkt(msPnl);
    document.getElementById('ms-pnl').className='pnl-big '+(msPnl>=0?'pur':'neg');
    document.getElementById('ms-eur').textContent=eur(ms.eur_pnl);
    document.getElementById('ms-eur').className=ms.eur_pnl>=0?'pos':'neg';
    document.getElementById('ms-wr-bar').style.width=(ms.win_rate||0)+'%';
    document.getElementById('ms-wins').textContent=ms.wins||0;
    document.getElementById('ms-losses').textContent=ms.losses||0;
    document.getElementById('ms-trades').textContent=ms.trades||0;
    document.getElementById('ms-wr').textContent=ms.win_rate?ms.win_rate+'%':'—';
    document.getElementById('ms-best').textContent=(ms.best||0).toFixed(2);
    document.getElementById('ms-worst').textContent=(ms.worst||0).toFixed(2);
    const bias=ms_state.bias||'NEUTRAL';
    const bEl=document.getElementById('ms-bias');
    bEl.textContent=bias;
    bEl.className='rv '+(bias==='LONG_BIAS'?'pos':bias==='SHORT_BIAS'?'neg':'neu');
    document.getElementById('ms-bias-score').textContent=(ms_state.bias_score||0)>=0?'+'+(ms_state.bias_score||0):ms_state.bias_score||0;
    document.getElementById('ms-yields').textContent=d.yields_trend||'—';
    document.getElementById('ms-dxy').textContent=d.dxy_trend||'—';
    document.getElementById('ms-rsi').textContent=fmt(i.rsi);
    document.getElementById('ms-bias-notes').innerHTML=(ms_state.bias_notes||[]).map(n=>`→ ${n}`).join('<br>')||'—';
    const struct=ms_state.market_structure||'UNDEFINED';
    const sEl=document.getElementById('ms-struct');
    sEl.textContent=struct;
    sEl.style.color=struct==='TREND_UP'?'var(--gr)':struct==='TREND_DOWN'?'var(--rd)':struct==='RANGE'?'var(--am)':'var(--ft)';
    document.getElementById('ms-struct-notes').innerHTML=(ms_state.structure_notes||[]).map(n=>`→ ${n}`).join('<br>')||'—';
    const setup=ms_state.setup_type;
    const setupEl=document.getElementById('ms-setup');
    setupEl.textContent=setup?`${setup} ${ms_state.size_multiplier===0.5?'(0.5× Größe)':''}`.trim():'Kein aktives Setup';
    setupEl.style.color=setup==='A_PULLBACK'?'var(--gr)':setup==='B_BREAKOUT'?'var(--am)':setup==='C_COUNTER'?'var(--pu)':'var(--ft)';
    document.getElementById('ms-sigs').innerHTML=
      (trades.filter(t=>t.strategy==='MACRO_STRUCTURE').slice(0,5).map(t=>
        `<span class="${t.result==='WIN'?'pos':'neg'}">${t.result}</span> ${t.direction} @ ${t.entry} → ${t.close_price||'—'} (${t.pnl>=0?'+':''}${t.pnl} Pkt)`
      ).join('<br>')) || 'Noch keine Macro-Struktur Trades — Warte auf Setup A, B oder C';

    // ── TAB 6: STATISTIKEN ──
    document.getElementById('perf-exp').textContent=perf.expectancy!==undefined?pkt(perf.expectancy,2):'—';
    document.getElementById('perf-exp').className='dv '+(perf.expectancy>=0?'pos':'neg');
    document.getElementById('perf-pf').textContent=perf.profit_factor!==undefined?perf.profit_factor.toFixed(2):'—';
    document.getElementById('perf-pf').className='dv '+(perf.profit_factor>=1?'pos':'neg');
    document.getElementById('perf-crv').textContent=perf.avg_crv!==undefined?perf.avg_crv.toFixed(2):'—';
    document.getElementById('perf-crv').className='dv '+(perf.avg_crv>=1.5?'pos':perf.avg_crv>=1?'amr':'neg');
    document.getElementById('perf-wr').textContent=s.win_rate?s.win_rate+'%':'—';
    document.getElementById('perf-wr').className='dv '+(s.win_rate>=50?'pos':'neg');

    const tmap=[['1h','t-1h','t1h-rsi','t1h-poc',t1h],['4h','t-4h','t4h-rsi','t4h-poc',t4h],
                ['1d','t-1d','t1d-rsi',null,t1d]];
    for(const[tf2,tid,rid,pid,tdi] of tmap){
      const tv=trends[tf2]||'—',el=document.getElementById(tid);
      el.textContent=tv; el.className='sv '+tc(tv);
      if(document.getElementById(rid)) document.getElementById(rid).textContent=fmt(tdi.rsi);
      if(pid&&document.getElementById(pid)) document.getElementById(pid).textContent=fmt(tdi.poc||'—');
    }
    if(document.getElementById('t1d-e200')) document.getElementById('t1d-e200').textContent=fmt(t1d.ema200);
    const ove=document.getElementById('t-overall'); ove.textContent=ov; ove.className='sv '+tc(ov);
    document.getElementById('active-strat').textContent=d.active_strategy||'—';

    document.getElementById('emas').textContent=`${fmt(i.ema9)}/${fmt(i.ema20)}/${fmt(i.ema50)}/${fmt(i.ema100)}/${fmt(i.ema200)}`;
    document.getElementById('rsi-macd').textContent=`RSI ${fmt(i.rsi)} / MACD ${fmt(i.macd)}`;
    document.getElementById('bb').textContent=`${fmt(i.bb_upper)} / ${fmt(i.bb_mid)} / ${fmt(i.bb_lower)}`;
    document.getElementById('stoch-wr').textContent=`${fmt(i.stoch_k)} / ${fmt(i.williams_r)}`;
    document.getElementById('cci-vwap').textContent=`${fmt(i.cci)} / ${fmt(i.vwap)}`;
    document.getElementById('atr-adx').textContent=`${fmt(i.atr)} / ${fmt(i.adx)}`;
    document.getElementById('vpoc').textContent=`${fmt(i.poc)} / ${fmt(i.vah)} / ${fmt(i.val)}`;
    document.getElementById('mom').textContent=`${fmt(i.momentum)} / ${fmt(i.momentum_5)}`;

    const rules=learn.rules||[],cfl=learn.confirmation_failures||[];
    document.getElementById('l-rules').innerHTML=rules.length
      ?rules.slice(0,6).map(r=>`⚡ [${r.count}×] ${r.avoid}`).join('<br>'):'Noch keine Regeln...';
    document.getElementById('l-conf-fail').innerHTML=cfl.length
      ?cfl.slice(0,4).map(f=>`⚠ ${f.time} — ${f.trade} (${f.conf_count} Conf., ${f.pnl>=0?'+':''}${f.pnl} Pkt)`).join('<br>')
      :'Noch keine...';

    const wte=document.getElementById('w-trend');
    wte.textContent=wa.trend||'—'; wte.className=tc(wa.trend||'');
    const wfe=document.getElementById('w-forecast');
    wfe.textContent=wa.forecast||'—';
    wfe.style.color=wa.forecast&&wa.forecast.includes('BULLISH')?'var(--gr)':wa.forecast&&wa.forecast.includes('BEARISH')?'var(--rd)':'var(--am)';
    document.getElementById('w-updated').textContent=wa.updated||'—';
    document.getElementById('w-levels').innerHTML=(wa.key_levels||[]).map(l=>`• ${l}`).join('<br>')||'—';

    // Trades Tabelle
    const tb=document.getElementById('t-body');
    if(trades.length){
      tb.innerHTML=trades.slice(0,20).map(t=>{
        const ep=t.eur_pnl!==undefined?t.eur_pnl:(t.pnl*(t.lot_size||0.01)*100);
        const sc={'MEAN_REVERSION':'blu','TREND_FOLLOW':'pos','BREAKOUT':'amr','MACRO_STRUCTURE':'pur'}[t.strategy]||'neu';
        return `<tr>
          <td>${(t.close_time||'').slice(11,16)}</td>
          <td class="amr" style="font-weight:700">${t.trade_type||'SH'}</td>
          <td class="${t.direction==='BUY'?'pos':'neg'}" style="font-weight:700">${t.direction}</td>
          <td>${t.entry}</td><td>${t.close_price||'—'}</td>
          <td class="${t.pnl>=0?'pos':'neg'}">${t.pnl>=0?'+':''}${t.pnl}</td>
          <td class="${ep>=0?'pos':'neg'}">${ep>=0?'+':''}${ep.toFixed(2)}€</td>
          <td>1:${t.leverage_used||'—'}</td>
          <td>${t.hold_min_final||t.hold_min||'—'}</td>
          <td class="${sc}" style="font-size:11px">${(t.strategy||'').replace('_',' ')}</td>
          <td style="font-size:11px">${t.confirmations_passed||'—'}</td>
          <td class="${t.result==='WIN'?'pos':'neg'}" style="font-weight:700">${t.result}</td>
        </tr>`;
      }).join('');
    }

    // Log
    const lc={SIGNAL:'var(--am)',TRADE:'var(--gr)',ERROR:'var(--rd)',WARN:'var(--am)',LEARN:'var(--pu)',INFO:'var(--bl)'};
    document.getElementById('log-box').innerHTML=(d.log||[]).map(l=>
      `<div class="le" style="color:${lc[l.level]||'var(--bl)'}"><span class="t">${l.time}</span>[${l.level}] ${l.msg}</div>`
    ).join('');

  }catch(e){console.error('Refresh-Fehler:',e);}
  setTimeout(refresh,10000);
}

refresh();
setInterval(()=>{const e=document.getElementById('clk');if(e)e.textContent=new Date().toUTCString().slice(17,25)+' UTC';},1000);
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
        "price":bot_state["price"],"price_source":bot_state["price_source"],
        "last_update":bot_state["last_update"],"last_signal":bot_state["last_signal"],
        "indicators":bot_state["indicators"],
        "indicators_1h":bot_state["indicators_1h"],"indicators_4h":bot_state["indicators_4h"],"indicators_1d":bot_state["indicators_1d"],
        "trend_details":bot_state["trend_details"],"trends":bot_state["trends"],
        "learning":bot_state["learning"],"log":bot_state["log"][:50],"stats":bot_state["stats"],
        "strategy_stats":bot_state["strategy_stats"],
        "open_trade":bot_state["open_trade"],"running":bot_state["running"],
        "willy_last":bot_state["willy_last"],"willy_signals_count":len(bot_state["willy_signals"]),
        "dxy":bot_state["dxy"],"dxy_trend":bot_state["dxy_trend"],
        "yields_10y":bot_state["yields_10y"],"yields_trend":bot_state["yields_trend"],
        "gold_dxy_correlation":bot_state["gold_dxy_correlation"],
        "session":bot_state["session"],"trade_type":bot_state["trade_type"],
        "weekly_analysis":bot_state["weekly_analysis"],
        "strategy_scores":bot_state["strategy_scores"],"active_strategy":bot_state["active_strategy"],
        "confirmations":bot_state["confirmations"],
        "macro_state":bot_state["macro_state"],
        "guardrails":bot_state["guardrails"],
        "performance":bot_state["performance"],
        "news_lock":bot_state["news_lock"],"news_lock_reason":bot_state["news_lock_reason"],
        "demo_account":get_demo_snapshot(),
        "willy_analytics":bot_state["willy_analytics"],
    })

@app.route("/trades")
def trades(): return jsonify(bot_state["trades"])
@app.route("/signals")
def signals(): return jsonify(bot_state["signals"][:50])
@app.route("/weekly")
def weekly(): return jsonify(bot_state["weekly_analysis"])
@app.route("/learning")
def learning_r(): return jsonify(bot_state["learning"])
@app.route("/demo")
def demo_r(): return jsonify(get_demo_snapshot())
@app.route("/macro")
def macro_r(): return jsonify(bot_state["macro_state"])
@app.route("/guardrails")
def guardrails_r(): return jsonify(bot_state["guardrails"])

@app.route("/news",methods=["POST"])
def add_news():
    data=request.get_json(force=True)
    bot_state["news_events"].append({"name":data.get("name","Event"),"time":data.get("time","2025-01-01 00:00"),"impact":"HIGH"})
    add_log(f"News-Event: {data.get('name')} @ {data.get('time')}","INFO")
    return jsonify({"status":"ok"})

@app.route("/settings",methods=["POST"])
def settings():
    data=request.get_json(force=True); da=bot_state["demo_account"]
    if "balance"  in data: da["balance"]=float(data["balance"])
    if "risk"     in data: da["risk_per_trade_pct"]=float(data["risk"])
    if "leverage" in data: da["max_leverage"]=int(data["leverage"])
    return jsonify({"status":"ok"})

@app.route("/webhook",methods=["POST"])
def webhook():
    try:
        data=request.get_json(force=True)
        add_log(f"Webhook empfangen: {data}","INFO")
        st=data.get("signal","").upper(); tf=data.get("timeframe","—")
        pr=data.get("price") or data.get("close")
        # Preis in Preisliste aufnehmen
        if pr:
            try:
                pf=float(str(pr).replace(",","."))
                if 1500<pf<6000: bot_state["prices"].append(pf); bot_state["price"]=pf
            except: pass
        if st:
            # WillyAlgoTrader Signal vollständig verarbeiten
            process_willy_signal(data)
            # willy_last und willy_signals für Rückwärtskompatibilität
            we={"signal_type":st,"timeframe":tf,"score":data.get("score","—"),
                "entry":data.get("entry") or pr,"tp1":data.get("tp1"),
                "tp2":data.get("tp2"),"tp3":data.get("tp3"),"sl":data.get("sl"),
                "time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                "date":datetime.datetime.utcnow().strftime("%d.%m.%Y")}
            bot_state["willy_last"]=we
            bot_state["willy_signals"].insert(0,we)
            if len(bot_state["willy_signals"])>200: bot_state["willy_signals"].pop()
        return jsonify({"status":"ok","signal":st,"tracked":True}),200
    except Exception as e:
        add_log(f"Webhook Fehler: {e}","ERROR"); return jsonify({"status":"error"}),400

@app.route("/health")
def health(): return jsonify({"status":"healthy","version":"4.0","time":datetime.datetime.utcnow().isoformat()})
@app.route("/start")
def start():
    if not bot_state["running"]:
        bot_state["running"]=True
        threading.Thread(target=analysis_loop,daemon=True).start()
        return jsonify({"status":"Bot v4.0 gestartet"})
    return jsonify({"status":"Läuft bereits"})
@app.route("/stop")
def stop():
    bot_state["running"]=False; return jsonify({"status":"Bot gestoppt"})

# ═══════════════════════════════════════════════════════
# AUTO-START
# ═══════════════════════════════════════════════════════
def _auto_start():
    if not bot_state["running"]:
        bot_state["running"]=True
        threading.Thread(target=analysis_loop,daemon=True).start()
        add_log("XAUUSD KI-Bot v4.0 auto-gestartet (gunicorn)","INFO")

_auto_start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
