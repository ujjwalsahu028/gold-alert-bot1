"""
XAU/USD 24/7 Trading Alert Bot
Telegram alerts: Pivots, Trends, Sessions, News, Signals, Moon Phase
Free APIs: yfinance, requests, ephem
"""

import os
import math
import datetime
import requests
import yfinance as yf
import ephem

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# WhatsApp via CallMeBot (free)
WA_PHONE  = os.environ.get("WA_PHONE",  "")   # e.g. 919876543210 (country code + number)
WA_APIKEY = os.environ.get("WA_APIKEY", "")   # from CallMeBot registration

SYMBOL = "GC=F"  # Gold Futures (XAU/USD proxy)
ALERT_MODE = os.environ.get("ALERT_MODE", "full")  # full | signal | session | news

# ─── TELEGRAM SENDER ──────────────────────────────────────────────────────────
def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print("✅ Telegram sent")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# ─── WHATSAPP SENDER (CallMeBot) ─────────────────────────────────────────────
def send_whatsapp(msg: str):
    if not WA_PHONE or not WA_APIKEY:
        print("⚠️  WhatsApp not configured — skipping")
        return
    # CallMeBot does not support HTML tags — strip them
    import re
    clean = re.sub(r"<[^>]+>", "", msg)
    url = "https://api.callmebot.com/whatsapp.php"
    params = {
        "phone":  WA_PHONE,
        "text":   clean,
        "apikey": WA_APIKEY,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if "Message Sent" in r.text or r.status_code == 200:
            print("✅ WhatsApp sent")
        else:
            print(f"⚠️  WhatsApp response: {r.text[:200]}")
    except Exception as e:
        print(f"❌ WhatsApp error: {e}")

# ─── PRICE & OHLC DATA ────────────────────────────────────────────────────────
def get_gold_data():
    ticker = yf.Ticker(SYMBOL)
    hist_1d  = ticker.history(period="5d",  interval="1d")
    hist_1w  = ticker.history(period="1mo", interval="1wk")
    hist_1m  = ticker.history(period="6mo", interval="1mo")
    hist_1h  = ticker.history(period="5d",  interval="1h")
    hist_15m = ticker.history(period="5d",  interval="15m")
    hist_5m  = ticker.history(period="2d",  interval="5m")

    if hist_1d.empty:
        return None

    today = hist_1d.iloc[-1]
    prev  = hist_1d.iloc[-2] if len(hist_1d) > 1 else today

    data = {
        "price":     round(float(today["Close"]), 2),
        "day_high":  round(float(today["High"]),  2),
        "day_low":   round(float(today["Low"]),   2),
        "day_open":  round(float(today["Open"]),  2),
        "prev_high": round(float(prev["High"]),   2),
        "prev_low":  round(float(prev["Low"]),    2),
        "prev_close":round(float(prev["Close"]),  2),
        "week_high": round(float(hist_1w["High"].max()),  2) if not hist_1w.empty else 0,
        "week_low":  round(float(hist_1w["Low"].min()),   2) if not hist_1w.empty else 0,
        "month_high":round(float(hist_1m["High"].max()),  2) if not hist_1m.empty else 0,
        "month_low": round(float(hist_1m["Low"].min()),   2) if not hist_1m.empty else 0,
        "hist_1h":   hist_1h,
        "hist_15m":  hist_15m,
        "hist_5m":   hist_5m,
        "hist_1d":   hist_1d,
    }
    return data

# ─── PIVOT POINTS ─────────────────────────────────────────────────────────────
def calc_pivots(high, low, close):
    pp = round((high + low + close) / 3, 2)
    r1 = round(2 * pp - low,  2)
    r2 = round(pp + (high - low), 2)
    r3 = round(high + 2 * (pp - low), 2)
    s1 = round(2 * pp - high, 2)
    s2 = round(pp - (high - low), 2)
    s3 = round(low - 2 * (high - pp), 2)
    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3,
            "S1": s1, "S2": s2, "S3": s3}

# ─── EMA TREND ────────────────────────────────────────────────────────────────
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean().iloc[-1]

def get_trend(df, label):
    if df is None or len(df) < 20:
        return label, "⚪ No data"
    close = df["Close"]
    e20 = ema(close, 20)
    e50 = ema(close, 50) if len(close) >= 50 else e20
    price = float(close.iloc[-1])
    if price > e20 and e20 > e50:
        return label, "🟢 Bullish"
    elif price < e20 and e20 < e50:
        return label, "🔴 Bearish"
    else:
        return label, "🟡 Sideways"

