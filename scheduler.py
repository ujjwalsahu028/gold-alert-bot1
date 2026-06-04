"""
Scheduler v3 — Hourly full alert + dashboard link in Telegram
"""
import time, datetime, subprocess, sys, os, requests

IST = datetime.timedelta(hours=5, minutes=30)
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN","")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","")
DASHBOARD_URL    = os.environ.get("DASHBOARD_URL","")  # Set in Railway variables

def ist_now(): return datetime.datetime.utcnow() + IST
def log(m): print(f"[{ist_now().strftime('%d %b %I:%M %p IST')}] {m}", flush=True)

def run_bot(mode):
    log(f"▶ mode={mode}")
    env=os.environ.copy(); env["ALERT_MODE"]=mode
    try:
        r=subprocess.run([sys.executable,"xauusd_bot.py"],
            env=env,timeout=180,capture_output=True,text=True)
        if r.stdout: print(r.stdout,flush=True)
        if r.stderr and "error" in r.stderr.lower(): print(r.stderr[:200],flush=True)
        log(f"✅ done")
        # Send dashboard link after full alert
        if mode=="full" and DASHBOARD_URL and TELEGRAM_TOKEN:
            try:
                msg = f'📊 <b>Live Dashboard:</b> <a href="{DASHBOARD_URL}">{DASHBOARD_URL}</a>'
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},timeout=10)
            except: pass
    except subprocess.TimeoutExpired: log("⚠️ timeout")
    except Exception as e: log(f"❌ {e}")

def get_mode(now):
    h=now.hour; m=now.minute; wd=now.weekday()
    utc_h=datetime.datetime.utcnow().hour
    # Session alerts on hour mark
    if m==0 and utc_h in {0,7,8,12,16,21}: return "session"
    # News alerts
    if h==7 and m==30: return "news"
    if h==8 and m==0 and wd==0: return "news"
    # Full alert every hour
    if m==0: return "full"
    return None

def main():
    log("🚀 Scheduler v3 — Hourly alerts + Dashboard")
    last_run={}
    while True:
        now=ist_now()
        key=f"{now.date()}_{now.hour}_{now.minute}"
        if key not in last_run:
            mode=get_mode(now)
            if mode:
                last_run[key]=mode
                if len(last_run)>20: last_run.pop(list(last_run.keys())[0])
                run_bot(mode)
        time.sleep(15)

if __name__=="__main__":
    main()
