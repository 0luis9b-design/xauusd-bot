from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import datetime, threading, time, math, json

app = Flask(__name__)
CORS(app)

bot_state = {
    "price": None, "prices": [], "signals": [],
    "last_signal": None, "last_update": None,
    "indicators": {}, "running": False, "log": [],
    "trades": [], "open_trade": None,
    "willy_signals": [],  # WillyAlgoTrader Signale
    "willy_last": None,
    "stats": {
        "total_signals": 0, "buy_signals": 0, "sell_signals": 0,
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
        "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
    },
    "learning": {"total": 0, "wins": 0, "accuracy": 0.0, "cycle": 0}
}

def add_log(msg, level="INFO"):
    entry = {"time": datetime.datetime.utcnow().strftime("%H:%M:%S"), "msg": msg, "level": level}
    bot_state["log"].insert(0, entry)
    if len(bot_state["log"]) > 100: bot_state["log"].pop()
    print(f"[{level}] {msg}")

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
    ag = sum(gains[-period:])/period; al = sum(losses[-period:])/period
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

def calculate_all_indicators(prices):
    if len(prices) < 30: return {}
    p = prices
    ema20=calc_ema(p,20); ema50=calc_ema(p,50); ema200=calc_ema(p,200)
    rsi=calc_rsi(p); macd,macd_s,macd_h=calc_macd(p)
    bb_l,bb_m,bb_u=calc_bollinger(p); sk,sd=calc_stochastic(p)
    atr=calc_atr(p); adx=calc_adx(p)
    wr=calc_williams_r(p); cci=calc_cci(p)
    vwap=round(sum(p[-20:])/len(p[-20:]),2); mom=calc_momentum(p)
    return {
        "price":p[-1],"ema20":ema20,"ema50":ema50,"ema200":ema200,
        "rsi":rsi,"macd":macd,"macd_signal":macd_s,"macd_hist":macd_h,
        "bb_lower":bb_l,"bb_mid":bb_m,"bb_upper":bb_u,
        "stoch_k":sk,"stoch_d":sd,"atr":atr,"adx":adx,
        "williams_r":wr,"cci":cci,"vwap":vwap,"momentum":mom,
    }

# ── SIGNAL ENGINE ────────────────────────────
def evaluate_signal(inds):
    if not inds or not inds.get("price"): return "WARTEN", 0, [], []
    price=inds["price"]; bull=[]; bear=[]
    e20=inds.get("ema20"); e50=inds.get("ema50"); e200=inds.get("ema200")
    rsi=inds.get("rsi"); macd=inds.get("macd"); ms=inds.get("macd_signal")
    bbl=inds.get("bb_lower"); bbu=inds.get("bb_upper")
    sk=inds.get("stoch_k"); wr=inds.get("williams_r")
    cci=inds.get("cci"); vwap=inds.get("vwap"); mom=inds.get("momentum")

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
        if macd>ms: bull.append(f"MACD={macd} Bullish Crossover")
        else: bear.append(f"MACD={macd} Bearish Crossover")
    if bbl and bbu:
        if price<bbl: bull.append(f"Unter BB-Unterkante({bbl}) Oversold")
        elif price>bbu: bear.append(f"Über BB-Oberkante({bbu}) Overbought")
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
        if price>vwap: bull.append(f"Preis({price}) über VWAP({vwap})")
        else: bear.append(f"Preis({price}) unter VWAP({vwap})")
    if mom is not None:
        if mom>0: bull.append(f"Momentum={mom:+.1f} Positiv")
        else: bear.append(f"Momentum={mom:+.1f} Negativ")

    # WillyAlgoTrader Bonus-Gewichtung
    willy = bot_state.get("willy_last")
    willy_boost = 0
    if willy and (datetime.datetime.utcnow() - datetime.datetime.strptime(willy["time"], "%H:%M:%S").replace(year=datetime.datetime.utcnow().year, month=datetime.datetime.utcnow().month, day=datetime.datetime.utcnow().day)).seconds < 3600:
        if willy["signal_type"] in ["BUY","BUY_A+"]:
            bull.append(f"⭐ WillyAlgoTrader: {willy['signal_type']} ({willy['timeframe']}) Score:{willy.get('score','—')}")
            willy_boost = 2
        elif willy["signal_type"] in ["SELL","SELL_A+"]:
            bear.append(f"⭐ WillyAlgoTrader: {willy['signal_type']} ({willy['timeframe']}) Score:{willy.get('score','—')}")
            willy_boost = 2

    total = len(bull)+len(bear)
    if total == 0: return "WARTEN", 0, [], []
    bp = len(bull)/total*100; sp = len(bear)/total*100
    min_signals = 4 if willy_boost > 0 else 5  # Mit Willy reichen 4 eigene
    if bp>=60 and len(bull)>=min_signals: return "BUY", round(bp,1), bull, bear
    elif sp>=60 and len(bear)>=min_signals: return "SELL", round(sp,1), bear, bull
    return "WARTEN", round(max(bp,sp),1), bull, bear

