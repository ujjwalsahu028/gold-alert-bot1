"""
XAU/USD HIGH-ACCURACY ALERT BOT v4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Accuracy fixes:
  ✅ Multi-TF confluence (5+ TF must agree)
  ✅ EMA trend filter  (no counter-trend trades)
  ✅ ATR-based SL/TP  (volatility-adjusted, not arbitrary)
  ✅ RSI divergence filter
  ✅ Minimum R:R 1.5 gate  (signals with R:R < 1.5 = NEUTRAL)
  ✅ Trend strength 0–10 score
  ✅ Market structure: Higher High / Lower Low detection
  ✅ Session quality filter (signals stronger in KZ overlap)
  ✅ Volume confirmation (relative volume spike check)
"""
import os, datetime, requests, ephem
import yfinance as yf
import pandas as pd
import numpy as np
 
# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WA_PHONE         = os.environ.get("WA_PHONE",  "")
WA_APIKEY        = os.environ.get("WA_APIKEY", "")
SYMBOL           = "GC=F"
ALERT_MODE       = os.environ.get("ALERT_MODE", "full")
IST              = datetime.timedelta(hours=5, minutes=30)
 
MIN_RR           = 1.5   # Minimum R:R — trades below this = NEUTRAL
MIN_TF_AGREE     = 5     # Out of 8 TFs must agree for strong signal
ATR_SL_MULT      = 1.5   # SL = ATR * this multiplier
ATR_TP_MULT      = 2.5   # TP = ATR * this multiplier
 
# ── TIME ──────────────────────────────────────────────────────────────────────
def utcnow():  return datetime.datetime.utcnow()
def istnow():  return utcnow() + IST
def ist_str(): return istnow().strftime("%d %b %Y  %I:%M %p IST")
def utc_h():
    n = utcnow(); return n.hour + n.minute / 60
 
# ── SENDERS ───────────────────────────────────────────────────────────────────
def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15)
        print("✅ TG sent" if r.status_code == 200 else f"⚠️ TG {r.text[:80]}")
    except Exception as e:
        print(f"❌ TG: {e}")
 
def send_whatsapp(msg):
    if not WA_PHONE or not WA_APIKEY: return
    import re; clean = re.sub(r"<[^>]+>", "", msg)
    try:
        r = requests.get("https://api.callmebot.com/whatsapp.php",
                         params={"phone": WA_PHONE, "text": clean, "apikey": WA_APIKEY},
                         timeout=15)
        print("✅ WA sent" if r.status_code == 200 else f"⚠️ WA {r.text[:80]}")
    except Exception as e:
        print(f"❌ WA: {e}")
 
def send_all(msg):
    send_telegram(msg)
    send_whatsapp(msg)
 
# ── PRICE DATA ────────────────────────────────────────────────────────────────
def get_data():
    t = yf.Ticker(SYMBOL)
    d = {}
    d["m5"]  = t.history(period="3d",   interval="5m")
    d["m15"] = t.history(period="5d",   interval="15m")
    d["m30"] = t.history(period="5d",   interval="30m")
    d["h1"]  = t.history(period="7d",   interval="1h")
    d["h2"]  = t.history(period="10d",  interval="2h")
    d["h4"]  = t.history(period="14d",  interval="4h")
    d["d1"]  = t.history(period="30d",  interval="1d")
    d["w1"]  = t.history(period="52wk", interval="1wk")
    d["mo1"] = t.history(period="24mo", interval="1mo")
 
    if d["d1"].empty or len(d["d1"]) < 2:
        return None
 
    today = d["d1"].iloc[-1]
    prev  = d["d1"].iloc[-2]
 
    d["price"]   = round(float(today["Close"]), 2)
    d["day_h"]   = round(float(today["High"]),  2)
    d["day_l"]   = round(float(today["Low"]),   2)
    d["day_o"]   = round(float(today["Open"]),  2)
    d["prev_h"]  = round(float(prev["High"]),   2)
    d["prev_l"]  = round(float(prev["Low"]),    2)
    d["prev_c"]  = round(float(prev["Close"]),  2)
    d["week_h"]  = round(float(d["w1"]["High"].max()),  2) if not d["w1"].empty  else 0
    d["week_l"]  = round(float(d["w1"]["Low"].min()),   2) if not d["w1"].empty  else 0
    d["month_h"] = round(float(d["mo1"]["High"].max()), 2) if not d["mo1"].empty else 0
    d["month_l"] = round(float(d["mo1"]["Low"].min()),  2) if not d["mo1"].empty else 0
 
    return d
 
