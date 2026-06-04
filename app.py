"""
XAU/USD Dashboard Server — Flask + Real-time data
Serves web dashboard + powers Telegram alerts
"""
from flask import Flask, jsonify, render_template_string
import os, datetime, threading, time, requests, ephem
import yfinance as yf
import pandas as pd

app = Flask(__name__)
IST = datetime.timedelta(hours=5, minutes=30)

# ── CACHE (avoid hammering API) ───────────────────────────────────────────────
_cache = {}
_cache_time = {}
CACHE_TTL = 300  # 5 min

def utcnow(): return datetime.datetime.utcnow()
def istnow(): return utcnow() + IST
def ist_str(): return istnow().strftime("%d %b %Y  %I:%M %p IST")

# ── INDICATORS ────────────────────────────────────────────────────────────────
def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def rsi_calc(df,p=14):
    if df is None or len(df)<p+1: return 50.0
    d=df["Close"].diff(); g=d.clip(lower=0).rolling(p).mean()
    l=(-d.clip(upper=0)).rolling(p).mean()
    return round(float((100-100/(1+g/l)).iloc[-1]),1)
def atr_calc(df,p=14):
    if df is None or len(df)<p+1: return 5.0
    h=df["High"];l=df["Low"];c=df["Close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return round(float(tr.rolling(p).mean().iloc[-1]),2)
def macd_calc(df):
    if df is None or len(df)<26: return 0
    c=df["Close"]; return round(float(ema(c,12).iloc[-1]-ema(c,26).iloc[-1]),3)
def bb_calc(df,p=20):
    if df is None or len(df)<p: return 0,0,0
    c=df["Close"]; mid=c.rolling(p).mean().iloc[-1]; std=c.rolling(p).std().iloc[-1]
    return round(float(mid-2*std),2),round(float(mid),2),round(float(mid+2*std),2)
def stoch_calc(df,p=14):
    if df is None or len(df)<p*2: return 50.0
    c=df["Close"].diff(); g=c.clip(lower=0).rolling(p).mean()
    l=(-c.clip(upper=0)).rolling(p).mean(); r=100-(100/(1+g/l))
    lo=r.rolling(p).min(); hi=r.rolling(p).max()
    return round(float((100*(r-lo)/(hi-lo+1e-9)).iloc[-1]),1)

def tf_trend(df,price,prev_c):
    if df is None or len(df)<20: return "Bull" if price>prev_c else "Bear"
    c=df["Close"]; e21=ema(c,21).iloc[-1]; e50=ema(c,50).iloc[-1] if len(c)>=50 else e21
    p=float(c.iloc[-1])
    if p>e21 and e21>e50: return "Bull"
    if p<e21 and e21<e50: return "Bear"
    return "Side"

def calc_pivots(h,l,c):
    pp=round((h+l+c)/3,2)
    return dict(PP=pp,R1=round(2*pp-l,2),R2=round(pp+(h-l),2),R3=round(h+2*(pp-l),2),
                S1=round(2*pp-h,2),S2=round(pp-(h-l),2),S3=round(l-2*(h-pp),2))

def market_struct(df):
    if df is None or len(df)<10: return "Unknown",0
    h=df["High"].rolling(3).max(); l=df["Low"].rolling(3).min()
    if len(h)<4: return "Unknown",0
    if h.iloc[-1]>h.iloc[-3] and l.iloc[-1]>l.iloc[-3]: return "HH+HL Bullish",1
    if h.iloc[-1]<h.iloc[-3] and l.iloc[-1]<l.iloc[-3]: return "LH+LL Bearish",-1
    return "Ranging",0

def get_moon():
    m=ephem.Moon(); m.compute(datetime.date.today()); ph=float(m.phase)
    cycle=(datetime.date.today()-datetime.date(2000,1,6)).days%29.53; cp=cycle/29.53
    if cp<0.03 or cp>0.97: name="New Moon"
    elif cp<0.25: name="Waxing Crescent"
    elif cp<0.27: name="First Quarter"
    elif cp<0.48: name="Waxing Gibbous"
    elif cp<0.52: name="Full Moon"
    elif cp<0.75: name="Waning Gibbous"
    elif cp<0.77: name="Last Quarter"
    else: name="Waning Crescent"
    dtf=int((0.5-cp)*29.53) if cp<0.5 else int((1.5-cp)*29.53)
    icons={"New Moon":"🌑","Waxing Crescent":"🌒","First Quarter":"🌓",
           "Waxing Gibbous":"🌔","Full Moon":"🌕","Waning Gibbous":"🌖",
           "Last Quarter":"🌗","Waning Crescent":"🌘"}
    return icons.get(name,"🌙")+" "+name, round(ph,1), dtf

def get_sessions():
    h=utcnow().hour+utcnow().minute/60
    sessions={"Asia":(0,8),"London":(7,16),"New York":(12,21)}
    kz={"Asia KZ":(0,4),"London KZ":(6,9),"NY KZ":(12,15),"LC KZ":(15,16)}
    act_s=[k for k,(a,b) in sessions.items() if a<=h<b]
    act_k=[k for k,(a,b) in kz.items() if a<=h<b]
    olap=[]
    if 7<=h<8: olap.append("Asia/London")
    if 12<=h<16: olap.append("London/NY")
    return act_s,act_k,olap

def get_news():
    try:
        data=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=8).json()
        today=datetime.date.today().strftime("%Y-%m-%d")
        today_items=[e for e in data if e.get("impact") in ("High","Medium")
                     and e.get("currency")=="USD" and e.get("date","")[:10]==today]
        week_items=[e for e in data if e.get("impact")=="High" and e.get("currency")=="USD"]
        def fmt(e):
            raw=e.get("date","")
            try:
                hh,mm=int(raw[11:13]),int(raw[14:16])
                ist_t=(datetime.datetime(2000,1,1,hh,mm)+IST).strftime("%I:%M %p")
            except: ist_t="?"
            return {"time":ist_t,"title":e["title"],"impact":e["impact"],
                    "forecast":e.get("forecast",""),"prev":e.get("previous","")}
        return [fmt(e) for e in today_items[:6]], [fmt(e) for e in week_items[:8]]
    except: return [],[]