def get_all_trends(data):
    hist = data["hist_1h"]
    trends = []
    tfs = [
        ("1m",  None),
        ("5m",  data["hist_5m"]),
        ("15m", data["hist_15m"]),
        ("30m", None),
        ("1H",  data["hist_1h"]),
        ("4H",  None),
        ("1D",  data["hist_1d"]),
    ]
    for label, df in tfs:
        if df is not None and len(df) >= 5:
            _, trend = get_trend(df, label)
        else:
            price = data["price"]
            prev  = data["prev_close"]
            trend = "🟢 Bullish" if price > prev else "🔴 Bearish"
        trends.append(f"  {label:>4}: {trend}")
    return "\n".join(trends)

# ─── RSI ──────────────────────────────────────────────────────────────────────
def calc_rsi(df, period=14):
    if df is None or len(df) < period + 1:
        return 50.0
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    rsi   = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)

# ─── BUY/SELL SIGNAL ──────────────────────────────────────────────────────────
def get_signal(data, pivots):
    price  = data["price"]
    rsi    = calc_rsi(data["hist_1h"])
    ph, pl = data["prev_high"], data["prev_low"]
    pp     = pivots["PP"]
    r1, s1 = pivots["R1"], pivots["S1"]

    score = 0
    if price > pp:      score += 1
    if price > ph:      score += 1
    if rsi > 50:        score += 1
    if price > data["day_open"]: score += 1
    if rsi < 30:        score -= 2
    if price < pl:      score -= 2

    if score >= 3:
        direction = "🟢 BUY"
        entry = round(price - 2, 2)
        sl    = round(s1 - 5,    2)
        tp    = round(r1 + 5,    2)
    elif score <= -1:
        direction = "🔴 SELL"
        entry = round(price + 2, 2)
        sl    = round(r1 + 5,    2)
        tp    = round(s1 - 5,    2)
    else:
        direction = "⚪ NEUTRAL"
        entry = price
        sl    = round(s1, 2)
        tp    = round(r1, 2)

    risk   = round(abs(entry - sl),   2)
    reward = round(abs(tp   - entry), 2)
    rr     = round(reward / risk, 2) if risk > 0 else 0

    return {
        "direction": direction,
        "entry":     entry,
        "sl":        sl,
        "tp":        tp,
        "rr":        rr,
        "rsi":       rsi,
        "score":     score,
    }

# ─── SESSION & KILL ZONES ─────────────────────────────────────────────────────
def get_session_info():
    utc_h = datetime.datetime.utcnow().hour + datetime.datetime.utcnow().minute / 60
    sessions = {
        "Asia":    (0,  8),
        "London":  (7,  16),
        "NY":      (12, 21),
    }
    kill_zones = {
        "Asia KZ":   (0,  4),
        "London KZ": (6,  9),
        "NY KZ":     (12, 15),
        "LC KZ":     (15, 16),
    }
    active_sessions  = [k for k, (s, e) in sessions.items()   if s <= utc_h < e]
    active_kz        = [k for k, (s, e) in kill_zones.items() if s <= utc_h < e]
    overlap = []
    if 7 <= utc_h < 8:  overlap.append("Asia/London")
    if 12 <= utc_h < 16: overlap.append("London/NY")
    return active_sessions, active_kz, overlap, round(utc_h, 2)

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

# ─── FOREX FACTORY NEWS ───────────────────────────────────────────────────────
def get_news_calendar():
    """Fetch high-impact USD news from ForexFactory RSS"""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, timeout=10)
        data = r.json()
        today = datetime.date.today().strftime("%Y-%m-%d")
        high_impact = [
            e for e in data
            if e.get("impact") in ("High", "Medium")
            and e.get("currency") == "USD"
            and e.get("date", "")[:10] == today
        ]
        if not high_impact:
            return "No high-impact USD news today."
        lines = []
        for e in high_impact[:6]:
            t = e.get("date", "")[-8:-3] or "?"
            lines.append(f"  ⚡ {t} UTC — {e['title']} ({e['impact']})")
        return "\n".join(lines)
    except Exception as ex:
        return f"  News fetch error: {ex}"