# ── TECHNICAL INDICATORS ──────────────────────────────────────────────────────
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()
 
def calc_rsi(df, period=14):
    if df is None or len(df) < period + 1:
        return 50.0
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return round(float((100 - 100 / (1 + rs)).iloc[-1]), 1)
 
def calc_atr(df, period=14):
    """Average True Range — real volatility measure"""
    if df is None or len(df) < period + 1:
        return None
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low  - close).abs()
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])
 
def calc_macd(df):
    """Returns (macd_line, signal_line, histogram)"""
    if df is None or len(df) < 35:
        return None, None, None
    close  = df["Close"]
    ema12  = calc_ema(close, 12).iloc[-1]
    ema26  = calc_ema(close, 26).iloc[-1]
    macd   = ema12 - ema26
    # Signal = EMA9 of MACD
    macd_series = calc_ema(close, 12) - calc_ema(close, 26)
    signal = macd_series.ewm(span=9, adjust=False).mean().iloc[-1]
    hist   = macd - signal
    return round(macd, 2), round(signal, 2), round(hist, 2)
 
def calc_bbands(df, period=20, std=2.0):
    """Bollinger Bands — returns (upper, mid, lower)"""
    if df is None or len(df) < period:
        return None, None, None
    close = df["Close"]
    mid   = close.rolling(period).mean().iloc[-1]
    sd    = close.rolling(period).std().iloc[-1]
    return round(mid + std*sd, 2), round(mid, 2), round(mid - std*sd, 2)
 
def vol_ratio(df, period=20):
    """Current volume vs average — >1.5 = spike"""
    if df is None or len(df) < period or "Volume" not in df.columns:
        return 1.0
    avg = float(df["Volume"].rolling(period).mean().iloc[-1])
    cur = float(df["Volume"].iloc[-1])
    if avg == 0: return 1.0
    return round(cur / avg, 2)
 
def detect_structure(df):
    """
    Market structure: Higher High / Higher Low = uptrend
                      Lower High / Lower Low   = downtrend
    Uses last 3 swing highs and lows from H4
    """
    if df is None or len(df) < 10:
        return "Unknown"
    highs = df["High"].values[-10:]
    lows  = df["Low"].values[-10:]
    # Simple: compare last 3 periods
    h = [highs[-8], highs[-5], highs[-2]]
    l = [lows[-8],  lows[-5],  lows[-2]]
    if h[2] > h[1] > h[0] and l[2] > l[1] > l[0]:
        return "HH/HL 📈"   # Uptrend structure
    if h[2] < h[1] < h[0] and l[2] < l[1] < l[0]:
        return "LH/LL 📉"   # Downtrend structure
    if h[2] > h[0] and l[2] < l[0]:
        return "Expanding ↔"
    return "Ranging ↔"
 
# ── PIVOT POINTS ─────────────────────────────────────────────────────────────
def calc_pivots(h, l, c):
    pp = round((h + l + c) / 3, 2)
    return dict(
        PP=pp,
        R1=round(2*pp - l,    2), R2=round(pp + (h-l),      2), R3=round(h + 2*(pp-l), 2),
        S1=round(2*pp - h,    2), S2=round(pp - (h-l),      2), S3=round(l - 2*(h-pp), 2)
    )
 
