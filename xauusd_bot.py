"""
GOLD SCALPING PRO BOT v5
- Balanced signal scoring (not too tight, not too loose)
- Full details har 1 ghante mein
- ICT + SMC + Multi-indicator confluence
- ATR-based dynamic SL/TP
- DXY correlation
- No double firing
"""
import os, datetime, requests, ephem, time
import yfinance as yf
import pandas as pd

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",  "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","")
WA_PHONE         = os.environ.get("WA_PHONE",  "")
WA_APIKEY        = os.environ.get("WA_APIKEY", "")
ALERT_MODE       = os.environ.get("ALERT_MODE", "full")
IST              = datetime.timedelta(hours=5, minutes=30)

PAIRS = {
    "XAU/USD": "GC=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "US30":    "YM=F",
    "NAS100":  "NQ=F",
    "OIL":     "CL=F",
    "BTC/USD": "BTC-USD",
    "DXY":     "DX-Y.NYB",
}

# ── TIME ──────────────────────────────────────────────────────────────────────
def utcnow(): return datetime.datetime.utcnow()
def istnow(): return utcnow() + IST
def ist_str(): return istnow().strftime("%d %b %Y  %I:%M %p IST")
def utc_h():   n=utcnow(); return n.hour + n.minute/60

# ── SENDERS ───────────────────────────────────────────────────────────────────
def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    for part in [msg[i:i+4000] for i in range(0,len(msg),4000)]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id":TELEGRAM_CHAT_ID,"text":part,
                      "parse_mode":"HTML","disable_web_page_preview":True},
                timeout=15)
            print("✅ TG" if r.status_code==200 else f"⚠️ {r.text[:60]}")
            time.sleep(0.5)
        except Exception as e: print(f"❌ TG: {e}")

def send_whatsapp(msg):
    if not WA_PHONE or not WA_APIKEY: return
    import re
    clean = re.sub(r"<[^>]+>","",msg)[:1500]
    try:
        requests.get("https://api.callmebot.com/whatsapp.php",
            params={"phone":WA_PHONE,"text":clean,"apikey":WA_APIKEY},timeout=15)
    except: pass

def send_all(msg): send_telegram(msg); send_whatsapp(msg)

# ── DATA ──────────────────────────────────────────────────────────────────────
def get_data(symbol="GC=F"):
    try:
        t   = yf.Ticker(symbol)
        d1  = t.history(period="10d",  interval="1d")
        h4  = t.history(period="10d",  interval="4h")
        h1  = t.history(period="5d",   interval="1h")
        m15 = t.history(period="5d",   interval="15m")
        m5  = t.history(period="2d",   interval="5m")
        w1  = t.history(period="3mo",  interval="1wk")
        mo1 = t.history(period="12mo", interval="1mo")
        if d1.empty: return None
        tod  = d1.iloc[-1]
        prev = d1.iloc[-2] if len(d1)>1 else tod
        return dict(
            price   = round(float(tod["Close"]),2),
            day_h   = round(float(tod["High"]),2),
            day_l   = round(float(tod["Low"]),2),
            day_o   = round(float(tod["Open"]),2),
            prev_h  = round(float(prev["High"]),2),
            prev_l  = round(float(prev["Low"]),2),
            prev_c  = round(float(prev["Close"]),2),
            week_h  = round(float(w1["High"].max()),2)  if not w1.empty  else 0,
            week_l  = round(float(w1["Low"].min()),2)   if not w1.empty  else 0,
            month_h = round(float(mo1["High"].max()),2) if not mo1.empty else 0,
            month_l = round(float(mo1["Low"].min()),2)  if not mo1.empty else 0,
            d1=d1, h4=h4, h1=h1, m15=m15, m5=m5,
        )
    except Exception as e:
        print(f"Data error: {e}"); return None

# ── INDICATORS ────────────────────────────────────────────────────────────────
def ema(s,p): return s.ewm(span=p,adjust=False).mean()

