"""
XAU/USD 24/7 Trading Alert Bot — v2 (IST Timing + Full Details)
Telegram alerts: Pivots, Trends, Sessions, News, Signals, Moon Phase
Free APIs: yfinance, requests, ephem
"""

import os
import datetime
import requests
import yfinance as yf
import ephem

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN",  "")
TELEGRAM_CHAT_ID= os.environ.get("TELEGRAM_CHAT_ID","")
WA_PHONE        = os.environ.get("WA_PHONE",  "")
WA_APIKEY       = os.environ.get("WA_APIKEY", "")
SYMBOL          = "GC=F"
ALERT_MODE      = os.environ.get("ALERT_MODE", "full")
IST_OFFSET      = datetime.timedelta(hours=5, minutes=30)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def now_ist():
    return datetime.datetime.utcnow() + IST_OFFSET

def now_ist_str():
    return now_ist().strftime("%d %b %Y  %I:%M %p IST")

def now_utc_h():
    n = datetime.datetime.utcnow()
    return n.hour + n.minute / 60

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_telegram(msg: str):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        r.raise_for_status()
        print("✅ Telegram sent")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# ─── WHATSAPP ─────────────────────────────────────────────────────────────────
def send_whatsapp(msg: str):
    if not WA_PHONE or not WA_APIKEY:
        return
    import re
    clean = re.sub(r"<[^>]+>", "", msg)
    try:
        r = requests.get("https://api.callmebot.com/whatsapp.php",
                         params={"phone": WA_PHONE, "text": clean, "apikey": WA_APIKEY},
                         timeout=15)
        print("✅ WhatsApp sent" if r.status_code == 200 else f"⚠️ WA: {r.text[:100]}")
    except Exception as e:
        print(f"❌ WhatsApp error: {e}")

# ─── PRICE DATA ───────────────────────────────────────────────────────────────
def get_gold_data():
    ticker  = yf.Ticker(SYMBOL)
    h1d     = ticker.history(period="5d",  interval="1d")
    h1w     = ticker.history(period="1mo", interval="1wk")
    h1mo    = ticker.history(period="6mo", interval="1mo")
    h1h     = ticker.history(period="5d",  interval="1h")
    h15m    = ticker.history(period="5d",  interval="15m")
    h5m     = ticker.history(period="2d",  interval="5m")
    if h1d.empty:
        return None
    today = h1d.iloc[-1]
    prev  = h1d.iloc[-2] if len(h1d) > 1 else today
    return {
        "price":      round(float(today["Close"]), 2),
        "day_high":   round(float(today["High"]),  2),
        "day_low":    round(float(today["Low"]),   2),
        "day_open":   round(float(today["Open"]),  2),
        "prev_high":  round(float(prev["High"]),   2),
        "prev_low":   round(float(prev["Low"]),    2),
        "prev_close": round(float(prev["Close"]),  2),
        "week_high":  round(float(h1w["High"].max()),  2) if not h1w.empty  else 0,
        "week_low":   round(float(h1w["Low"].min()),   2) if not h1w.empty  else 0,
        "month_high": round(float(h1mo["High"].max()), 2) if not h1mo.empty else 0,
        "month_low":  round(float(h1mo["Low"].min()),  2) if not h1mo.empty else 0,
        "h1h": h1h, "h15m": h15m, "h5m": h5m, "h1d": h1d,
    }

# ─── PIVOTS ───────────────────────────────────────────────────────────────────
def calc_pivots(high, low, close):
    pp = round((high + low + close) / 3, 2)
    return {
        "PP": pp,
        "R1": round(2*pp - low,       2),
        "R2": round(pp + (high-low),  2),
        "R3": round(high + 2*(pp-low),2),
        "S1": round(2*pp - high,      2),
        "S2": round(pp - (high-low),  2),
        "S3": round(low - 2*(high-pp),2),
    }

# ─── EMA & TREND ──────────────────────────────────────────────────────────────
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean().iloc[-1]

def trend_from_df(df, price, prev_close):
    if df is None or len(df) < 20:
        return "🟢 Bullish" if price > prev_close else "🔴 Bearish"
    close = df["Close"]
    e20 = ema(close, 20)
    e50 = ema(close, 50) if len(close) >= 50 else e20
    p   = float(close.iloc[-1])
    if p > e20 and e20 > e50:   return "🟢 Bullish"
    elif p < e20 and e20 < e50: return "🔴 Bearish"
    else:                        return "🟡 Sideways"

def get_all_trends(d):
    pc = d["prev_close"]
    pr = d["price"]
    tfs = [
        ("1m",  None),
        ("5m",  d["h5m"]),
        ("15m", d["h15m"]),
        ("30m", None),
        ("1H",  d["h1h"]),
        ("4H",  None),
        ("1D",  d["h1d"]),
    ]
    lines = []
    for label, df in tfs:
        t = trend_from_df(df, pr, pc)
        lines.append(f"  {label:>4}: {t}")
    return "\n".join(lines)