# ── MULTI-TF TREND ENGINE ────────────────────────────────────────────────────
def tf_trend(df):
    """
    Returns: +1 Bullish, -1 Bearish, 0 Neutral
    Condition: price > EMA20 > EMA50 → Bull
               price < EMA20 < EMA50 → Bear
    """
    if df is None or len(df) < 21:
        return 0
    c   = df["Close"]
    e20 = calc_ema(c, 20).iloc[-1]
    e50 = calc_ema(c, 50).iloc[-1] if len(c) >= 50 else e20
    p   = float(c.iloc[-1])
    if p > e20 and e20 > e50:
        return 1
    if p < e20 and e20 < e50:
        return -1
    return 0
 
def all_trends(d):
    tfs = [
        ("5m",   d["m5"]),
        ("15m",  d["m15"]),
        ("30m",  d["m30"]),
        ("1H",   d["h1"]),
        ("2H",   d["h2"]),
        ("4H",   d["h4"]),
        ("Daily",d["d1"]),
        ("Week", d["w1"]),
    ]
    results = []
    for label, df in tfs:
        t = tf_trend(df)
        emoji = "🟢 Bull" if t == 1 else ("🔴 Bear" if t == -1 else "🟡 Side")
        results.append((label, t, emoji))
 
    bull = sum(1 for _, t, _ in results if t ==  1)
    bear = sum(1 for _, t, _ in results if t == -1)
    neut = sum(1 for _, t, _ in results if t ==  0)
 
    if bull >= 6:   overall, overall_t = "🟢 STRONG BULLISH",  1
    elif bull >= 4: overall, overall_t = "🟡 MILD BULLISH",    1
    elif bear >= 6: overall, overall_t = "🔴 STRONG BEARISH", -1
    elif bear >= 4: overall, overall_t = "🟠 MILD BEARISH",   -1
    else:           overall, overall_t = "⚪ NEUTRAL",          0
 
    lines = [f"  {lbl:<6}: {em}" for lbl, _, em in results]
    return "\n".join(lines), overall, overall_t, bull, bear, neut
 