# ── MAIN DATA FETCH ────────────────────────────────────────────────────────────
def fetch_market_data():
    global _cache, _cache_time
    now=time.time()
    if "data" in _cache and now-_cache_time.get("data",0)<CACHE_TTL:
        return _cache["data"]
    try:
        t=yf.Ticker("GC=F")
        d1=t.history(period="10d",interval="1d")
        h4=t.history(period="10d",interval="4h")
        h1=t.history(period="5d",interval="1h")
        m15=t.history(period="5d",interval="15m")
        m5=t.history(period="2d",interval="5m")
        w1=t.history(period="3mo",interval="1wk")
        mo1=t.history(period="12mo",interval="1mo")
        dxy_h=yf.Ticker("DX-Y.NYB").history(period="3d",interval="1h")

        if d1.empty: return None
        tod=d1.iloc[-1]; prev=d1.iloc[-2] if len(d1)>1 else tod
        price=round(float(tod["Close"]),2)
        prev_c=round(float(prev["Close"]),2)
        chg=round(price-prev_c,2); pct=round(chg/prev_c*100,2)

        pvt=calc_pivots(float(prev["High"]),float(prev["Low"]),prev_c)

        tfs=[("1m",None),("5m",m5),("15m",m15),("1H",h1),("4H",h4),("1D",d1)]
        trends={}
        for label,df in tfs:
            trends[label]=tf_trend(df,price,prev_c) if df is not None and not df.empty else ("Bull" if price>prev_c else "Bear")
        bull_c=sum(1 for v in trends.values() if v=="Bull")
        bear_c=sum(1 for v in trends.values() if v=="Bear")
        overall="BULLISH" if bull_c>bear_c else ("BEARISH" if bear_c>bull_c else "NEUTRAL")

        r1h=rsi_calc(h1); r5m=rsi_calc(m5)
        atr5=atr_calc(m5); atr1d=atr_calc(d1)
        macd_h=macd_calc(m5)
        bb_lo,bb_mid,bb_hi=bb_calc(m5)
        stoch=stoch_calc(m5)
        struct_txt,struct_sc=market_struct(h1)

        # Signal scoring
        score=0; reasons=[]
        if "Bull" in trends.get("4H","") or "Bull" in trends.get("1D",""):
            score+=2; reasons.append({"ok":True,"text":"HTF bullish (4H/1D)"})
        elif "Bear" in trends.get("4H","") and "Bear" in trends.get("1D",""):
            score-=2; reasons.append({"ok":False,"text":"HTF bearish (4H/1D)"})
        if price>pvt["PP"]:
            score+=1; reasons.append({"ok":True,"text":f"Above PP ${pvt['PP']:,.2f}"})
        else:
            score-=1; reasons.append({"ok":False,"text":f"Below PP ${pvt['PP']:,.2f}"})
        if r1h<35:
            score+=1; reasons.append({"ok":True,"text":f"RSI 1H oversold ({r1h}) — bounce"})
        elif r1h>65:
            score-=1; reasons.append({"ok":False,"text":f"RSI 1H overbought ({r1h})"})
        if macd_h>0:
            score+=1; reasons.append({"ok":True,"text":"MACD bullish"})
        else:
            score-=1; reasons.append({"ok":False,"text":"MACD bearish"})
        if stoch<25 or bb_lo>0 and price<bb_lo:
            score+=1; reasons.append({"ok":True,"text":f"Oversold zone (Stoch:{stoch})"})
        elif stoch>75:
            score-=1; reasons.append({"ok":False,"text":f"Overbought (Stoch:{stoch})"})
        if struct_sc==1:
            score+=1; reasons.append({"ok":True,"text":struct_txt})
        elif struct_sc==-1:
            score-=1; reasons.append({"ok":False,"text":struct_txt})

        atr_sl=max(atr5*1.2,8); atr_tp=max(atr5*2.0,15)
        if score>=3:
            dirn="BUY"; entry=price; sl=round(price-atr_sl,2)
            tp1=round(price+atr_tp,2); tp2=round(pvt["R1"],2); conf=min(88,55+score*6)
        elif score<=-3:
            dirn="SELL"; entry=price; sl=round(price+atr_sl,2)
            tp1=round(price-atr_tp,2); tp2=round(pvt["S1"],2); conf=min(88,55+abs(score)*6)
        elif score>=1:
            dirn="WEAK BUY"; entry=price; sl=round(price-atr_sl,2)
            tp1=round(price+atr_tp,2); tp2=round(pvt["R1"],2); conf=40+score*5
        elif score<=-1:
            dirn="WEAK SELL"; entry=price; sl=round(price+atr_sl,2)
            tp1=round(price-atr_tp,2); tp2=round(pvt["S1"],2); conf=40+abs(score)*5
        else:
            dirn="WAIT"; entry=price; sl=round(price-atr_sl,2)
            tp1=round(price+atr_tp,2); tp2=round(pvt["R1"],2); conf=30

        risk=round(abs(entry-sl),2); rew=round(abs(tp1-entry),2)
        rr=round(rew/risk,2) if risk>0 else 0

        # DXY
        dxy_price=0; dxy_chg=0; dxy_sent="Neutral"
        if not dxy_h.empty:
            dxy_price=round(float(dxy_h["Close"].iloc[-1]),2)
            dxy_chg=round(dxy_price-float(dxy_h["Close"].iloc[-2]),2)
            dxy_sent="Rising — Bearish Gold" if dxy_chg>0.15 else ("Falling — Bullish Gold" if dxy_chg<-0.15 else "Flat — Neutral")

        act_s,act_k,olap=get_sessions()
        moon_name,moon_pct,dtf=get_moon()
        news_today,news_week=get_news()

        result=dict(
            time=ist_str(), price=price, chg=chg, pct=pct,
            day_h=round(float(tod["High"]),2), day_l=round(float(tod["Low"]),2),
            prev_h=round(float(prev["High"]),2), prev_l=round(float(prev["Low"]),2),
            week_h=round(float(w1["High"].max()),2) if not w1.empty else 0,
            week_l=round(float(w1["Low"].min()),2)  if not w1.empty else 0,
            month_h=round(float(mo1["High"].max()),2) if not mo1.empty else 0,
            month_l=round(float(mo1["Low"].min()),2)  if not mo1.empty else 0,
            atr_day=atr1d, pvt=pvt, trends=trends, overall=overall,
            bull_c=bull_c, bear_c=bear_c,
            rsi_1h=r1h, rsi_5m=r5m, macd_h=macd_h,
            stoch=stoch, bb_lo=bb_lo, bb_mid=bb_mid, bb_hi=bb_hi,
            dirn=dirn, entry=entry, sl=sl, tp1=tp1, tp2=tp2,
            rr=rr, score=score, conf=conf, reasons=reasons,
            dxy_price=dxy_price, dxy_chg=dxy_chg, dxy_sent=dxy_sent,
            sessions=act_s, killzones=act_k, overlap=olap,
            moon=moon_name, moon_pct=moon_pct, moon_dtf=dtf,
            news_today=news_today, news_week=news_week,
            struct=struct_txt,
        )
        _cache["data"]=result; _cache_time["data"]=time.time()
        return result
    except Exception as e:
        print(f"Fetch error: {e}"); return None

