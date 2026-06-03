"""
XAU/USD 24/7 Scheduler — Railway.app
Exactly time pe alert bhejta hai — no delay
"""
import time, datetime, subprocess, sys, os

IST = datetime.timedelta(hours=5, minutes=30)

def ist_now():
    return datetime.datetime.utcnow() + IST

def log(msg):
    print(f"[{ist_now().strftime('%d %b %Y %I:%M %p IST')}] {msg}", flush=True)

def run_bot(mode):
    log(f"▶ Running bot — mode: {mode}")
    env = os.environ.copy()
    env["ALERT_MODE"] = mode
    try:
        result = subprocess.run(
            [sys.executable, "xauusd_bot.py"],
            env=env, timeout=120, capture_output=True, text=True
        )
        if result.stdout: print(result.stdout, flush=True)
        if result.stderr: print(result.stderr, flush=True)
        log(f"✅ Done — mode: {mode}")
    except subprocess.TimeoutExpired:
        log(f"⚠️ Timeout — mode: {mode}")
    except Exception as e:
        log(f"❌ Error: {e}")

def should_run(now_ist):
    h  = now_ist.hour
    m  = now_ist.minute
    wd = now_ist.weekday()  # 0=Mon, 6=Sun

    # Weekend skip (Saturday=5, Sunday=6)
    # Railway chalega weekend pe bhi — comment out karo agar weekend bhi chahiye
    # if wd >= 5: return None

    # ── FULL ALERT (IST times) ────────────────────────────────────────────────
    # 07:00 AM — Morning briefing
    if h == 7  and m == 0:  return "full"
    # 12:30 PM — London open
    if h == 12 and m == 30: return "full"
    # 05:30 PM — NY open
    if h == 17 and m == 30: return "full"
    # 09:00 PM — NY midpoint
    if h == 21 and m == 0:  return "full"

    # ── NEWS ALERT ────────────────────────────────────────────────────────────
    # 07:30 AM — Daily news briefing
    if h == 7  and m == 30: return "news"
    # Monday 08:00 AM — Weekly calendar
    if wd == 0 and h == 8 and m == 0: return "news"

    # ── SESSION ALERTS (UTC converted to IST) ─────────────────────────────────
    # Asia open  = 00:00 UTC = 05:30 IST
    if h == 5  and m == 30: return "session"
    # London open = 07:00 UTC = 12:30 IST
    if h == 12 and m == 30: return "session"
    # NY open     = 12:00 UTC = 17:30 IST
    if h == 17 and m == 30: return "session"
    # London close = 16:00 UTC = 21:30 IST
    if h == 21 and m == 30: return "session"
    # NY close    = 21:00 UTC = 02:30 IST
    if h == 2  and m == 30: return "session"

    # ── SIGNAL ALERT — har 30 min (trading hours: 07:00 AM – 11:30 PM IST) ───
    if 7 <= h <= 23 and m in (0, 30): return "signal"
    # Early morning bhi cover karo (00:00 – 02:30 IST for NY session)
    if h <= 2 and m in (0, 30): return "signal"

    return None

def main():
    log("🚀 XAU/USD Scheduler started — Railway.app 24/7")
    log("📡 Waiting for next scheduled time...")

    last_run_minute = -1  # prevent double-run in same minute

    while True:
        now = ist_now()
        current_minute = now.hour * 60 + now.minute

        if current_minute != last_run_minute:
            mode = should_run(now)
            if mode:
                last_run_minute = current_minute
                run_bot(mode)

        # Sleep 20 seconds — check karता rahega
        time.sleep(20)

if __name__ == "__main__":
    main()