def rsi_val(df, p=14):
    if df is None or len(df)<p+1: return 50.0
    d=df["Close"].diff()
    g=d.clip(lower=0).rolling(p).mean()
    l=(-d.clip(upper=0)).rolling(p).mean()
    return round(float((100-100/(1+g/l)).iloc[-1]),1)

def macd_signal(df):
    if df is None or len(df)<26: return "⚪", 0
    c=df["Close"]
    hist = ema(c,12).iloc[-1] - ema(c,26).iloc[-1]
    prev_hist = ema(c,12).iloc[-2] - ema(c,26).iloc[-2] if len(c)>2 else hist
    if hist>0 and hist>prev_hist: return "📈 Bull Cross", round(hist,3)
    if hist>0:                    return "📈 Bull",       round(hist,3)
    if hist<0 and hist<prev_hist: return "📉 Bear Cross", round(hist,3)
    return "📉 Bear", round(hist,3)

def atr_val(df, p=14):
    if df is None or len(df)<p+1: return 5.0
    h=df["High"]; l=df["Low"]; c=df["Close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return round(float(tr.rolling(p).mean().iloc[-1]),2)

def bollinger_pos(df, p=20):
    """Returns: 'above upper', 'below lower', 'near mid', 'upper half', 'lower half'"""
    if df is None or len(df)<p: return "unknown", 0, 0, 0
    c=df["Close"]
    mid=c.rolling(p).mean().iloc[-1]
    std=c.rolling(p).std().iloc[-1]
    upper=mid+2*std; lower=mid-2*std
    price=float(c.iloc[-1])
    if price>upper:   pos="🔴 Above upper BB"
    elif price<lower: pos="🟢 Below lower BB (oversold)"
    elif price>mid:   pos="🟡 Upper half BB"
    else:             pos="🟡 Lower half BB"
    return pos, round(lower,2), round(mid,2), round(upper,2)

def stoch_rsi_val(df, p=14):
    if df is None or len(df)<p*2: return 50.0
    c=df["Close"].diff()
    g=c.clip(lower=0).rolling(p).mean()
    l=(-c.clip(upper=0)).rolling(p).mean()
    r=100-(100/(1+g/l))
    lo=r.rolling(p).min(); hi=r.rolling(p).max()
    s=100*(r-lo)/(hi-lo+1e-9)
    return round(float(s.iloc[-1]),1)

# ── SMART MONEY ───────────────────────────────────────────────────────────────
def market_structure(df):
    if df is None or len(df)<10: return "⚪ Unknown", 0
    h=df["High"].rolling(3).max(); l=df["Low"].rolling(3).min()
    if len(h)<4: return "⚪ Unknown", 0
    hh = h.iloc[-1]>h.iloc[-3]; hl = l.iloc[-1]>l.iloc[-3]
    lh = h.iloc[-1]<h.iloc[-3]; ll = l.iloc[-1]<l.iloc[-3]
    if hh and hl:  return "📈 HH+HL (Bullish)", 1
    if lh and ll:  return "📉 LH+LL (Bearish)", -1
    return "🔄 Ranging", 0

def find_ob(df):
    """Simple Order Block finder"""
    if df is None or len(df)<5: return None, None
    bull_ob=None; bear_ob=None
    for i in range(len(df)-6, len(df)-1):
        try:
            c=df.iloc[i]; n=df.iloc[i+1]
            if c["Close"]<c["Open"] and n["Close"]>n["Open"]:
                bull_ob=round(float(c["Low"]),2)
            if c["Close"]>c["Open"] and n["Close"]<n["Open"]:
                bear_ob=round(float(c["High"]),2)
        except: continue
    return bull_ob, bear_ob

# ── PIVOTS ────────────────────────────────────────────────────────────────────
def calc_pivots(h,l,c):
    pp=round((h+l+c)/3,2)
    return dict(PP=pp,
        R1=round(2*pp-l,2),R2=round(pp+(h-l),2),R3=round(h+2*(pp-l),2),
        S1=round(2*pp-h,2),S2=round(pp-(h-l),2),S3=round(l-2*(h-pp),2))

# ── TREND ─────────────────────────────────────────────────────────────────────
def trend(df, price, prev_c):
    if df is None or len(df)<20:
        return "🟢 Bull" if price>prev_c else "🔴 Bear"
    c=df["Close"]
    e21=ema(c,21).iloc[-1]; e50=ema(c,50).iloc[-1] if len(c)>=50 else e21
    p=float(c.iloc[-1])
    if p>e21 and e21>e50: return "🟢 Bull"
    if p<e21 and e21<e50: return "🔴 Bear"
    if p>e21: return "🟡 Weak Bull"
    if p<e21: return "🟡 Weak Bear"
    return "🟡 Side"

def all_trends(d):
    pc,pr=d["prev_c"],d["price"]
    tfs=[("1H",d["h1"]),("4H",d["h4"]),("15m",d["m15"]),("5m",d["m5"]),("1D",d["d1"])]
    res={}
    for l,df in tfs: res[l]=trend(df,pr,pc)
    bull=sum(1 for v in res.values() if "Bull" in v)
    bear=sum(1 for v in res.values() if "Bear" in v)
    ov="🟢 BULLISH" if bull>bear else ("🔴 BEARISH" if bear>bull else "🟡 NEUTRAL")
    return res,ov,bull,bear

# ── BALANCED SIGNAL SCORING (6 factors, threshold=3) ─────────────────────────
def get_signal(d, pvt, trends, overall, bull_c, bear_c):
    price   = d["price"]
    atr     = atr_val(d["m5"])
    r1_rsi  = rsi_val(d["h1"])
    r5_rsi  = rsi_val(d["m5"])
    macd_txt, macd_h = macd_signal(d["m5"])
    bb_pos, bb_lo, bb_mid, bb_hi = bollinger_pos(d["m5"])
    stoch   = stoch_rsi_val(d["m5"])
    struct_txt, struct_score = market_structure(d["h1"])
    bull_ob, bear_ob = find_ob(d["m5"])
    pp=pvt["PP"]; r1=pvt["R1"]; s1=pvt["S1"]

    score=0; bull_r=[]; bear_r=[]

    # ── FACTOR 1: HTF Trend (most important — 2 pts) ──────────────────────────
    if "Bull" in trends.get("4H","") or "Bull" in trends.get("1D",""):
        score+=2; bull_r.append("✅ HTF bullish (4H/1D)")
    elif "Bear" in trends.get("4H","") and "Bear" in trends.get("1D",""):
        score-=2; bear_r.append("❌ HTF bearish (4H/1D)")

    # ── FACTOR 2: Price vs Pivot ───────────────────────────────────────────────
    if price>pp:
        score+=1; bull_r.append(f"✅ Above PP ${pp:,.2f}")
    else:
        score-=1; bear_r.append(f"❌ Below PP ${pp:,.2f}")

    # ── FACTOR 3: RSI 1H ──────────────────────────────────────────────────────
    if r1_rsi<35:
        score+=1; bull_r.append(f"✅ RSI 1H oversold ({r1_rsi}) — bounce zone")
    elif r1_rsi>65:
        score-=1; bear_r.append(f"❌ RSI 1H overbought ({r1_rsi})")

    # ── FACTOR 4: MACD 5m ─────────────────────────────────────────────────────
    if "Bull" in macd_txt:
        score+=1; bull_r.append(f"✅ MACD {macd_txt}")
    elif "Bear" in macd_txt:
        score-=1; bear_r.append(f"❌ MACD {macd_txt}")

    # ── FACTOR 5: Bollinger / StochRSI ────────────────────────────────────────
    if "Below lower" in bb_pos or stoch<25:
        score+=1; bull_r.append(f"✅ Oversold: {bb_pos} | StochRSI:{stoch}")
    elif "Above upper" in bb_pos or stoch>75:
        score-=1; bear_r.append(f"❌ Overbought: {bb_pos} | StochRSI:{stoch}")

    # ── FACTOR 6: Market Structure ────────────────────────────────────────────
    if struct_score==1:
        score+=1; bull_r.append(f"✅ {struct_txt}")
    elif struct_score==-1:
        score-=1; bear_r.append(f"❌ {struct_txt}")

    # ── ATR BASED SL/TP ───────────────────────────────────────────────────────
    sl_dist = max(atr*1.2, 8)
    tp_dist = max(atr*2.0, 15)

    # ── DECISION (threshold: +3 buy, -3 sell) ─────────────────────────────────
    if score>=3:
        dirn="🟢 BUY"; strength="STRONG" if score>=5 else "MODERATE"
        entry=round(price,2)
        sl=round(price-sl_dist,2)
        tp1=round(price+tp_dist,2)
        tp2=round(r1,2)
        conf=min(90, 55+score*6)
    elif score<=-3:
        dirn="🔴 SELL"; strength="STRONG" if score<=-5 else "MODERATE"
        entry=round(price,2)
        sl=round(price+sl_dist,2)
        tp1=round(price-tp_dist,2)
        tp2=round(s1,2)
        conf=min(90, 55+abs(score)*6)
    elif score>=1:
        dirn="🟡 WEAK BUY"; strength="WEAK"
        entry=round(price,2)
        sl=round(price-sl_dist,2)
        tp1=round(price+tp_dist,2)
        tp2=round(r1,2)
        conf=40+score*5
    elif score<=-1:
        dirn="🟡 WEAK SELL"; strength="WEAK"
        entry=round(price,2)
        sl=round(price+sl_dist,2)
        tp1=round(price-tp_dist,2)
        tp2=round(s1,2)
        conf=40+abs(score)*5
    else:
        dirn="⚪ NO TRADE"; strength="WAIT"
        entry=price; sl=round(price-sl_dist,2)
        tp1=round(price+tp_dist,2); tp2=round(r1,2)
        conf=30

    risk=round(abs(entry-sl),2); rew=round(abs(tp1-entry),2)
    rr=round(rew/risk,2) if risk>0 else 0
    all_reasons = bull_r+bear_r

    return dict(
        dirn=dirn,strength=strength,entry=entry,sl=sl,tp1=tp1,tp2=tp2,
        rr=rr,score=score,conf=conf,
        rsi_1h=r1_rsi,rsi_5m=r5_rsi,
        macd_txt=macd_txt,macd_h=macd_h,
        stoch=stoch,atr=atr,
        bb_pos=bb_pos,bb_lo=bb_lo,bb_mid=bb_mid,bb_hi=bb_hi,
        struct_txt=struct_txt,
        bull_ob=bull_ob,bear_ob=bear_ob,
        reasons=all_reasons
    )

# ── DXY ───────────────────────────────────────────────────────────────────────
def get_dxy():
    try:
        h=yf.Ticker("DX-Y.NYB").history(period="3d",interval="1h")
        if h.empty: return None
        price=round(float(h["Close"].iloc[-1]),2)
        chg=round(price-float(h["Close"].iloc[-2]),2)
        r=rsi_val(h)
        if chg>0.15:   sent="📈 Rising — Bearish for Gold"
        elif chg<-0.15:sent="📉 Falling — Bullish for Gold"
        else:          sent="➡️ Flat — Neutral"
        return dict(price=price,chg=chg,rsi=r,sent=sent)
    except: return None

# ── SESSIONS ──────────────────────────────────────────────────────────────────
def get_sessions():
    h=utc_h()
    s_map ={"Asia":(0,8),"London":(7,16),"New York":(12,21)}
    kz_map={"Asia KZ":(0,4),"London KZ":(6,9),"NY KZ":(12,15),"LC KZ":(15,16)}
    act_s=[k for k,(a,b) in s_map.items()  if a<=h<b]
    act_k=[k for k,(a,b) in kz_map.items() if a<=h<b]
    olap=[]
    if 7<=h<8:   olap.append("Asia/London ⚡")
    if 12<=h<16: olap.append("London/NY ⚡ BEST TIME")
    best=len(act_k)>0 or len(olap)>0
    # Next opens
    next_opens=[]
    opens_utc={"London":7,"New York":12,"Asia":0}
    for name,oh in opens_utc.items():
        if h<oh:
            diff=oh-h
            t=(utcnow()+IST+datetime.timedelta(hours=diff)).strftime("%I:%M %p")
            next_opens.append(f"{name} opens {t} IST")
    return act_s,act_k,olap,best,next_opens

# ── MOON ──────────────────────────────────────────────────────────────────────
def get_moon():
    m=ephem.Moon(); m.compute(datetime.date.today()); ph=float(m.phase)
    # Correct phase name
    cycle=(datetime.date.today()-datetime.date(2000,1,6)).days % 29.53
    cyc_pct=cycle/29.53
    if cyc_pct<0.03 or cyc_pct>0.97: name="🌑 New Moon"
    elif cyc_pct<0.25: name="🌒 Waxing Crescent"
    elif cyc_pct<0.27: name="🌓 First Quarter"
    elif cyc_pct<0.48: name="🌔 Waxing Gibbous"
    elif cyc_pct<0.52: name="🌕 Full Moon"
    elif cyc_pct<0.75: name="🌖 Waning Gibbous"
    elif cyc_pct<0.77: name="🌗 Last Quarter"
    else: name="🌘 Waning Crescent"
    days_to_full=int((0.5-cyc_pct)*29.53) if cyc_pct<0.5 else int((1.5-cyc_pct)*29.53)
    return name, round(ph,1), days_to_full

# ── NEWS ──────────────────────────────────────────────────────────────────────
def get_news(week=False):
    try:
        data=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=10).json()
        today=datetime.date.today().strftime("%Y-%m-%d")
        if week:
            items=[e for e in data if e.get("impact")=="High" and e.get("currency")=="USD"]
        else:
            items=[e for e in data if e.get("impact") in ("High","Medium")
                   and e.get("currency")=="USD" and e.get("date","")[:10]==today]
        if not items:
            return "  ✅ No major USD news — Clean technical day" if not week else "  No high-impact events this week"
        out=[]
        for e in items[:8]:
            raw=e.get("date","")
            try:
                hh,mm=int(raw[11:13]),int(raw[14:16])
                ist_t=(datetime.datetime(2000,1,1,hh,mm)+IST).strftime("%I:%M %p")
                if week:
                    day=datetime.datetime.strptime(raw[:10],"%Y-%m-%d").strftime("%a %d")
                    out.append(f"  🔴 {day} {ist_t} IST — {e['title']}")
                else:
                    fc=e.get("forecast","") or "-"
                    out.append(f"  🔴 {ist_t} IST — {e['title']} | Fcst:{fc}")
            except: pass
        return "\n".join(out)
    except: return "  Error fetching news"