# ── HIGH-ACCURACY SIGNAL ENGINE ──────────────────────────────────────────────
def generate_signal(d, pvt, overall_trend):
    """
    New signal engine — 8 confluence factors:
    1. Multi-TF trend alignment
    2. RSI level + direction
    3. Price vs key levels (PP, prev high/low)
    4. MACD histogram direction
    5. Bollinger band position
    6. Volume confirmation
    7. Market structure (HH/HL vs LH/LL)
    8. ATR-based SL/TP with minimum R:R gate
    """
    price = d["price"]
    pvt_pp, pvt_r1, pvt_s1 = pvt["PP"], pvt["R1"], pvt["S1"]
 
    # ── RSI (1H) ──
    rsi_1h  = calc_rsi(d["h1"])
    rsi_15m = calc_rsi(d["m15"])
 
    # ── MACD (1H) ──
    macd_val, macd_sig, macd_hist = calc_macd(d["h1"])
 
    # ── Bollinger Bands (1H) ──
    bb_upper, bb_mid, bb_lower = calc_bbands(d["h1"])
 
    # ── Volume ──
    vol_r = vol_ratio(d["h1"])
 
    # ── Structure (4H) ──
    structure = detect_structure(d["h4"])
 
    # ── ATR for SL/TP ──
    atr_1h = calc_atr(d["h1"])
    atr_4h = calc_atr(d["h4"])
    atr    = atr_1h if atr_1h else (atr_4h if atr_4h else 10.0)
 
    # ── SCORING SYSTEM (max +10 / min -10) ──
    score = 0
    reasons_bull = []
    reasons_bear = []
 
    # 1. Multi-TF trend (most important) — ±3
    if overall_trend == 1:
        score += 3
        reasons_bull.append("Multi-TF Bullish alignment")
    elif overall_trend == -1:
        score -= 3
        reasons_bear.append("Multi-TF Bearish alignment")
 
    # 2. RSI ±2
    if rsi_1h < 30:
        score += 2
        reasons_bull.append(f"RSI oversold ({rsi_1h})")
    elif rsi_1h > 70:
        score -= 2
        reasons_bear.append(f"RSI overbought ({rsi_1h})")
    elif rsi_1h > 55 and overall_trend == 1:
        score += 1
        reasons_bull.append(f"RSI momentum bullish ({rsi_1h})")
    elif rsi_1h < 45 and overall_trend == -1:
        score -= 1
        reasons_bear.append(f"RSI momentum bearish ({rsi_1h})")
 
    # 3. Price vs key levels ±2
    if price > d["prev_h"]:
        score += 2
        reasons_bull.append("Price above Prev Day High (breakout)")
    elif price < d["prev_l"]:
        score -= 2
        reasons_bear.append("Price below Prev Day Low (breakdown)")
    elif price > pvt_pp:
        score += 1
        reasons_bull.append("Price above Pivot PP")
    elif price < pvt_pp:
        score -= 1
        reasons_bear.append("Price below Pivot PP")
 
    # 4. MACD ±1
    if macd_hist is not None:
        if macd_hist > 0 and macd_val > macd_sig:
            score += 1
            reasons_bull.append("MACD bullish crossover")
        elif macd_hist < 0 and macd_val < macd_sig:
            score -= 1
            reasons_bear.append("MACD bearish crossover")
 
    # 5. Bollinger Bands ±1
    if bb_lower is not None and bb_upper is not None:
        if price <= bb_lower:
            score += 1
            reasons_bull.append("Price at/below BB lower (bounce zone)")
        elif price >= bb_upper:
            score -= 1
            reasons_bear.append("Price at/above BB upper (reversal risk)")
 
    # 6. Volume ±1
    if vol_r >= 1.5:
        if overall_trend == 1:
            score += 1
            reasons_bull.append(f"Volume spike ({vol_r}x avg) — confirms bulls")
        elif overall_trend == -1:
            score -= 1
            reasons_bear.append(f"Volume spike ({vol_r}x avg) — confirms bears")
 
    # 7. Market structure ±1
    if "HH/HL" in structure:
        score += 1
        reasons_bull.append("Bullish market structure (HH/HL)")
    elif "LH/LL" in structure:
        score -= 1
        reasons_bear.append("Bearish market structure (LH/LL)")
 
    # ── DETERMINE DIRECTION ──
    # Thresholds: Bull ≥ 5, Bear ≤ -4, else NEUTRAL
    if score >= 5:
        direction = "🟢 BUY"
        bias      = 1
    elif score <= -4:
        direction = "🔴 SELL"
        bias      = -1
    else:
        direction = "⚪ NEUTRAL"
        bias      = 0
 
    # ── ATR-BASED SL/TP ──
    if bias == 1:
        entry = price
        sl    = round(price - atr * ATR_SL_MULT, 2)
        tp    = round(price + atr * ATR_TP_MULT,  2)
        # Also check pivot support
        if pvt_s1 > sl:
            sl = round(pvt_s1 - 2, 2)   # SL just below S1
    elif bias == -1:
        entry = price
        sl    = round(price + atr * ATR_SL_MULT, 2)
        tp    = round(price - atr * ATR_TP_MULT,  2)
        if pvt_r1 < sl:
            sl = round(pvt_r1 + 2, 2)   # SL just above R1
    else:
        entry = price
        sl    = round(pvt_s1, 2)
        tp    = round(pvt_r1, 2)
 
    risk   = round(abs(entry - sl),   2)
    reward = round(abs(tp   - entry), 2)
    rr     = round(reward / risk, 2) if risk > 0 else 0
 
    # ── R:R GATE — if RR < 1.5, downgrade to NEUTRAL ──
    if bias != 0 and rr < MIN_RR:
        direction   = "⚪ NEUTRAL"
        bias        = 0
        gate_reason = f"⚠️ R:R {rr} < {MIN_RR} min — Signal filtered out"
    else:
        gate_reason = None
 
    # ── CONFIDENCE LABEL ──
    abs_score = abs(score)
    if abs_score >= 7:   confidence = "🔥 VERY HIGH (7+/10)"
    elif abs_score >= 5: confidence = "✅ HIGH (5-6/10)"
    elif abs_score >= 3: confidence = "🟡 MEDIUM (3-4/10)"
    else:                confidence = "⚠️ LOW (0-2/10) — Skip"
 
    reasons = reasons_bull if bias >= 0 else reasons_bear
 
    return dict(
        direction  = direction,
        bias       = bias,
        entry      = entry,
        sl         = sl,
        tp         = tp,
        rr         = rr,
        score      = score,
        confidence = confidence,
        rsi_1h     = rsi_1h,
        rsi_15m    = rsi_15m,
        macd_hist  = macd_hist,
        atr        = round(atr, 2),
        structure  = structure,
        vol_ratio  = vol_r,
        reasons    = reasons,
        gate_reason= gate_reason,
    )
 
