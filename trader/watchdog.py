"""Run once a minute by a systemd timer (as root). If the trader's heartbeat file is stale during market hours it
restarts the service and tells you on Telegram. Independent of the trader process, so it also catches a hung one."""
import datetime
import os
import subprocess
import sys
import time

from trader.clock import ist_now
from trader.config import Config
from trader.tg_api import TelegramAPI

STALE_S = 120
MIN_GAP_S = 600


def decide(now_ist, hb_age, since_restart):
    """-> 'restart' | 'ok' | 'wait'."""
    if now_ist.weekday() >= 5 or not (datetime.time(8, 55) <= now_ist.time() <= datetime.time(15, 40)):
        return "ok"
    if hb_age is None or hb_age > STALE_S:
        return "wait" if since_restart is not None and since_restart < MIN_GAP_S else "restart"
    return "ok"


def main():
    cfg = Config()
    now = ist_now()
    marker = os.path.join(cfg.state, "watchdog_restart")
    hb = None
    if os.path.exists(cfg.heartbeat):
        hb = time.time() - os.path.getmtime(cfg.heartbeat)
    since = time.time() - os.path.getmtime(marker) if os.path.exists(marker) else None
    d = decide(now, hb, since)
    if d != "restart":
        return 0
    open(marker, "w").write(now.isoformat())
    rc = subprocess.call(["systemctl", "restart", "trader.service"])
    msg = "WATCHDOG: heartbeat %s, restarted trader (rc=%s)." % ("missing" if hb is None else "%ds old" % hb, rc)
    try:
        TelegramAPI(cfg.env["TG_TOKEN"]).send_message(cfg.env["TG_CHAT_ID"], msg)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