# ── TRADE TRACKING ───────────────────────────
def open_trade(signal, price, sl, tp1, tp2):
    bot_state["open_trade"] = {
        "direction":signal,"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,
        "open_time":datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),"status":"OPEN"
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
        t["close_time"]=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        t["status"]="CLOSED"
        bot_state["trades"].insert(0,t.copy())
        if len(bot_state["trades"])>200: bot_state["trades"].pop()
        bot_state["open_trade"]=None
        s=bot_state["stats"]; s["total_trades"]+=1; s["total_pnl"]=round(s["total_pnl"]+pnl,2)
        if result=="WIN":
            s["winning_trades"]+=1; s["best_trade"]=round(max(s["best_trade"],pnl),2)
            wins=[t["pnl"] for t in bot_state["trades"] if t["result"]=="WIN"]
            s["avg_win"]=round(sum(wins)/len(wins),2) if wins else 0
        else:
            s["losing_trades"]+=1; s["worst_trade"]=round(min(s["worst_trade"],pnl),2)
            losses=[t["pnl"] for t in bot_state["trades"] if t["result"]=="LOSS"]
            s["avg_loss"]=round(sum(losses)/len(losses),2) if losses else 0
        s["win_rate"]=round(s["winning_trades"]/s["total_trades"]*100,1)
        add_log(f"Trade geschlossen: {result} P&L:{pnl:+.2f} Pkt", "TRADE")