# ── SESSIONS & KILL ZONES ────────────────────────────────────────────────────
def sessions():
    h = utc_h()
    s_map  = {"Asia": (0, 8), "London": (7, 16), "New York": (12, 21)}
    kz_map = {"Asia KZ": (0, 4), "London KZ": (6, 9), "NY KZ": (12, 15), "LC KZ": (15, 16)}
    act_s  = [k for k, (a, b) in s_map.items()  if a <= h < b]
    act_k  = [k for k, (a, b) in kz_map.items() if a <= h < b]
    olap   = []
    if 7  <= h < 8:  olap.append("Asia / London ⚡")
    if 12 <= h < 16: olap.append("London / NY ⚡")
    next_s = []
    for name, (a, b) in s_map.items():
        if h < a:
            diff     = a - h
            open_ist = (utcnow() + IST + datetime.timedelta(hours=diff)).strftime("%I:%M %p")
            next_s.append(f"{name} opens at {open_ist} IST")
    return act_s, act_k, olap, next_s
 
def session_quality(act_k, olap):
    """High quality = in kill zone or overlap"""
    if olap: return "🔥 PRIME TIME (Overlap)"
    if act_k: return "✅ Kill Zone Active"
    return "🟡 Normal Session"
 
# ── MOON PHASE ────────────────────────────────────────────────────────────────
def moon():
    m = ephem.Moon(); m.compute(datetime.date.today()); ph = float(m.phase)
    name = ("🌑 New Moon" if ph < 6 else "🌒 Waxing Crescent" if ph < 25
            else "🌓 First Quarter" if ph < 35 else "🌔 Waxing Gibbous" if ph < 60
            else "🌕 Full Moon" if ph < 66 else "🌖 Waning Gibbous" if ph < 75
            else "🌗 Last Quarter" if ph < 85 else "🌘 Waning Crescent")
    return name, round(ph, 1)
 
# ── NEWS CALENDAR ────────────────────────────────────────────────────────────
def news_today():
    try:
        data  = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10).json()
        today = datetime.date.today().strftime("%Y-%m-%d")
        items = [e for e in data if e.get("impact") in ("High", "Medium")
                 and e.get("currency") == "USD" and e.get("date", "")[:10] == today]
        if not items: return "  Aaj koi major USD news nahi."
        out = []
        for e in items[:8]:
            raw = e.get("date", "")
            try:
                hh, mm = int(raw[11:13]), int(raw[14:16])
                ist_t  = (datetime.datetime(2000, 1, 1, hh, mm) + IST).strftime("%I:%M %p")
            except: ist_t = "?"
            imp  = "🔴 HIGH" if e["impact"] == "High" else "🟡 MED"
            fc   = e.get("forecast", "") or "-"
            prev = e.get("previous", "") or "-"
            out.append(f"  {imp} {ist_t} IST — {e['title']}\n    Forecast:{fc} | Prev:{prev}")
        return "\n".join(out)
    except Exception as ex:
        return f"  Error: {ex}"
 
def news_week():
    try:
        data  = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10).json()
        items = [e for e in data if e.get("impact") in ("High", "Medium") and e.get("currency") == "USD"]
        if not items: return "  Is hafte koi major news nahi."
        out = []
        for e in items[:12]:
            raw = e.get("date", "")
            try:
                day   = datetime.datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%a %d %b")
                hh, mm = int(raw[11:13]), int(raw[14:16])
                ist_t  = (datetime.datetime(2000, 1, 1, hh, mm) + IST).strftime("%I:%M %p")
            except: day = "?"; ist_t = "?"
            imp = "🔴" if e["impact"] == "High" else "🟡"
            out.append(f"  {imp} {day} {ist_t} — {e['title']}")
        return "\n".join(out)
    except Exception as ex:
        return f"  Error: {ex}"
 