# ── HTML DASHBOARD ─────────────────────────────────────────────────────────────
DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAU/USD Pro Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0a0b0e; --bg2: #111318; --bg3: #1a1d24;
  --border: #2a2d35; --border2: #353840;
  --text: #e8eaf0; --text2: #9199a8; --text3: #5a6070;
  --gold: #f0c040; --gold2: #c89820;
  --green: #22c97a; --green2: #0f7a45;
  --red: #f04060; --red2: #8a1530;
  --blue: #4080f0; --blue2: #1a3a80;
  --yellow: #f0a020;
  --radius: 10px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;min-height:100vh;padding:16px}
.mono{font-family:'JetBrains Mono',monospace}

/* HEADER */
.header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:12px}
.header-left h1{font-size:13px;color:var(--text3);font-weight:600;letter-spacing:.15em;text-transform:uppercase;margin-bottom:4px}
.price-main{font-size:42px;font-weight:800;color:var(--gold);font-family:'JetBrains Mono',monospace;line-height:1}
.price-chg{font-size:14px;margin-top:4px;font-weight:600}
.price-chg.up{color:var(--green)} .price-chg.dn{color:var(--red)}
.time-badge{background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:11px;color:var(--text2);font-family:'JetBrains Mono',monospace;text-align:right}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--green);display:inline-block;margin-right:6px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.3)}}