# ── PREIS ABRUFEN ────────────────────────────
def fetch_price():
    import urllib.request
    try:
        url="https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1m&range=1d"
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=10) as r:
            data=json.loads(r.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception as e:
        add_log(f"Preis-Fehler: {e}","WARN")
        if bot_state["prices"]:
            import random
            return round(bot_state["prices"][-1]+random.uniform(-0.3,0.3),2)
    return None

# ── ANALYSE LOOP ─────────────────────────────
def analysis_loop():
    add_log("KI-Analyse-Engine gestartet ✓","INFO")
    cycle=0
    while bot_state["running"]:
        try:
            cycle+=1; bot_state["learning"]["cycle"]=cycle
            price=fetch_price()
            if price:
                bot_state["price"]=price
                bot_state["prices"].append(price)
                if len(bot_state["prices"])>200: bot_state["prices"].pop(0)
                bot_state["last_update"]=datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
                check_trade(price)
                if len(bot_state["prices"])>=30:
                    inds=calculate_all_indicators(bot_state["prices"])
                    bot_state["indicators"]=inds
                    sig,conf,reasons,counter=evaluate_signal(inds)
                    bot_state["stats"]["total_signals"]+=1
                    if sig=="BUY": bot_state["stats"]["buy_signals"]+=1
                    elif sig=="SELL": bot_state["stats"]["sell_signals"]+=1
                    atr=inds.get("atr",15)
                    entry={
                        "time":datetime.datetime.utcnow().strftime("%H:%M:%S"),
                        "date":datetime.datetime.utcnow().strftime("%d.%m.%Y"),
                        "signal":sig,"confidence":conf,"price":price,
                        "reasons":reasons,"counter_reasons":counter,"atr":atr,
                        "sl":round(price-1.5*atr,2) if sig=="BUY" else round(price+1.5*atr,2) if sig=="SELL" else None,
                        "tp1":round(price+1.5*atr,2) if sig=="BUY" else round(price-1.5*atr,2) if sig=="SELL" else None,
                        "tp2":round(price+3.0*atr,2) if sig=="BUY" else round(price-3.0*atr,2) if sig=="SELL" else None,
                        "willy_confirmed": bot_state["willy_last"] is not None,
                    }
                    bot_state["last_signal"]=entry
                    bot_state["signals"].insert(0,entry)
                    if len(bot_state["signals"])>200: bot_state["signals"].pop()
                    if sig!="WARTEN" and not bot_state["open_trade"]:
                        open_trade(sig,price,entry["sl"],entry["tp1"],entry["tp2"])
                    bot_state["learning"]["total"]+=1
                    if sig in ["BUY","SELL"]: bot_state["learning"]["wins"]+=1
                    t=bot_state["learning"]["total"]
                    bot_state["learning"]["accuracy"]=round(bot_state["learning"]["wins"]/t*100,1) if t>0 else 0
                    willy_tag=" ⭐WILLY" if entry["willy_confirmed"] else ""
                    lvl="SIGNAL" if sig!="WARTEN" else "INFO"
                    add_log(f"{sig}{willy_tag} | Konfidenz:{conf}% | Preis:{price}",lvl)
                else:
                    add_log(f"Preis:{price} | Sammle Daten... ({len(bot_state['prices'])}/30)","INFO")
        except Exception as e:
            add_log(f"Fehler: {str(e)}","ERROR")
        time.sleep(300)

# ── DASHBOARD ────────────────────────────────
DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD KI-Bot Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0e1a;color:#e0e6f0;font-family:'Courier New',monospace;padding:12px}
.hdr{background:#111827;border:1px solid #1e3a5f;border-radius:8px;padding:12px 16px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.logo{font-size:16px;font-weight:700;color:#f59e0b;letter-spacing:2px}
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
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}
.pn{background:#111827;border:1px solid #1e2d45;border-radius:8px;padding:12px}
.pt{font-size:9px;color:#6b7280;letter-spacing:2px;margin-bottom:8px;display:flex;align-items:center;gap:5px}
.dot{width:6px;height:6px;border-radius:50%}
.dg{background:#4ade80;box-shadow:0 0 5px #4ade80}.da{background:#f59e0b;box-shadow:0 0 5px #f59e0b}
.db{background:#60a5fa;box-shadow:0 0 5px #60a5fa}.dr{background:#f87171;box-shadow:0 0 5px #f87171}
.dp{background:#c084fc;box-shadow:0 0 5px #c084fc}
.big{font-size:22px;font-weight:700;letter-spacing:2px}
.pos{color:#4ade80}.neg{color:#f87171}.neu{color:#94a3b8}.amr{color:#f59e0b}.pur{color:#c084fc}
.sm{text-align:center}.sv{font-size:18px;font-weight:700}.sl2{font-size:8px;color:#6b7280;letter-spacing:1px;margin-top:2px}
.ir{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #1a2236;font-size:10px}
.ir:last-child{border-bottom:none}.in{color:#6b7280}
.pb{background:#1e2d45;border-radius:4px;height:5px;margin:3px 0;overflow:hidden}
.pf{height:100%;border-radius:4px;transition:width .5s}
.fg{background:linear-gradient(90deg,#166534,#4ade80)}.fr{background:linear-gradient(90deg,#7f1d1d,#f87171)}
.fa{background:linear-gradient(90deg,#78350f,#f59e0b)}.fl{background:linear-gradient(90deg,#1e3a5f,#60a5fa)}
.fp{background:linear-gradient(90deg,#6b21a8,#c084fc)}
.le{font-size:9px;padding:2px 0;border-bottom:1px solid #1a2236;line-height:1.5}
.le:last-child{border-bottom:none}
.pulse{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.blink{animation:blink 1s infinite}@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
table{width:100%;border-collapse:collapse;font-size:9px}
th{color:#6b7280;font-weight:700;padding:3px 6px;border-bottom:1px solid #1e2d45;text-align:left;letter-spacing:1px}
td{padding:3px 6px;border-bottom:1px solid #1a2236}
tr:last-child td{border-bottom:none}
.sbox{padding:10px;border-radius:6px;border:1px solid;margin-bottom:4px}
.sbuy{background:#052e16;border-color:#166534}.ssell{background:#1c0a0a;border-color:#7f1d1d}.swait{background:#1c1000;border-color:#78350f}
.willy-box{background:#1a0a2e;border:1px solid #6b21a8;border-radius:6px;padding:8px;margin-top:6px}
</style>
</head>
<body>
<div class="hdr">
  <div><div class="logo">⚡ XAUUSD KI-BOT DASHBOARD</div><div class="sub">GOLD/USD · AUTONOME ANALYSE · v2.1 · WillyAlgoTrader INTEGRATION</div></div>
  <div class="badges">
    <span class="b bg"><span class="blink">●</span> LIVE</span>
    <span class="b bb" id="clk">--:--:-- UTC</span>
    <span class="b ba" id="last-upd">Warte...</span>
    <span class="b bp" id="willy-status">WILLY: —</span>
  </div>
</div>

<div class="g4">
  <div class="pn"><div class="pt"><span class="dot da"></span>XAUUSD PREIS</div>
    <div class="big amr" id="price">—</div>
    <div style="font-size:10px;margin-top:4px;color:#6b7280">ATR: <span id="atr" class="amr">—</span> &nbsp; ADX: <span id="adx" class="amr">—</span></div>
  </div>
  <div class="pn"><div class="pt"><span class="dot dg pulse"></span>SIGNAL</div>
    <div id="sig-box" class="sbox swait">
      <div style="font-size:13px;font-weight:700;letter-spacing:2px" id="sig-t">WARTEN</div>
      <div style="font-size:9px;color:#94a3b8;margin-top:3px" id="sig-c">Sammle Daten...</div>
      <div style="font-size:9px;margin-top:3px" id="sig-levels"></div>
    </div>
  </div>
  <div class="pn"><div class="pt"><span class="dot db"></span>WIN RATE</div>
    <div class="big pos" id="winrate">—</div>
    <div class="pb"><div class="pf fg" id="wr-bar" style="width:0%"></div></div>
    <div style="font-size:9px;color:#6b7280;margin-top:4px"><span id="wins">0</span>W / <span id="losses">0</span>L / <span id="total-t">0</span> Trades</div>
  </div>
  <div class="pn"><div class="pt"><span class="dot dg"></span>GESAMT P&L</div>
    <div class="big" id="total-pnl">+0.00 Pkt</div>
    <div style="font-size:9px;margin-top:4px;color:#6b7280">Best: <span id="best" class="pos">0</span> &nbsp; Worst: <span id="worst" class="neg">0</span></div>
  </div>
</div>

<!-- WillyAlgoTrader Panel -->
<div class="pn" style="margin-bottom:10px">
  <div class="pt"><span class="dot dp pulse"></span>WILLYALGOTRADER — EXTERNE SIGNALE</div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px">
    <div class="sm"><div class="sv pur" id="w-signal">—</div><div class="sl2">SIGNAL</div></div>
    <div class="sm"><div class="sv" id="w-tf">—</div><div class="sl2">TIMEFRAME</div></div>
    <div class="sm"><div class="sv" id="w-score">—</div><div class="sl2">SCORE</div></div>
    <div class="sm"><div class="sv" id="w-time">—</div><div class="sl2">LETZTES SIGNAL</div></div>
    <div class="sm"><div class="sv" id="w-count">0</div><div class="sl2">TOTAL SIGNALS</div></div>
  </div>
  <div style="margin-top:8px;font-size:9px;color:#6b7280" id="w-tps">TP1: — &nbsp;|&nbsp; TP2: — &nbsp;|&nbsp; TP3: —</div>
  <div style="margin-top:4px" id="w-history" style="font-size:9px"></div>
</div>

<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot da"></span>ALLE INDIKATOREN — LIVE WERTE</div>
    <div class="ir"><span class="in">EMA 20</span><span id="ema20" class="neu">—</span></div>
    <div class="ir"><span class="in">EMA 50</span><span id="ema50" class="neu">—</span></div>
    <div class="ir"><span class="in">EMA 200</span><span id="ema200" class="neu">—</span></div>
    <div class="ir"><span class="in">RSI (14)</span><span id="rsi" class="neu">—</span></div>
    <div class="ir"><span class="in">MACD</span><span id="macd" class="neu">—</span></div>
    <div class="ir"><span class="in">MACD Signal</span><span id="macd-s" class="neu">—</span></div>
    <div class="ir"><span class="in">BB Oben</span><span id="bb-u" class="neg">—</span></div>
    <div class="ir"><span class="in">BB Mitte</span><span id="bb-m" class="neu">—</span></div>
    <div class="ir"><span class="in">BB Unten</span><span id="bb-l" class="pos">—</span></div>
    <div class="ir"><span class="in">Stochastic K</span><span id="stoch" class="neu">—</span></div>
    <div class="ir"><span class="in">Williams %R</span><span id="wr2" class="neu">—</span></div>
    <div class="ir"><span class="in">CCI (20)</span><span id="cci" class="neu">—</span></div>
    <div class="ir"><span class="in">VWAP</span><span id="vwap" class="neu">—</span></div>
    <div class="ir"><span class="in">Momentum</span><span id="mom" class="neu">—</span></div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot dg pulse"></span>SIGNAL-BEGRÜNDUNG</div>
    <div style="font-size:9px;color:#6b7280;margin-bottom:3px">✅ BULLISH SIGNALE</div>
    <div id="bull-reasons" style="font-size:9px;color:#4ade80;line-height:1.8;min-height:50px">Warte auf Daten...</div>
    <div style="font-size:9px;color:#6b7280;margin:6px 0 3px">❌ BEARISH SIGNALE</div>
    <div id="bear-reasons" style="font-size:9px;color:#f87171;line-height:1.8;min-height:50px">Warte auf Daten...</div>
    <div style="border-top:1px solid #1e2d45;margin-top:8px;padding-top:8px">
      <div class="pt"><span class="dot db"></span>OFFENER TRADE</div>
      <div id="open-trade" style="font-size:10px;color:#94a3b8">Kein offener Trade</div>
    </div>
  </div>
</div>

<div class="g2">
  <div class="pn">
    <div class="pt"><span class="dot db"></span>TRADE HISTORIE & P&L</div>
    <div style="overflow-y:auto;max-height:200px">
    <table>
      <thead><tr><th>DATUM</th><th>DIR</th><th>ENTRY</th><th>CLOSE</th><th>P&L</th><th>WILLY</th><th>RESULT</th></tr></thead>
      <tbody id="trades-body"><tr><td colspan="7" style="color:#6b7280;text-align:center">Noch keine Trades</td></tr></tbody>
    </table>
    </div>
    <div style="margin-top:8px;border-top:1px solid #1e2d45;padding-top:6px;display:grid;grid-template-columns:repeat(3,1fr);gap:6px">
      <div class="sm"><div class="sv pos" id="avg-win">—</div><div class="sl2">AVG WIN</div></div>
      <div class="sm"><div class="sv neg" id="avg-loss">—</div><div class="sl2">AVG LOSS</div></div>
      <div class="sm"><div class="sv amr" id="signal-count">0</div><div class="sl2">SIGNALE</div></div>
    </div>
  </div>
  <div class="pn">
    <div class="pt"><span class="dot db pulse"></span>BOT LOG — ECHTZEIT</div>
    <div id="log-box" style="max-height:260px;overflow-y:auto"></div>
  </div>
</div>

<script>
function fmt(v){return(v===null||v===undefined)?'—':v}
async function refresh(){
  try{
    const [stateRes, tradesRes] = await Promise.all([fetch('/state'), fetch('/trades')]);
    const d = await stateRes.json();
    const trades = await tradesRes.json();
    const i=d.indicators||{}; const s=d.stats||{}; const sig=d.last_signal||{};
    const w=d.willy_last||null; const wc=d.willy_signals_count||0;

    document.getElementById('clk').textContent=new Date().toUTCString().slice(17,25)+' UTC';
    document.getElementById('last-upd').textContent=d.last_update||'Warte...';

    const p=d.price;
    if(p) document.getElementById('price').textContent=p.toFixed(2);
    document.getElementById('atr').textContent=fmt(i.atr);
    document.getElementById('adx').textContent=fmt(i.adx);

    const st=sig.signal||'WARTEN';
    const box=document.getElementById('sig-box');
    box.className='sbox '+(st==='BUY'?'sbuy':st==='SELL'?'ssell':'swait');
    document.getElementById('sig-t').textContent=st+(sig.willy_confirmed?' ⭐':'');
    document.getElementById('sig-t').style.color=st==='BUY'?'#4ade80':st==='SELL'?'#f87171':'#f59e0b';
    document.getElementById('sig-c').textContent=sig.confidence?`Konfidenz: ${sig.confidence}% | ${sig.price}`:'Warte auf Konvergenz...';
    if(sig.sl) document.getElementById('sig-levels').innerHTML=`<span style="color:#f87171">SL: ${sig.sl}</span> &nbsp; <span style="color:#4ade80">TP1: ${sig.tp1}</span> &nbsp; <span style="color:#4ade80">TP2: ${sig.tp2}</span>`;

    document.getElementById('winrate').textContent=s.win_rate?s.win_rate+'%':'—';
    document.getElementById('winrate').className='big '+(s.win_rate>=50?'pos':'neg');
    document.getElementById('wr-bar').style.width=(s.win_rate||0)+'%';
    document.getElementById('wins').textContent=s.winning_trades||0;
    document.getElementById('losses').textContent=s.losing_trades||0;
    document.getElementById('total-t').textContent=s.total_trades||0;
    const pnl=s.total_pnl||0;
    const pnlEl=document.getElementById('total-pnl');
    pnlEl.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+' Pkt';
    pnlEl.className='big '+(pnl>=0?'pos':'neg');
    document.getElementById('best').textContent=(s.best_trade||0).toFixed(2);
    document.getElementById('worst').textContent=(s.worst_trade||0).toFixed(2);
    document.getElementById('avg-win').textContent=s.avg_win?'+'+s.avg_win:'—';
    document.getElementById('avg-loss').textContent=s.avg_loss||'—';
    document.getElementById('signal-count').textContent=s.total_signals||0;

    // WillyAlgoTrader
    document.getElementById('w-count').textContent=wc;
    if(w){
      const wdir=w.signal_type||'—';
      document.getElementById('w-signal').textContent=wdir;
      document.getElementById('w-signal').className='sv '+(wdir.includes('BUY')?'pos':wdir.includes('SELL')?'neg':'pur');
      document.getElementById('w-tf').textContent=w.timeframe||'—';
      document.getElementById('w-score').textContent=w.score||'—';
      document.getElementById('w-time').textContent=w.time||'—';
      document.getElementById('willy-status').textContent='WILLY: '+wdir;
      document.getElementById('willy-status').className='b '+(wdir.includes('BUY')?'bg':wdir.includes('SELL')?'br':'bp');
      if(w.tp1||w.tp2||w.tp3)
        document.getElementById('w-tps').textContent=`TP1: ${w.tp1||'—'} | TP2: ${w.tp2||'—'} | TP3: ${w.tp3||'—'} | Entry: ${w.entry||'—'}`;
    }

    const set=(id,v,cls)=>{const el=document.getElementById(id);if(el){el.textContent=fmt(v);if(cls)el.className=cls;}};
    set('ema20',i.ema20,i.ema20&&p&&i.ema20<p?'pos':'neg');
    set('ema50',i.ema50,i.ema50&&p&&i.ema50<p?'pos':'neg');
    set('ema200',i.ema200,i.ema200&&p&&i.ema200<p?'pos':'neg');
    set('rsi',i.rsi,i.rsi<35?'pos':i.rsi>65?'neg':'neu');
    set('macd',i.macd,i.macd&&i.macd>0?'pos':'neg');
    set('macd-s',i.macd_signal,'neu');
    set('bb-u',i.bb_upper,'neg');set('bb-m',i.bb_mid,'neu');set('bb-l',i.bb_lower,'pos');
    set('stoch',i.stoch_k,i.stoch_k<25?'pos':i.stoch_k>75?'neg':'neu');
    set('wr2',i.williams_r,i.williams_r<-80?'pos':i.williams_r>-20?'neg':'neu');
    set('cci',i.cci,i.cci<-100?'pos':i.cci>100?'neg':'neu');
    set('vwap',i.vwap,i.vwap&&p&&p>i.vwap?'pos':'neg');
    set('mom',i.momentum,i.momentum&&i.momentum>0?'pos':'neg');

    const br=sig.reasons||[]; const cr=sig.counter_reasons||[];
    document.getElementById('bull-reasons').innerHTML=br.length?br.map(r=>`✓ ${r}`).join('<br>'):'<span style="color:#374151">Keine bullischen Signale</span>';
    document.getElementById('bear-reasons').innerHTML=cr.length?cr.map(r=>`✗ ${r}`).join('<br>'):'<span style="color:#374151">Keine bärischen Signale</span>';

    const ot=d.open_trade;
    if(ot){
      const upnl=ot.direction==='BUY'?(p||0)-ot.entry:ot.entry-(p||0);
      document.getElementById('open-trade').innerHTML=
        `<span class="${ot.direction==='BUY'?'pos':'neg'}">${ot.direction}</span> @ ${ot.entry} | SL:${ot.sl} | TP1:${ot.tp1} | TP2:${ot.tp2}<br>Unrealisiert: <span class="${upnl>=0?'pos':'neg'}">${upnl>=0?'+':''}${upnl.toFixed(2)} Pkt</span>`;
    } else {
      document.getElementById('open-trade').textContent='Kein offener Trade';
    }

    const tbody=document.getElementById('trades-body');
    if(trades.length){
      tbody.innerHTML=trades.slice(0,20).map(t=>
        `<tr><td>${(t.close_time||'').slice(0,16)}</td>
        <td class="${t.direction==='BUY'?'pos':'neg'}">${t.direction}</td>
        <td>${t.entry}</td><td>${t.close_price||'—'}</td>
        <td class="${t.pnl>=0?'pos':'neg'}">${t.pnl>=0?'+':''}${t.pnl}</td>
        <td>${t.willy_confirmed?'⭐':'—'}</td>
        <td class="${t.result==='WIN'?'pos':'neg'}">${t.result}</td></tr>`).join('');
    }

    document.getElementById('log-box').innerHTML=(d.log||[]).map(l=>
      `<div class="le" style="color:${l.level==='SIGNAL'?'#f59e0b':l.level==='TRADE'?'#4ade80':l.level==='ERROR'?'#f87171':l.level==='WARN'?'#f59e0b':'#60a5fa'}">
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
        "learning":bot_state["learning"],"log":bot_state["log"][:30],
        "stats":bot_state["stats"],"open_trade":bot_state["open_trade"],
        "running":bot_state["running"],"willy_last":bot_state["willy_last"],
        "willy_signals_count":len(bot_state["willy_signals"]),
    })

@app.route("/trades")
def trades(): return jsonify(bot_state["trades"])

@app.route("/signals")
def signals(): return jsonify(bot_state["signals"][:50])

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        add_log(f"Webhook empfangen: {data}","INFO")
        sig_type = data.get("signal","").upper()
        tf = data.get("timeframe","—")
        price_raw = data.get("price") or data.get("close")

        # Preis verarbeiten
        if price_raw:
            try:
                p=float(str(price_raw).replace(",","."))
                bot_state["prices"].append(p); bot_state["price"]=p
            except: pass

        # WillyAlgoTrader Signal verarbeiten
        if sig_type:
            willy_entry = {
                "signal_type": sig_type,
                "timeframe": tf,
                "score": data.get("score","—"),
                "entry": data.get("entry") or price_raw,
                "tp1": data.get("tp1"),
                "tp2": data.get("tp2"),
                "tp3": data.get("tp3"),
                "sl": data.get("sl"),
                "time": datetime.datetime.utcnow().strftime("%H:%M:%S"),
                "date": datetime.datetime.utcnow().strftime("%d.%m.%Y"),
            }
            bot_state["willy_last"] = willy_entry
            bot_state["willy_signals"].insert(0, willy_entry)
            if len(bot_state["willy_signals"])>100: bot_state["willy_signals"].pop()
            add_log(f"⭐ WillyAlgoTrader: {sig_type} | TF:{tf} | Entry:{willy_entry['entry']}","SIGNAL")

        return jsonify({"status":"ok"}),200
    except Exception as e:
        add_log(f"Webhook Fehler: {e}","ERROR")
        return jsonify({"status":"error","message":str(e)}),400

@app.route("/health")
def health(): return jsonify({"status":"healthy","time":datetime.datetime.utcnow().isoformat()})

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
    add_log("XAUUSD KI-Bot v2.1 + WillyAlgoTrader gestartet","INFO")
    app.run(host="0.0.0.0",port=8080)