# ─── RSI ──────────────────────────────────────────────────────────────────────
def calc_rsi(df, period=14):
    if df is None or len(df) < period+1:
        return 50.0
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return round(float((100 - 100/(1+rs)).iloc[-1]), 1)

# ─── SIGNAL ───────────────────────────────────────────────────────────────────
def get_signal(d, pivots):
    price = d["price"]
    rsi   = calc_rsi(d["h1h"])
    pp, r1, s1 = pivots["PP"], pivots["R1"], pivots["S1"]
    score = 0
    if price > pp:          score += 1
    if price > d["prev_high"]: score += 1
    if rsi > 50:            score += 1
    if price > d["day_open"]: score += 1
    if rsi < 30:            score -= 2
    if price < d["prev_low"]: score -= 2
    if score >= 3:
        direction, entry = "🟢 BUY",  round(price-2, 2)
        sl, tp = round(s1-5, 2), round(r1+5, 2)
    elif score <= -1:
        direction, entry = "🔴 SELL", round(price+2, 2)
        sl, tp = round(r1+5, 2), round(s1-5, 2)
    else:
        direction, entry = "⚪ NEUTRAL", price
        sl, tp = round(s1, 2), round(r1, 2)
    risk   = round(abs(entry-sl), 2)
    reward = round(abs(tp-entry), 2)
    return {"direction": direction, "entry": entry, "sl": sl, "tp": tp,
            "rr": round(reward/risk, 2) if risk > 0 else 0, "rsi": rsi}

# ─── SESSIONS & KILL ZONES ────────────────────────────────────────────────────
def get_session_info():
    h = now_utc_h()
    sessions   = {"Asia":(0,8), "London":(7,16), "NY":(12,21)}
    kill_zones = {"Asia KZ":(0,4), "London KZ":(6,9), "NY KZ":(12,15), "LC KZ":(15,16)}
    active_sess = [k for k,(s,e) in sessions.items()   if s <= h < e]
    active_kz   = [k for k,(s,e) in kill_zones.items() if s <= h < e]
    overlap = []
    if 7  <= h < 8:  overlap.append("Asia/London ⚡")
    if 12 <= h < 16: overlap.append("London/NY ⚡")
    return active_sess, active_kz, overlap

# ─── MOON PHASE ───────────────────────────────────────────────────────────────
def get_moon_phase():
    moon = ephem.Moon()
    moon.compute(datetime.date.today())
    phase = float(moon.phase)
    if phase < 6:    name = "🌑 New Moon"
    elif phase < 25: name = "🌒 Waxing Crescent"
    elif phase < 35: name = "🌓 First Quarter"
    elif phase < 60: name = "🌔 Waxing Gibbous"
    elif phase < 66: name = "🌕 Full Moon"
    elif phase < 75: name = "🌖 Waning Gibbous"
    elif phase < 85: name = "🌗 Last Quarter"
    else:            name = "🌘 Waning Crescent"
    return name, round(phase, 1)

# ─── NEWS CALENDAR ────────────────────────────────────────────────────────────
def get_news_calendar():
    try:
        r    = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10)
        data = r.json()
        today = datetime.date.today().strftime("%Y-%m-%d")
        items = [e for e in data
                 if e.get("impact") in ("High","Medium")
                 and e.get("currency") == "USD"
                 and e.get("date","")[:10] == today]
        if not items:
            return "  Aaj koi high-impact USD news nahi hai."
        lines = []
        for e in items[:6]:
            utc_t = e.get("date","")[-8:-3] or "?"
            # Convert to IST
            try:
                hh, mm = int(utc_t[:2]), int(utc_t[3:])
                ist_dt = datetime.datetime(2000,1,1,hh,mm) + IST_OFFSET
                ist_t  = ist_dt.strftime("%I:%M %p")
            except:
                ist_t = utc_t + " UTC"
            imp = "🔴" if e['impact']=="High" else "🟡"
            lines.append(f"  {imp} {ist_t} IST — {e['title']}")
        return "\n".join(lines)
    except Exception as ex:
        return f"  News error: {ex}"