# ─── FULL ALERT MESSAGE ───────────────────────────────────────────────────────
def build_full_alert(data):
    price    = data["price"]
    chg      = round(price - data["prev_close"], 2)
    chg_pct  = round(chg / data["prev_close"] * 100, 2)
    arrow    = "▲" if chg >= 0 else "▼"

    pivots   = calc_pivots(data["prev_high"], data["prev_low"], data["prev_close"])
    signal   = get_signal(data, pivots)
    trends   = get_all_trends(data)
    sessions, kzones, overlap, utc_h = get_session_info()
    moon_name, moon_pct = get_moon_phase()
    news     = get_news_calendar()

    now_str  = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    msg = f"""
🏅 <b>XAU/USD ALERT</b> — {now_str}

💰 <b>Price:</b> ${price:,.2f}  {arrow} {abs(chg)} ({abs(chg_pct)}%)

📊 <b>KEY LEVELS</b>
  Day  H: ${data['day_high']:,.2f}  |  L: ${data['day_low']:,.2f}
  Prev H: ${data['prev_high']:,.2f}  |  L: ${data['prev_low']:,.2f}
  Week H: ${data['week_high']:,.2f}  |  L: ${data['week_low']:,.2f}
  Month H: ${data['month_high']:,.2f}  |  L: ${data['month_low']:,.2f}

📐 <b>PIVOT POINTS</b>
  R3: ${pivots['R3']:,.2f}  R2: ${pivots['R2']:,.2f}  R1: ${pivots['R1']:,.2f}
  PP: ${pivots['PP']:,.2f}
  S1: ${pivots['S1']:,.2f}  S2: ${pivots['S2']:,.2f}  S3: ${pivots['S3']:,.2f}

📈 <b>MULTI-TF TREND</b>
{trends}

🎯 <b>SIGNAL</b>
  Direction : {signal['direction']}
  Entry     : ${signal['entry']:,.2f}
  Stop Loss : ${signal['sl']:,.2f}
  Take Profit: ${signal['tp']:,.2f}
  Risk:Reward: 1 : {signal['rr']}
  RSI (1H)  : {signal['rsi']}

🌐 <b>SESSIONS</b>
  Active: {', '.join(active_sessions) if sessions else 'None'}
  Kill Zones: {', '.join(kzones) if kzones else 'None active'}
  Overlap: {'⚡ ' + ', '.join(overlap) if overlap else 'None'}

📰 <b>TODAY'S HIGH-IMPACT NEWS</b>
{news}

{moon_name}  Moon: {moon_pct}% illuminated

<i>Data: yfinance | Signals: EMA + RSI + Pivot logic</i>
""".strip()
    return msg

# ─── SIGNAL-ONLY ALERT ────────────────────────────────────────────────────────
def build_signal_alert(data):
    pivots = calc_pivots(data["prev_high"], data["prev_low"], data["prev_close"])
    signal = get_signal(data, pivots)
    sessions, kzones, overlap, _ = get_session_info()
    now_str = datetime.datetime.utcnow().strftime("%H:%M UTC")

    msg = f"""
⚡ <b>SIGNAL ALERT</b> — {now_str}
💰 XAU/USD: ${data['price']:,.2f}

{signal['direction']}
  Entry: ${signal['entry']:,.2f}
  SL   : ${signal['sl']:,.2f}
  TP   : ${signal['tp']:,.2f}
  R:R  : 1 : {signal['rr']}
  RSI  : {signal['rsi']}

Sessions: {', '.join(sessions) if sessions else 'None'}
{('⚡ OVERLAP: ' + ', '.join(overlap)) if overlap else ''}
""".strip()
    return msg

# ─── SESSION OPEN/CLOSE ALERT ─────────────────────────────────────────────────
def build_session_alert():
    sessions, kzones, overlap, utc_h = get_session_info()
    now_str = datetime.datetime.utcnow().strftime("%H:%M UTC")

    session_opens = {7: "London OPEN 🇬🇧", 12: "New York OPEN 🇺🇸", 0: "Asia OPEN 🌏"}
    session_closes= {16: "London CLOSE 🇬🇧", 21: "New York CLOSE 🇺🇸", 8: "Asia CLOSE 🌏"}

    h = datetime.datetime.utcnow().hour
    alert_name = session_opens.get(h) or session_closes.get(h) or f"Session Check"

    msg = f"""
🔔 <b>{alert_name}</b> — {now_str}

Active Sessions : {', '.join(sessions) if sessions else 'None'}
Kill Zones      : {', '.join(kzones)   if kzones   else 'None'}
Overlap         : {'⚡ ' + ', '.join(overlap) if overlap else 'None'}
""".strip()
    return msg

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print(f"🚀 XAU/USD Bot running — mode: {ALERT_MODE}")

    if ALERT_MODE == "session":
        msg = build_session_alert()
        if TELEGRAM_TOKEN: send_telegram(msg)
        send_whatsapp(msg)
        return

    data = get_gold_data()
    if data is None:
        err = "⚠️ XAU/USD data fetch failed. Markets may be closed."
        if TELEGRAM_TOKEN: send_telegram(err)
        send_whatsapp(err)
        return

    if ALERT_MODE == "signal":
        msg = build_signal_alert(data)
    else:
        msg = build_full_alert(data)

    if TELEGRAM_TOKEN: send_telegram(msg)
    send_whatsapp(msg)
    print(msg)

if __name__ == "__main__":
    main()