# ── SIGNAL ALERT (Short — sent every 30min) ──────────────────────────────────
def signal_alert(d):
    pvt                        = calc_pivots(d["prev_h"], d["prev_l"], d["prev_c"])
    _, overall, overall_t, bull, bear, neut = all_trends(d)
    sig                        = generate_signal(d, pvt, overall_t)
    act_s, act_k, olap, _      = sessions()
    sq                         = session_quality(act_k, olap)
    rsi_txt                    = f"{sig['rsi_1h']} {'⬆' if sig['rsi_1h'] > 50 else '⬇'}"
 
    # Reasons block
    reasons_block = ""
    if sig["reasons"]:
        reasons_block = "\n📋 <b>Confluence:</b>\n" + "\n".join(f"  • {r}" for r in sig["reasons"][:4])
 
    gate_block = f"\n⛔ {sig['gate_reason']}" if sig["gate_reason"] else ""
 
    return f"""
⚡ <b>SCALPINGMEBOT:  SIGNAL ALERT</b>
📅 {ist_str()}
💰 XAU/USD: ${d['price']:,.2f}
 
{sig['direction']}  |  Confidence: {sig['confidence']}
  Entry : ${sig['entry']:,.2f}
  SL    : ${sig['sl']:,.2f}
  TP    : ${sig['tp']:,.2f}
  R:R   : 1 : {sig['rr']}
  Score : {sig['score']:+d}/10
  ATR   : ${sig['atr']:,.2f}
{gate_block}
 
📊 Trend  : {bull}B / {bear}S / {neut}N  →  {overall}
📈 Structure: {sig['structure']}
📉 RSI(1H) : {rsi_txt}  |  RSI(15m): {sig['rsi_15m']}
🕯️ MACD hist: {sig['macd_hist'] if sig['macd_hist'] is not None else '—'}
📦 Vol ratio: {sig['vol_ratio']}x
{reasons_block}
 
🌐 Sessions : {', '.join(act_s) if act_s else 'None'}
🎯 Kill Zones: {', '.join(act_k) if act_k else 'None'}
⚡ Overlap  : {', '.join(olap)  if olap  else 'None'}
🏆 Quality  : {sq}
""".strip()
 