# ─── FULL ALERT ───────────────────────────────────────────────────────────────
def build_full_alert(data):
    price   = data["price"]
    chg     = round(price - data["prev_close"], 2)
    chg_pct = round(chg / data["prev_close"] * 100, 2) if data["prev_close"] else 0
    arrow   = "▲" if chg >= 0 else "▼"

    pivots              = calc_pivots(data["prev_high"], data["prev_low"], data["prev_close"])
    signal              = get_signal(data, pivots)
    trends              = get_all_trends(data)
    active_sess, active_kz, overlap = get_session_info()
    moon_name, moon_pct = get_moon_phase()
    news                = get_news_calendar()

    sess_str    = ", ".join(active_sess) if active_sess else "None"
    kz_str      = ", ".join(active_kz)   if active_kz   else "None"
    overlap_str = ", ".join(overlap)      if overlap     else "None"

    msg = f"""
🏅 <b>XAU/USD FULL ALERT</b>
📅 {now_ist_str()}

💰 <b>Price:</b> ${price:,.2f}  {arrow} {abs(chg)} ({abs(chg_pct)}%)

📊 <b>KEY LEVELS</b>
  Day   H: ${data['day_high']:,.2f}  |  L: ${data['day_low']:,.2f}
  Prev  H: ${data['prev_high']:,.2f}  |  L: ${data['prev_low']:,.2f}
  Week  H: ${data['week_high']:,.2f}  |  L: ${data['week_low']:,.2f}
  Month H: ${data['month_high']:,.2f}  |  L: ${data['month_low']:,.2f}

📐 <b>PIVOT POINTS</b>
  🟢 R3: ${pivots['R3']:,.2f}
  🟢 R2: ${pivots['R2']:,.2f}
  🟢 R1: ${pivots['R1']:,.2f}
  🔵 PP: ${pivots['PP']:,.2f}
  🔴 S1: ${pivots['S1']:,.2f}
  🔴 S2: ${pivots['S2']:,.2f}
  🔴 S3: ${pivots['S3']:,.2f}

📈 <b>MULTI-TF TREND</b>
{trends}

🎯 <b>SIGNAL</b>
  Direction  : {signal['direction']}
  Entry      : ${signal['entry']:,.2f}
  Stop Loss  : ${signal['sl']:,.2f}
  Take Profit: ${signal['tp']:,.2f}
  Risk:Reward: 1 : {signal['rr']}
  RSI (1H)   : {signal['rsi']}

🌐 <b>SESSIONS (UTC)</b>
  Active    : {sess_str}
  Kill Zones: {kz_str}
  Overlap   : {overlap_str}

📰 <b>TODAY'S NEWS (IST)</b>
{news}

{moon_name}  {moon_pct}% illuminated

<i>yfinance | EMA + RSI + Pivot | IST timing</i>
""".strip()
    return msg

# ─── SIGNAL ONLY ──────────────────────────────────────────────────────────────
def build_signal_alert(data):
    pivots = calc_pivots(data["prev_high"], data["prev_low"], data["prev_close"])
    signal = get_signal(data, pivots)
    active_sess, active_kz, overlap = get_session_info()
    sess_str    = ", ".join(active_sess) if active_sess else "None"
    overlap_str = ", ".join(overlap)     if overlap     else "None"

    msg = f"""
⚡ <b>SIGNAL ALERT</b>
📅 {now_ist_str()}
💰 XAU/USD: ${data['price']:,.2f}

{signal['direction']}
  Entry : ${signal['entry']:,.2f}
  SL    : ${signal['sl']:,.2f}
  TP    : ${signal['tp']:,.2f}
  R:R   : 1 : {signal['rr']}
  RSI   : {signal['rsi']}

Sessions: {sess_str}
Overlap : {overlap_str}
""".strip()
    return msg

# ─── SESSION ALERT ────────────────────────────────────────────────────────────
def build_session_alert():
    active_sess, active_kz, overlap = get_session_info()
    h = datetime.datetime.utcnow().hour
    opens  = {7:"London OPEN 🇬🇧", 12:"New York OPEN 🇺🇸", 0:"Asia OPEN 🌏"}
    closes = {16:"London CLOSE 🇬🇧", 21:"New York CLOSE 🇺🇸", 8:"Asia CLOSE 🌏"}
    name   = opens.get(h) or closes.get(h) or "Session Check"
    msg = f"""
🔔 <b>{name}</b>
📅 {now_ist_str()}

Active    : {', '.join(active_sess) if active_sess else 'None'}
Kill Zones: {', '.join(active_kz)  if active_kz  else 'None'}
Overlap   : {', '.join(overlap)    if overlap    else 'None'}
""".strip()
    return msg

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print(f"🚀 XAU/USD Bot v2 | Mode: {ALERT_MODE} | Time: {now_ist_str()}")

    if ALERT_MODE == "session":
        msg = build_session_alert()
        send_telegram(msg); send_whatsapp(msg)
        return

    data = get_gold_data()
    if data is None:
        err = f"⚠️ XAU/USD data fetch failed.\n📅 {now_ist_str()}\nMarket band ho sakta hai."
        send_telegram(err); send_whatsapp(err)
        return

    msg = build_signal_alert(data) if ALERT_MODE == "signal" else build_full_alert(data)
    send_telegram(msg); send_whatsapp(msg)
    print(msg)

if __name__ == "__main__":
    main()
