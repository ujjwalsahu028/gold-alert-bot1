"""
XAU/USD MEGA ALERT BOT v3
Covers: Price, H/L levels, Pivots, Multi-TF Trends, Signal, Sessions,
        Kill Zones, Overlap, News Calendar, Moon Phase, Market Briefing,
        Sentiment, Institutional Interest, Risk:Reward — IST timing
"""
import os, datetime, requests, ephem
import yfinance as yf

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",  "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","")
WA_PHONE         = os.environ.get("WA_PHONE",  "")
WA_APIKEY        = os.environ.get("WA_APIKEY", "")
SYMBOL           = "GC=F"
ALERT_MODE       = os.environ.get("ALERT_MODE", "full")
IST              = datetime.timedelta(hours=5, minutes=30)

# ── TIME HELPERS ──────────────────────────────────────────────────────────────
def utcnow():  return datetime.datetime.utcnow()
def istnow():  return utcnow() + IST
def ist_str(): return istnow().strftime("%d %b %Y  %I:%M %p IST")
def utc_h():
    n = utcnow(); return n.hour + n.minute/60

# ── SENDERS ───────────────────────────────────────────────────────────────────
def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,
                  "parse_mode":"HTML","disable_web_page_preview":True},
            timeout=15)
        print("✅ TG sent" if r.status_code==200 else f"⚠️ TG {r.text[:80]}")
    except Exception as e: print(f"❌ TG: {e}")

def send_whatsapp(msg):
    if not WA_PHONE or not WA_APIKEY: return
    import re; clean=re.sub(r"<[^>]+>","",msg)
    try:
        r=requests.get("https://api.callmebot.com/whatsapp.php",
            params={"phone":WA_PHONE,"text":clean,"apikey":WA_APIKEY},timeout=15)
        print("✅ WA sent" if r.status_code==200 else f"⚠️ WA {r.text[:80]}")
    except Exception as e: print(f"❌ WA: {e}")

def send_all(msg): send_telegram(msg); send_whatsapp(msg)

# ── PRICE DATA ────────────────────────────────────────────────────────────────
def get_data():
    t   = yf.Ticker(SYMBOL)
    d1  = t.history(period="5d",  interval="1d")
    w1  = t.history(period="1mo", interval="1wk")
    mo1 = t.history(period="6mo", interval="1mo")
    h1  = t.history(period="5d",  interval="1h")
    h2  = t.history(period="7d",  interval="2h")
    h4  = t.history(period="10d", interval="4h")
    m15 = t.history(period="5d",  interval="15m")
    m5  = t.history(period="2d",  interval="5m")
    if d1.empty: return None
    tod  = d1.iloc[-1]
    prev = d1.iloc[-2] if len(d1)>1 else tod
    return dict(
        price      = round(float(tod["Close"]),2),
        day_h      = round(float(tod["High"]),2),
        day_l      = round(float(tod["Low"]),2),
        day_o      = round(float(tod["Open"]),2),
        prev_h     = round(float(prev["High"]),2),
        prev_l     = round(float(prev["Low"]),2),
        prev_c     = round(float(prev["Close"]),2),
        week_h     = round(float(w1["High"].max()),2)  if not w1.empty  else 0,
        week_l     = round(float(w1["Low"].min()),2)   if not w1.empty  else 0,
        month_h    = round(float(mo1["High"].max()),2) if not mo1.empty else 0,
        month_l    = round(float(mo1["Low"].min()),2)  if not mo1.empty else 0,
        d1=d1, w1=w1, h1=h1, h2=h2, h4=h4, m15=m15, m5=m5,
    )

# ── PIVOTS ────────────────────────────────────────────────────────────────────
def pivots(h,l,c):
    pp=round((h+l+c)/3,2)
    return dict(PP=pp,
        R1=round(2*pp-l,2), R2=round(pp+(h-l),2), R3=round(h+2*(pp-l),2),
        S1=round(2*pp-h,2), S2=round(pp-(h-l),2), S3=round(l-2*(h-pp),2))