/* GRID */
.grid{display:grid;gap:10px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:1fr 1fr 1fr}
.g4{grid-template-columns:repeat(4,1fr)}

/* CARDS */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:14px}
.card-title{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--text3);margin-bottom:10px}

/* RANGES */
.range-item{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px}
.range-item:last-child{border-bottom:none}
.range-label{color:var(--text2)}
.range-vals{font-family:'JetBrains Mono',monospace;font-size:12px}
.h-val{color:var(--green)} .l-val{color:var(--red)}

/* SIGNAL BOX */
.signal-box{background:var(--bg3);border-radius:8px;padding:14px;margin-bottom:10px}
.signal-direction{font-size:24px;font-weight:800;margin-bottom:8px;font-family:'JetBrains Mono',monospace}
.sig-buy{color:var(--green)} .sig-sell{color:var(--red)} .sig-wait{color:var(--yellow)} .sig-weak{color:var(--yellow)}
.conf-bar-wrap{margin:8px 0}
.conf-label{font-size:11px;color:var(--text2);margin-bottom:4px;display:flex;justify-content:space-between}
.conf-bar{height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.conf-fill{height:100%;border-radius:3px;transition:width .8s ease}
.cf-buy{background:linear-gradient(90deg,var(--green2),var(--green))}
.cf-sell{background:linear-gradient(90deg,var(--red2),var(--red))}
.cf-wait{background:linear-gradient(90deg,#5a4010,var(--yellow))}
.signal-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.sig-item{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px}
.sig-item-label{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:3px}
.sig-item-val{font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace}
.rr-val{color:var(--blue)} .entry-val{color:var(--text)}
.sl-val{color:var(--red)} .tp-val{color:var(--green)}

/* PIVOT */
.pivot-row{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px}
.pivot-row.current{background:rgba(240,192,64,.08);border-radius:6px;padding:5px 8px;margin:2px -4px}
.p-label{min-width:28px;font-weight:700;font-family:'JetBrains Mono',monospace}
.p-r{color:var(--green)} .p-s{color:var(--red)} .p-pp{color:var(--blue)}
.p-bar{flex:1;height:4px;border-radius:2px;overflow:hidden;background:var(--border)}
.p-fill{height:100%;border-radius:2px}
.p-val{min-width:70px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:11px}
.p-now{font-size:10px;color:var(--gold);font-weight:700}

/* TRENDS */
.trend-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.trend-cell{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center}
.trend-cell.bull{border-color:var(--green2);background:rgba(34,201,122,.06)}
.trend-cell.bear{border-color:var(--red2);background:rgba(240,64,96,.06)}
.trend-cell.side{border-color:var(--border2)}
.tf-name{font-size:10px;color:var(--text3);margin-bottom:3px}
.tf-val{font-size:12px;font-weight:700}
.bull .tf-val{color:var(--green)} .bear .tf-val{color:var(--red)} .side .tf-val{color:var(--yellow)}
.overall-badge{background:var(--bg);border-radius:6px;padding:8px 12px;text-align:center;margin-top:8px;font-size:13px;font-weight:700;border:1px solid var(--border)}
.ob-bull{color:var(--green);border-color:var(--green2)} .ob-bear{color:var(--red);border-color:var(--red2)} .ob-neut{color:var(--yellow)}

/* CONFLUENCE */
.conf-item{display:flex;align-items:flex-start;gap:8px;padding:5px 0;font-size:12px;border-bottom:1px solid var(--border)}
.conf-item:last-child{border-bottom:none}
.ci-ok{color:var(--green);font-size:14px} .ci-no{color:var(--red);font-size:14px} .ci-warn{color:var(--yellow);font-size:14px}

/* SESSION */
.sess-pills{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.sess-pill{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;border:1px solid}
.sess-active{background:rgba(34,201,122,.12);border-color:var(--green);color:var(--green)}
.sess-kz{background:rgba(240,160,32,.12);border-color:var(--yellow);color:var(--yellow)}
.sess-overlap{background:rgba(240,64,96,.12);border-color:var(--red);color:var(--red)}
.sess-inactive{background:var(--bg);border-color:var(--border);color:var(--text3)}

/* NEWS */
.news-item{padding:7px 0;border-bottom:1px solid var(--border);font-size:12px}
.news-item:last-child{border-bottom:none}
.ni-imp-h{color:var(--red);font-weight:700;font-size:10px}
.ni-imp-m{color:var(--yellow);font-weight:700;font-size:10px}
.ni-title{color:var(--text);margin:2px 0}
.ni-meta{font-size:10px;color:var(--text3);font-family:'JetBrains Mono',monospace}

/* INDICATORS */
.ind-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px}
.ind-row:last-child{border-bottom:none}
.ind-label{color:var(--text2)}
.ind-val{font-family:'JetBrains Mono',monospace;font-weight:600}
.ind-ob{color:var(--red)} .ind-os{color:var(--green)} .ind-neut{color:var(--text2)}

/* MOON */
.moon-display{display:flex;align-items:center;gap:12px}
.moon-icon{font-size:32px}
.moon-info .phase{font-size:14px;font-weight:700;color:var(--gold)}
.moon-info .detail{font-size:11px;color:var(--text2);margin-top:2px}

/* DXY */
.dxy-row{display:flex;justify-content:space-between;font-size:12px;padding:4px 0}

/* REFRESH */
.refresh-bar{display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding:8px 0;border-top:1px solid var(--border)}
.refresh-btn{background:var(--bg3);border:1px solid var(--border2);color:var(--text2);padding:6px 14px;border-radius:6px;cursor:pointer;font-size:11px;font-family:'Syne',sans-serif}
.refresh-btn:hover{border-color:var(--gold);color:var(--gold)}
.countdown{font-size:11px;color:var(--text3);font-family:'JetBrains Mono',monospace}

/* SCORE BADGE */
.score-badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;margin-top:6px}
.sb-strong{background:rgba(34,201,122,.15);color:var(--green);border:1px solid var(--green2)}
.sb-weak{background:rgba(240,160,32,.15);color:var(--yellow);border:1px solid #6a5010}
.sb-wait{background:var(--bg);color:var(--text3);border:1px solid var(--border)}

@media(max-width:600px){.g2,.g3,.g4{grid-template-columns:1fr 1fr} .g4{grid-template-columns:1fr 1fr} .trend-grid{grid-template-columns:repeat(3,1fr)} .price-main{font-size:32px}}
</style>
</head>
<body>
<div id="root">Loading...</div>
<script>
let refreshTimer;

async function loadData() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    render(d);
    startCountdown(300);
  } catch(e) {
    document.getElementById('root').innerHTML = '<div style="color:#f04060;padding:20px">Error loading data. Refreshing...</div>';
    setTimeout(loadData, 5000);
  }
}

function fmt(n) { return '$' + parseFloat(n).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:2}); }
function pct_bar(val, max, cls) {
  const w = Math.min(100, Math.abs(val/max)*100);
  return `<div class="p-bar"><div class="p-fill ${cls}" style="width:${w}%"></div></div>`;
}