# ── VOLATILITY SCANNER ────────────────────────────────────────────────────────
def vol_scan():
    results=[]
    for name,sym in PAIRS.items():
        if name=="DXY": continue
        try:
            h=yf.Ticker(sym).history(period="2d",interval="1h")
            if h.empty or len(h)<3: continue
            price=round(float(h["Close"].iloc[-1]),2)
            chg=round((float(h["Close"].iloc[-1])-float(h["Close"].iloc[-2]))/float(h["Close"].iloc[-2])*100,2)
            a=atr_val(h)
            results.append((name,price,chg,a))
        except: continue
    results.sort(key=lambda x:abs(x[2]),reverse=True)
    lines=[]
    for name,price,chg,a in results[:5]:
        arr="▲" if chg>=0 else "▼"
        hot="🔥" if abs(chg)>0.5 else "⚡" if abs(chg)>0.2 else "➡️"
        lines.append(f"  {hot} {name}: ${price:,} {arr}{abs(chg)}%")
    return "\n".join(lines)

# ── FULL HOURLY ALERT ─────────────────────────────────────────────────────────
def full_alert(d):
    price=d["price"]
    chg=round(price-d["prev_c"],2)
    pct=round(chg/d["prev_c"]*100,2) if d["prev_c"] else 0
    arr="▲" if chg>=0 else "▼"

    pvt=calc_pivots(d["prev_h"],d["prev_l"],d["prev_c"])
    trends,overall,bull_c,bear_c=all_trends(d)
    sig=get_signal(d,pvt,trends,overall,bull_c,bear_c)
    act_s,act_k,olap,best,next_op=get_sessions()
    moon_n,moon_p,dtf=get_moon()
    dxy=get_dxy()
    n_today=get_news()
    n_week=get_news(week=True)
    scan=vol_scan()
    timing="🎯 BEST TIME — Trade now!" if best else "⏳ Wait for kill zone"
    conf_bar="█"*int(sig['conf']//10)+"░"*(10-int(sig['conf']//10))

    # Signal color
    if "BUY" in sig['dirn'] and "WEAK" not in sig['dirn']:   sig_emoji="🚀"
    elif "SELL" in sig['dirn'] and "WEAK" not in sig['dirn']: sig_emoji="🔻"
    elif "WEAK" in sig['dirn']: sig_emoji="⚠️"
    else: sig_emoji="⏸️"

    msg=f"""
🏆 <b>SCALPING PRO — HOURLY BRIEF</b>
📅 {ist_str()}
{timing}

━━━━━━━━━━━━━━━━━━━━
💰 <b>XAU/USD</b>: ${price:,.2f}  {arr}{abs(chg)} ({abs(pct)}%)
📊 ATR(14): ${sig['atr']:,.1f} | Day range: ${d['day_h']-d['day_l']:,.1f}

━━━━━━━━━━━━━━━━━━━━
{sig_emoji} <b>SIGNAL: {sig['dirn']}</b>  [{sig['strength']}]
  [{conf_bar}] {sig['conf']}% confidence
  Score: {sig['score']}/6

  📍 Entry : ${sig['entry']:,.2f}
  🛑 SL    : ${sig['sl']:,.2f}  (${sig['atr']:.1f} ATR)
  🎯 TP1   : ${sig['tp1']:,.2f}
  🎯 TP2   : ${sig['tp2']:,.2f}
  ⚖️ R:R   : 1 : {sig['rr']}

━━━━━━━━━━━━━━━━━━━━
🧠 <b>WHY THIS SIGNAL</b>
"""+"\n".join(f"  {r}" for r in sig['reasons'])+f"""

━━━━━━━━━━━━━━━━━━━━
📐 <b>SMART MONEY</b>
  Structure : {sig['struct_txt']}
  Bull OB   : ${sig['bull_ob']:,.2f}""" + (f"\n  Bear OB   : ${sig['bear_ob']:,.2f}" if sig['bear_ob'] else "") + f"""

━━━━━━━━━━━━━━━━━━━━
📊 <b>KEY LEVELS</b>
  Day   H/L : ${d['day_h']:,.2f} / ${d['day_l']:,.2f}
  Prev  H/L : ${d['prev_h']:,.2f} / ${d['prev_l']:,.2f}
  Week  H/L : ${d['week_h']:,.2f} / ${d['week_l']:,.2f}
  Month H/L : ${d['month_h']:,.2f} / ${d['month_l']:,.2f}

━━━━━━━━━━━━━━━━━━━━
📐 <b>PIVOTS</b>
  R3:${pvt['R3']:,.2f} R2:${pvt['R2']:,.2f} R1:${pvt['R1']:,.2f}
  PP:${pvt['PP']:,.2f}
  S1:${pvt['S1']:,.2f} S2:${pvt['S2']:,.2f} S3:${pvt['S3']:,.2f}

━━━━━━━━━━━━━━━━━━━━
📈 <b>TRENDS</b>
  5m :{trends.get('5m','?')}  15m:{trends.get('15m','?')}
  1H :{trends.get('1H','?')}  4H :{trends.get('4H','?')}
  1D :{trends.get('1D','?')}
  ▶ Overall: {overall} ({bull_c} bull / {bear_c} bear)

━━━━━━━━━━━━━━━━━━━━
📉 <b>INDICATORS</b>
  RSI 1H  : {sig['rsi_1h']} {'🔴OB' if sig['rsi_1h']>70 else '🟢OS' if sig['rsi_1h']<30 else '⚪'}
  RSI 5m  : {sig['rsi_5m']} {'🔴OB' if sig['rsi_5m']>70 else '🟢OS' if sig['rsi_5m']<30 else '⚪'}
  MACD    : {sig['macd_txt']}
  StochRSI: {sig['stoch']} {'🔴OB' if sig['stoch']>80 else '🟢OS' if sig['stoch']<20 else '⚪'}
  BB      : {sig['bb_pos']}

━━━━━━━━━━━━━━━━━━━━
💵 <b>DXY</b>: ${dxy['price'] if dxy else 'N/A'} | {dxy['sent'] if dxy else 'N/A'}

━━━━━━━━━━━━━━━━━━━━
🌐 <b>SESSIONS</b>
  Active: {', '.join(act_s) if act_s else 'None'}
  Kill Z: {', '.join(act_k) if act_k else 'None'}
  Overlap:{', '.join(olap)  if olap  else 'None'}
  {chr(10).join(next_op) if next_op else ''}

━━━━━━━━━━━━━━━━━━━━
🔥 <b>HOT PAIRS RIGHT NOW</b>
{scan}

━━━━━━━━━━━━━━━━━━━━
📰 <b>TODAY'S NEWS</b>
{n_today}

📅 <b>WEEKLY EVENTS</b>
{n_week}

━━━━━━━━━━━━━━━━━━━━
{moon_n} | {moon_p}% | Full moon in {dtf} days

⚠️ <i>Max 1-2% risk per trade. Signal is confluence-based, not guarantee.</i>
""".strip()
    return msg

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print(f"🚀 Scalping Pro v5 | {ALERT_MODE} | {ist_str()}")

    if ALERT_MODE=="session":
        act_s,act_k,olap,best,next_op=get_sessions()
        h=utcnow().hour
        opens={7:"🇬🇧 London OPEN",12:"🇺🇸 NY OPEN",0:"🌏 Asia OPEN"}
        closes={16:"🇬🇧 London CLOSE",21:"🇺🇸 NY CLOSE",8:"🌏 Asia CLOSE"}
        name=opens.get(h) or closes.get(h) or "Session Update"
        msg=f"🔔 <b>{name}</b>\n📅 {ist_str()}\n\nActive: {', '.join(act_s) if act_s else 'None'}\nKZ: {', '.join(act_k) if act_k else 'None'}\nOverlap: {', '.join(olap) if olap else 'None'}\n{'🎯 BEST TIME TO TRADE!' if best else ''}"
        send_all(msg); return

    if ALERT_MODE=="news":
        send_all(f"📰 <b>NEWS ALERT</b>\n📅 {ist_str()}\n\n<b>Today:</b>\n{get_news()}\n\n<b>This Week:</b>\n{get_news(week=True)}")
        return

    d=get_data()
    if d is None:
        send_all(f"⚠️ Data error\n📅 {ist_str()}"); return

    # Always send full alert — har ghante
    msg=full_alert(d)
    send_all(msg)
    print("✅ Done")

if __name__=="__main__":
    main()