# ── EMA TREND ────────────────────────────────────────────────────────────────
def ema(s,p): return s.ewm(span=p,adjust=False).mean().iloc[-1]

def tf_trend(df, price, prev_c):
    if df is None or len(df)<20:
        return "🟢 Bull" if price>prev_c else "🔴 Bear"
    c=df["Close"]; e20=ema(c,20); e50=ema(c,50) if len(c)>=50 else e20
    p=float(c.iloc[-1])
    if p>e20 and e20>e50: return "🟢 Bull"
    if p<e20 and e20<e50: return "🔴 Bear"
    return "🟡 Side"

def all_trends(d):
    pc,pr = d["prev_c"], d["price"]
    rows=[
        ("1m ",  None),
        ("5m ",  d["m5"]),
        ("15m",  d["m15"]),
        ("30m",  None),
        ("1H ",  d["h1"]),
        ("2H ",  d["h2"]),
        ("4H ",  d["h4"]),
        ("12H",  None),
        ("24H",  d["d1"]),
    ]
    lines=[]
    for label,df in rows:
        lines.append(f"  {label}: {tf_trend(df,pr,pc)}")
    # Overall trend = majority
    bulls = sum(1 for _,df in rows if tf_trend(df,pr,pc)=="🟢 Bull")
    bears = sum(1 for _,df in rows if tf_trend(df,pr,pc)=="🔴 Bear")
    overall = "🟢 BULLISH" if bulls>bears else ("🔴 BEARISH" if bears>bulls else "🟡 NEUTRAL")
    return "\n".join(lines), overall

# ── RSI ───────────────────────────────────────────────────────────────────────
def rsi(df,p=14):
    if df is None or len(df)<p+1: return 50.0
    d=df["Close"].diff()
    g=d.clip(lower=0).rolling(p).mean()
    l=(-d.clip(upper=0)).rolling(p).mean()
    return round(float((100-100/(1+g/l)).iloc[-1]),1)

# ── SIGNAL ────────────────────────────────────────────────────────────────────
def signal(d, pvt):
    price=d["price"]; r=rsi(d["h1"])
    pp,r1,s1=pvt["PP"],pvt["R1"],pvt["S1"]
    sc=0
    if price>pp:       sc+=1
    if price>d["prev_h"]: sc+=1
    if r>50:           sc+=1
    if price>d["day_o"]: sc+=1
    if r<30:           sc-=2
    if price<d["prev_l"]: sc-=2
    if sc>=3:   dirn,ent="🟢 BUY",  round(price-2,2); sl,tp=round(s1-5,2),round(r1+5,2)
    elif sc<=-1:dirn,ent="🔴 SELL", round(price+2,2); sl,tp=round(r1+5,2),round(s1-5,2)
    else:        dirn,ent="⚪ NEUTRAL",price;          sl,tp=round(s1,2),round(r1,2)
    risk=round(abs(ent-sl),2); rew=round(abs(tp-ent),2)
    return dict(dirn=dirn,ent=ent,sl=sl,tp=tp,
                rr=round(rew/risk,2) if risk>0 else 0,rsi_val=r,score=sc)

# ── SESSIONS & KILL ZONES ─────────────────────────────────────────────────────
def sessions():
    h=utc_h()
    s_map = {"Asia":(0,8),"London":(7,16),"New York":(12,21)}
    kz_map= {"Asia KZ":(0,4),"London KZ":(6,9),"NY KZ":(12,15),"LC KZ":(15,16)}
    act_s = [k for k,(a,b) in s_map.items()  if a<=h<b]
    act_k = [k for k,(a,b) in kz_map.items() if a<=h<b]
    olap  = []
    if 7<=h<8:   olap.append("Asia / London ⚡")
    if 12<=h<16: olap.append("London / NY ⚡")
    # Next session open (IST)
    next_s=[]
    for name,(a,b) in s_map.items():
        if h<a:
            diff=a-h
            open_ist=(utcnow()+IST+datetime.timedelta(hours=diff)).strftime("%I:%M %p")
            next_s.append(f"{name} opens at {open_ist} IST")
    return act_s, act_k, olap, next_s