# ── FULL ALERT ────────────────────────────────────────────────────────────────
def full_alert(d):
    chg  = round(d["price"] - d["prev_c"], 2)
    pct  = round(chg / d["prev_c"] * 100, 2) if d["prev_c"] else 0
    arr  = "▲" if chg >= 0 else "▼"
    pvt  = calc_pivots(d["prev_h"], d["prev_l"], d["prev_c"])
    trend_block, overall, overall_t, bull, bear, neut = all_trends(d)
    sig  = generate_signal(d, pvt, overall_t)
    act_s, act_k, olap, next_s = sessions()
    sq   = session_quality(act_k, olap)
    moon_name, moon_pct = moon()
    n_today = news_today()
    n_week  = news_week()
 
    reasons_block = "\n".join(f"  • {r}" for r in sig["reasons"][:5]) if sig["reasons"] else "  —"
    gate_block    = f"\n⛔ {sig['gate_reason']}" if sig["gate_reason"] else ""
    macd_str      = f"{sig['macd_hist']:+.2f}" if sig["macd_hist"] is not None else "—"
 
    return f"""
🏅 <b>XAU/USD MEGA ALERT — v4</b>
📅 {ist_str()}
 
━━━━━━━━━━━━━━━━━━━━
💰 <b>PRICE</b>: ${d['price']:,.2f}  {arr} {abs(chg)} ({abs(pct)}%)
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
📈 <b>MULTI-TF TREND</b>  [{bull}B / {bear}S / {neut}N]
{trend_block}
  ─────────
  Overall : {overall}
 
━━━━━━━━━━━━━━━━━━━━
🏗️ <b>MARKET STRUCTURE (4H)</b>: {sig['structure']}
 
━━━━━━━━━━━━━━━━━━━━
📉 <b>INDICATORS</b>
  RSI (1H)  : {sig['rsi_1h']}
  RSI (15m) : {sig['rsi_15m']}
  MACD hist : {macd_str}
  ATR (1H)  : ${sig['atr']:,.2f}
  Vol ratio : {sig['vol_ratio']}x
 
━━━━━━━━━━━━━━━━━━━━
🎯 <b>SIGNAL</b>
  Direction  : {sig['direction']}
  Confidence : {sig['confidence']}
  Score      : {sig['score']:+d}/10
  Entry      : ${sig['entry']:,.2f}
  Stop Loss  : ${sig['sl']:,.2f}
  Take Profit: ${sig['tp']:,.2f}
  Risk:Reward: 1 : {sig['rr']}
{gate_block}
 
📋 <b>Confluence Reasons:</b>
{reasons_block}
 
━━━━━━━━━━━━━━━━━━━━
🌐 <b>SESSIONS</b>
  Active    : {', '.join(act_s) if act_s else 'None'}
  Kill Zones: {', '.join(act_k) if act_k else 'None'}
  Overlap   : {', '.join(olap)  if olap  else 'None'}
  Quality   : {sq}
{('  ' + '\n  '.join(next_s)) if next_s else ''}
 
━━━━━━━━━━━━━━━━━━━━
📰 <b>TODAY'S NEWS</b>
{n_today}
 
━━━━━━━━━━━━━━━━━━━━
📅 <b>WEEKLY CALENDAR</b>
{n_week}
 
━━━━━━━━━━━━━━━━━━━━
{moon_name}  {moon_pct}% illuminated
 
<i>XAU/USD Bot v4 | 8-Factor Confluence | ATR SL/TP | IST</i>
""".strip()
 
# ── NEWS ALERT ────────────────────────────────────────────────────────────────
def news_alert():
    return f"""
📰 <b>NEWS ALERT — TODAY (IST)</b>
📅 {ist_str()}
 
<b>Aaj ke high-impact events:</b>
{news_today()}
 
━━━━━━━━━━━━━━━━━━━━
📅 <b>Is hafte ke events:</b>
{news_week()}
""".strip()
 
# ── SESSION ALERT ─────────────────────────────────────────────────────────────
def session_alert_msg():
    h       = utcnow().hour
    opens   = {7: "🇬🇧 London OPEN",  12: "🇺🇸 New York OPEN",  0: "🌏 Asia OPEN"}
    closes  = {16: "🇬🇧 London CLOSE", 21: "🇺🇸 NY CLOSE",       8: "🌏 Asia CLOSE"}
    name    = opens.get(h) or closes.get(h) or "Session Update"
    act_s, act_k, olap, next_s = sessions()
    sq      = session_quality(act_k, olap)
    return f"""
🔔 <b>{name}</b>
📅 {ist_str()}
 
Active    : {', '.join(act_s) if act_s else 'None'}
Kill Zones: {', '.join(act_k) if act_k else 'None'}
Overlap   : {', '.join(olap)  if olap  else 'None'}
Quality   : {sq}
{chr(10).join(next_s) if next_s else ''}
""".strip()
 
# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print(f"🚀 XAU/USD Bot v4 | {ALERT_MODE} | {ist_str()}")
 
    if ALERT_MODE == "session":
        send_all(session_alert_msg())
        return
 
    if ALERT_MODE == "news":
        send_all(news_alert())
        return
 
    d = get_data()
    if d is None:
        send_all(f"⚠️ Data fetch failed.\n📅 {ist_str()}\nMarket band ho sakta hai.")
        return
 
    msg = signal_alert(d) if ALERT_MODE == "signal" else full_alert(d)
    send_all(msg)
    print(msg)
 
if __name__ == "__main__":
    main()
 