function render(d) {
  const upDown = d.chg >= 0;
  const sigCls = d.dirn.includes('BUY') ? 'sig-buy' : d.dirn.includes('SELL') ? 'sig-sell' : 'sig-wait';
  const cfCls  = d.dirn.includes('BUY') ? 'cf-buy'  : d.dirn.includes('SELL') ? 'cf-sell'  : 'cf-wait';
  const isBuy  = d.dirn.includes('BUY');
  const isSell = d.dirn.includes('SELL');

  // Trend cells
  const trendOrder = ['1m','5m','15m','1H','4H','1D'];
  const trendCells = trendOrder.map(tf => {
    const v = d.trends[tf] || 'Side';
    const cls = v==='Bull'?'bull':v==='Bear'?'bear':'side';
    return `<div class="trend-cell ${cls}"><div class="tf-name">${tf}</div><div class="tf-val">${v}</div></div>`;
  }).join('');

  const obCls = d.overall==='BULLISH'?'ob-bull':d.overall==='BEARISH'?'ob-bear':'ob-neut';

  // Confluence
  const confItems = (d.reasons||[]).map(r =>
    `<div class="conf-item"><span class="${r.ok?'ci-ok':'ci-no'}">${r.ok?'✓':'✗'}</span><span>${r.text}</span></div>`
  ).join('');

  // Pivots
  const pvt = d.pvt;
  const pvtRows = [
    {k:'R3',v:pvt.R3,cls:'p-r'},{k:'R2',v:pvt.R2,cls:'p-r'},{k:'R1',v:pvt.R1,cls:'p-r'},
    {k:'PP',v:pvt.PP,cls:'p-pp'},
    {k:'S1',v:pvt.S1,cls:'p-s'},{k:'S2',v:pvt.S2,cls:'p-s'},{k:'S3',v:pvt.S3,cls:'p-s'},
  ].map(p => {
    const isCur = Math.abs(d.price-p.v)<10;
    const barCls = p.cls==='p-r'?'background:var(--green)':p.cls==='p-s'?'background:var(--red)':'background:var(--blue)';
    const barW = Math.min(100,Math.abs(p.v-pvt.S3)/(pvt.R3-pvt.S3)*100);
    return `<div class="pivot-row ${isCur?'current':''}">
      <span class="p-label ${p.cls}">${p.k}</span>
      <div class="p-bar" style="flex:1"><div class="p-fill" style="width:${barW}%;${barCls}"></div></div>
      <span class="p-val ${p.cls}">${fmt(p.v)}</span>
      ${isCur?`<span class="p-now">◀ NOW</span>`:''}
    </div>`;
  }).join('');

  // Sessions
  const allSess = ['Asia','London','New York'];
  const sessHTML = allSess.map(s => {
    const active = d.sessions.includes(s);
    return `<span class="sess-pill ${active?'sess-active':'sess-inactive'}">${s}</span>`;
  }).join('');
  const kzHTML = d.killzones.map(k => `<span class="sess-pill sess-kz">${k}</span>`).join('');
  const olHTML = d.overlap.map(o => `<span class="sess-pill sess-overlap">⚡ ${o}</span>`).join('');

  // News today
  const newsHTML = d.news_today.length ? d.news_today.map(n =>
    `<div class="news-item">
      <span class="${n.impact==='High'?'ni-imp-h':'ni-imp-m'}">${n.impact}</span>
      <div class="ni-title">${n.title}</div>
      <div class="ni-meta">${n.time} IST | Forecast: ${n.forecast||'-'}</div>
    </div>`).join('') : '<div style="font-size:12px;color:var(--green);padding:6px 0">✓ No major USD news today</div>';

  // News week
  const newsWkHTML = d.news_week.length ? d.news_week.map(n =>
    `<div class="news-item"><span class="ni-imp-h">HIGH</span> <span style="font-size:12px">${n.title}</span> <span class="ni-meta">${n.time} IST</span></div>`
  ).join('') : '<div style="font-size:12px;color:var(--text3);padding:6px 0">No high-impact events this week</div>';

  // RSI color
  function rsiCls(v){ return v>70?'ind-ob':v<30?'ind-os':'ind-neut'; }

  // Score badge
  const absSc = Math.abs(d.score);
  const sbCls = absSc>=3?'sb-strong':absSc>=1?'sb-weak':'sb-wait';
  const sbTxt = absSc>=3?`Score ${d.score}/6 — Strong`:`Score ${d.score}/6 — ${absSc>=1?'Moderate':'Wait'}`;

  document.getElementById('root').innerHTML = `
<div class="header">
  <div class="header-left">
    <h1><span class="live-dot"></span>XAU/USD · LIVE DASHBOARD</h1>
    <div class="price-main mono">${fmt(d.price)}</div>
    <div class="price-chg ${upDown?'up':'dn'}">${upDown?'▲':'▼'} ${Math.abs(d.chg)} (${Math.abs(d.pct)}%)</div>
  </div>
  <div class="time-badge">${d.time}<br>ATR: ${fmt(d.atr_day)} | ${d.struct}</div>
</div>

<div class="grid g2" style="margin-bottom:10px">
  <div class="card">
    <div class="card-title">Key Levels</div>
    <div class="range-item"><span class="range-label">Day Range</span><span class="range-vals"><span class="h-val">${fmt(d.day_h)}</span> — <span class="l-val">${fmt(d.day_l)}</span></span></div>
    <div class="range-item"><span class="range-label">Prev Day</span><span class="range-vals"><span class="h-val">${fmt(d.prev_h)}</span> — <span class="l-val">${fmt(d.prev_l)}</span></span></div>
    <div class="range-item"><span class="range-label">Week</span><span class="range-vals"><span class="h-val">${fmt(d.week_h)}</span> — <span class="l-val">${fmt(d.week_l)}</span></span></div>
    <div class="range-item"><span class="range-label">Month</span><span class="range-vals"><span class="h-val">${fmt(d.month_h)}</span> — <span class="l-val">${fmt(d.month_l)}</span></span></div>
  </div>
  <div class="card">
    <div class="card-title">Signal</div>
    <div class="signal-box">
      <div class="signal-direction ${sigCls}">${d.dirn}</div>
      <div class="conf-bar-wrap">
        <div class="conf-label"><span>Confidence</span><span>${d.conf}%</span></div>
        <div class="conf-bar"><div class="conf-fill ${cfCls}" style="width:${d.conf}%"></div></div>
      </div>
      <div class="score-badge ${sbCls}">${sbTxt}</div>
    </div>
    <div class="signal-grid">
      <div class="sig-item"><div class="sig-item-label">Entry</div><div class="sig-item-val entry-val">${fmt(d.entry)}</div></div>
      <div class="sig-item"><div class="sig-item-label">Stop Loss</div><div class="sig-item-val sl-val">${fmt(d.sl)}</div></div>
      <div class="sig-item"><div class="sig-item-label">TP1</div><div class="sig-item-val tp-val">${fmt(d.tp1)}</div></div>
      <div class="sig-item"><div class="sig-item-label">R:R</div><div class="sig-item-val rr-val">1 : ${d.rr}</div></div>
    </div>
  </div>
</div>

<div class="grid g2" style="margin-bottom:10px">
  <div class="card">
    <div class="card-title">Pivot Points</div>
    ${pvtRows}
  </div>
  <div class="card">
    <div class="card-title">Confluence Check</div>
    ${confItems}
  </div>
</div>

<div class="card" style="margin-bottom:10px">
  <div class="card-title">Multi-Timeframe Trend</div>
  <div class="trend-grid">${trendCells}</div>
  <div class="overall-badge ${obCls}">Overall: ${d.overall} &nbsp;|&nbsp; ${d.bull_c} Bull / ${d.bear_c} Bear</div>
</div>

<div class="grid g2" style="margin-bottom:10px">
  <div class="card">
    <div class="card-title">Indicators</div>
    <div class="ind-row"><span class="ind-label">RSI 1H</span><span class="ind-val ${rsiCls(d.rsi_1h)}">${d.rsi_1h} ${d.rsi_1h>70?'OB':d.rsi_1h<30?'OS':''}</span></div>
    <div class="ind-row"><span class="ind-label">RSI 5m</span><span class="ind-val ${rsiCls(d.rsi_5m)}">${d.rsi_5m} ${d.rsi_5m>70?'OB':d.rsi_5m<30?'OS':''}</span></div>
    <div class="ind-row"><span class="ind-label">MACD 5m</span><span class="ind-val ${d.macd_h>0?'ind-os':'ind-ob'}">${d.macd_h>0?'▲ Bull':'▼ Bear'} (${d.macd_h})</span></div>
    <div class="ind-row"><span class="ind-label">StochRSI</span><span class="ind-val ${rsiCls(d.stoch)}">${d.stoch} ${d.stoch>80?'OB':d.stoch<20?'OS':''}</span></div>
    <div class="ind-row"><span class="ind-label">BB Low/Mid/Hi</span><span class="ind-val ind-neut" style="font-size:10px">${fmt(d.bb_lo)} / ${fmt(d.bb_mid)}</span></div>
  </div>
  <div class="card">
    <div class="card-title">Sessions & Kill Zones</div>
    <div class="sess-pills">${sessHTML}${kzHTML}${olHTML||'<span style="font-size:11px;color:var(--text3)">No overlap</span>'}</div>
    <div style="font-size:11px;color:var(--text2);margin-top:6px">
      ${d.overlap.length?'<span style="color:var(--red)">⚡ OVERLAP ACTIVE — Highest volatility. Best time for breakouts.</span>':'Waiting for kill zone / overlap for best signals.'}
    </div>
    <div style="margin-top:10px">
      <div class="dxy-row"><span style="color:var(--text2)">DXY</span><span class="mono" style="color:var(--gold)">${d.dxy_price}</span></div>
      <div style="font-size:11px;color:var(--text2);margin-top:2px">${d.dxy_sent}</div>
    </div>
    <div style="margin-top:10px">
      <div class="moon-display">
        <div class="moon-icon">${d.moon.split(' ')[0]}</div>
        <div class="moon-info">
          <div class="phase">${d.moon.split(' ').slice(1).join(' ')}</div>
          <div class="detail">${d.moon_pct}% illuminated · Full moon in ${d.moon_dtf} days</div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="grid g2" style="margin-bottom:10px">
  <div class="card">
    <div class="card-title">Today's News (IST)</div>
    ${newsHTML}
  </div>
  <div class="card">
    <div class="card-title">Weekly Calendar</div>
    ${newsWkHTML}
  </div>
</div>

<div class="refresh-bar">
  <span class="countdown" id="countdown">Refreshing in 5:00</span>
  <button class="refresh-btn" onclick="loadData()">↻ Refresh Now</button>
</div>
`;
}

function startCountdown(sec) {
  clearInterval(refreshTimer);
  let s = sec;
  refreshTimer = setInterval(() => {
    s--;
    const el = document.getElementById('countdown');
    if(el) el.textContent = `Refreshing in ${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
    if(s<=0){ clearInterval(refreshTimer); loadData(); }
  }, 1000);
}

loadData();
</script>
</body>
</html>'''

@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/data')
def api_data():
    d = fetch_market_data()
    if d is None:
        return jsonify({"error": "Data unavailable"}), 503
    return jsonify(d)

@app.route('/health')
def health():
    return jsonify({"status":"ok","time":ist_str()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Dashboard starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