# ── MOON PHASE ────────────────────────────────────────────────────────────────
def moon():
    m=ephem.Moon(); m.compute(datetime.date.today()); ph=float(m.phase)
    name=("🌑 New Moon" if ph<6 else "🌒 Waxing Crescent" if ph<25
          else "🌓 First Quarter" if ph<35 else "🌔 Waxing Gibbous" if ph<60
          else "🌕 Full Moon" if ph<66 else "🌖 Waning Gibbous" if ph<75
          else "🌗 Last Quarter" if ph<85 else "🌘 Waning Crescent")
    return name, round(ph,1)

# ── NEWS CALENDAR ─────────────────────────────────────────────────────────────
def news_today():
    try:
        data=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=10).json()
        today=datetime.date.today().strftime("%Y-%m-%d")
        items=[e for e in data if e.get("impact") in ("High","Medium")
               and e.get("currency")=="USD" and e.get("date","")[:10]==today]
        if not items: return "  Aaj koi major USD news nahi."
        out=[]
        for e in items[:8]:
            raw=e.get("date","")
            try:
                hh,mm=int(raw[11:13]),int(raw[14:16])
                ist_t=(datetime.datetime(2000,1,1,hh,mm)+IST).strftime("%I:%M %p")
            except: ist_t="?"
            imp="🔴 HIGH" if e["impact"]=="High" else "🟡 MED"
            fc=e.get("forecast","") or "-"; prev=e.get("previous","") or "-"
            out.append(f"  {imp} {ist_t} IST\n    📌 {e['title']}\n    Forecast:{fc} | Prev:{prev}")
        return "\n".join(out)
    except Exception as ex: return f"  Error: {ex}"

def news_week():
    try:
        data=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=10).json()
        items=[e for e in data if e.get("impact") in ("High","Medium")
               and e.get("currency")=="USD"]
        if not items: return "  Is hafte koi major news nahi."
        out=[]
        for e in items[:12]:
            raw=e.get("date","")
            try:
                day=datetime.datetime.strptime(raw[:10],"%Y-%m-%d").strftime("%a %d %b")
                hh,mm=int(raw[11:13]),int(raw[14:16])
                ist_t=(datetime.datetime(2000,1,1,hh,mm)+IST).strftime("%I:%M %p")
            except: day="?"; ist_t="?"
            imp="🔴" if e["impact"]=="High" else "🟡"
            out.append(f"  {imp} {day} {ist_t} — {e['title']}")
        return "\n".join(out)
    except Exception as ex: return f"  Error: {ex}"

# ── SENTIMENT (RSI proxy) ─────────────────────────────────────────────────────
def sentiment(d):
    r=rsi(d["h1"])
    if r>65:   return "😤 Greed (Overbought)", r
    if r>55:   return "📈 Bullish Sentiment", r
    if r<35:   return "😨 Fear (Oversold)", r
    if r<45:   return "📉 Bearish Sentiment", r
    return "😐 Neutral", r

# ── INSTITUTIONAL / BIG MONEY (COT proxy via price structure) ─────────────────
def institutional(d, pvt, sig):
    price=d["price"]; r1,s1=pvt["R1"],pvt["S1"]; pp=pvt["PP"]
    # Price above PP + prev high = institutional buy zone
    if price>d["prev_h"] and price>pp:
        return "🏦 BIG MONEY: Long Bias", "📈 Smart money above prev high — accumulation zone"
    if price<d["prev_l"] and price<pp:
        return "🏦 BIG MONEY: Short Bias", "📉 Smart money below prev low — distribution zone"
    if abs(price-pp)/price < 0.002:
        return "🏦 BIG MONEY: Neutral", "⚖️ Price at pivot — consolidation, wait for breakout"
    return "🏦 BIG MONEY: Watch", "🔍 No clear institutional bias — use caution"

# ── MARKET BRIEFING ───────────────────────────────────────────────────────────
def briefing(d, pvt, sig, overall_trend, sent_txt):
    price=d["price"]; pp=pvt["PP"]; r1=pvt["R1"]; s1=pvt["S1"]
    trend_word="bullish" if "Bull" in overall_trend else ("bearish" if "Bear" in overall_trend else "sideways")
    pos="above PP" if price>pp else "below PP"
    near_r=abs(price-r1)<15; near_s=abs(price-s1)<15
    level_note=f"Price near R1 (${r1:,.2f}) — watch breakout" if near_r else (
               f"Price near S1 (${s1:,.2f}) — watch support" if near_s else
               f"Price between S1-R1 range")
    return (f"Gold is <b>{trend_word}</b> overall, trading {pos} at ${price:,.2f}. "
            f"{level_note}. Sentiment: {sent_txt}. "
            f"Signal: {sig['dirn']} with R:R {sig['rr']}.")

# ── FULL ALERT ────────────────────────────────────────────────────────────────
def full_alert(d):
    chg=round(d["price"]-d["prev_c"],2)
    pct=round(chg/d["prev_c"]*100,2) if d["prev_c"] else 0
    arr="▲" if chg>=0 else "▼"
    pvt   = pivots(d["prev_h"],d["prev_l"],d["prev_c"])
    sig   = signal(d,pvt)
    trend_block, overall = all_trends(d)
    act_s,act_k,olap,next_s = sessions()
    moon_name,moon_pct = moon()
    sent_txt,rsi_val = sentiment(d)
    inst_title,inst_note = institutional(d,pvt,sig)
    brief = briefing(d,pvt,sig,overall,sent_txt)
    n_today = news_today()
    n_week  = news_week()

    msg=f"""
🏅 <b>XAU/USD MEGA ALERT — v3</b>
📅 {ist_str()}

━━━━━━━━━━━━━━━━━━━━
💰 <b>PRICE</b>: ${d['price']:,.2f}  {arr} {abs(chg)} ({abs(pct)}%)
━━━━━━━━━━━━━━━━━━━━

📋 <b>MARKET BRIEFING</b>
{brief}

━━━━━━━━━━━━━━━━━━━━
📊 <b>KEY LEVELS</b>
  Day   H: ${d['day_h']:,.2f}  L: ${d['day_l']:,.2f}
  Prev  H: ${d['prev_h']:,.2f}  L: ${d['prev_l']:,.2f}
  Week  H: ${d['week_h']:,.2f}  L: ${d['week_l']:,.2f}
  Month H: ${d['month_h']:,.2f}  L: ${d['month_l']:,.2f}

━━━━━━━━━━━━━━━━━━━━
📐 <b>PIVOT POINTS</b>
  🟢 R3: ${pvt['R3']:,.2f}
  🟢 R2: ${pvt['R2']:,.2f}
  🟢 R1: ${pvt['R1']:,.2f}
  🔵 PP: ${pvt['PP']:,.2f}
  🔴 S1: ${pvt['S1']:,.2f}
  🔴 S2: ${pvt['S2']:,.2f}
  🔴 S3: ${pvt['S3']:,.2f}

━━━━━━━━━━━━━━━━━━━━
📈 <b>MULTI-TF TREND</b>
{trend_block}
  ──────────────
  Overall : {overall}

━━━━━━━━━━━━━━━━━━━━
🎯 <b>SIGNAL</b>
  Direction  : {sig['dirn']}
  Entry      : ${sig['ent']:,.2f}
  Stop Loss  : ${sig['sl']:,.2f}
  Take Profit: ${sig['tp']:,.2f}
  Risk:Reward: 1 : {sig['rr']}
  RSI (1H)   : {rsi_val}
  Score      : {sig['score']}/4

━━━━━━━━━━━━━━━━━━━━
{inst_title}
  {inst_note}

━━━━━━━━━━━━━━━━━━━━
😊 <b>MARKET SENTIMENT</b>: {sent_txt}

━━━━━━━━━━━━━━━━━━━━
🌐 <b>SESSIONS</b>
  Active    : {', '.join(act_s) if act_s else 'None'}
  Kill Zones: {', '.join(act_k) if act_k else 'None'}
  Overlap   : {', '.join(olap)  if olap  else 'None'}
{('  ' + chr(10)+'  '.join(next_s)) if next_s else ''}

━━━━━━━━━━━━━━━━━━━━
📰 <b>TODAY'S NEWS (IST)</b>
{n_today}

━━━━━━━━━━━━━━━━━━━━
📅 <b>WEEKLY CALENDAR</b>
{n_week}

━━━━━━━━━━━━━━━━━━━━
{moon_name}  {moon_pct}% illuminated

<i>XAU/USD Bot v3 | yfinance + ForexFactory | IST</i>
""".strip()
    return msg

# ── SIGNAL ALERT (short) ──────────────────────────────────────────────────────
def signal_alert(d):
    pvt=pivots(d["prev_h"],d["prev_l"],d["prev_c"])
    sig=signal(d,pvt); act_s,act_k,olap,_=sessions()
    return f"""
⚡ <b>SIGNAL ALERT</b>
📅 {ist_str()}
💰 XAU/USD: ${d['price']:,.2f}

{sig['dirn']}
  Entry : ${sig['ent']:,.2f}
  SL    : ${sig['sl']:,.2f}
  TP    : ${sig['tp']:,.2f}
  R:R   : 1 : {sig['rr']}
  RSI   : {sig['rsi_val']}

Sessions : {', '.join(act_s) if act_s else 'None'}
KillZones: {', '.join(act_k) if act_k else 'None'}
Overlap  : {', '.join(olap)  if olap  else 'None'}
""".strip()

# ── NEWS ONLY ALERT ───────────────────────────────────────────────────────────
def news_alert():
    return f"""
📰 <b>NEWS ALERT — TODAY (IST)</b>
📅 {ist_str()}

<b>Aaj ke high-impact events:</b>
{news_today()}

━━━━━━━━━━━━━━━━━━━━
📅 <b>Is hafte ke baaki events:</b>
{news_week()}
""".strip()

# ── SESSION ALERT ─────────────────────────────────────────────────────────────
def session_alert():
    h=utcnow().hour
    opens ={7:"🇬🇧 London OPEN",12:"🇺🇸 New York OPEN",0:"🌏 Asia OPEN"}
    closes={16:"🇬🇧 London CLOSE",21:"🇺🇸 NY CLOSE",8:"🌏 Asia CLOSE"}
    name=opens.get(h) or closes.get(h) or "Session Update"
    act_s,act_k,olap,next_s=sessions()
    return f"""
🔔 <b>{name}</b>
📅 {ist_str()}

Active    : {', '.join(act_s) if act_s else 'None'}
Kill Zones: {', '.join(act_k) if act_k else 'None'}
Overlap   : {', '.join(olap)  if olap  else 'None'}
{chr(10).join(next_s) if next_s else ''}
""".strip()

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print(f"🚀 XAU/USD Bot v3 | {ALERT_MODE} | {ist_str()}")
    if ALERT_MODE=="session":
        send_all(session_alert()); return
    if ALERT_MODE=="news":
        send_all(news_alert()); return
    d=get_data()
    if d is None:
        send_all(f"⚠️ Data fetch failed.\n📅 {ist_str()}\nMarket band ho sakta hai."); return
    msg = signal_alert(d) if ALERT_MODE=="signal" else full_alert(d)
    send_all(msg); print(msg)

if __name__=="__main__":
    main()
