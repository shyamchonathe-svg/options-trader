#!/usr/bin/env python3
"""Download 5-minute index candles (Nifty 50, Sensex, India VIX) from Kite for a date range. Run ON THE VM.
Needs a valid Kite token (log in first with /login in the bot; tokens die ~06:00 IST).
Usage:  ~/trader/venv/bin/python tools/fetch_index_history.py 2026-09-01 2026-11-20 [outdir]
Writes <outdir>/<NAME>_5m.csv  (day,time,open,high,low,close), default outdir = ~/trader/data/history.
Read-only: it only calls historical_data / quote; it never places or changes anything."""
import csv
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from trader.config import Config  # noqa: E402
from trader.adapters.kite_adapter import to_ist_naive  # noqa: E402

SYMBOLS = [("NIFTY", "NSE:NIFTY 50"), ("SENSEX", "BSE:SENSEX"), ("VIX", "NSE:INDIA VIX")]
CHUNK_DAYS = 55            # Kite allows up to 100 days per 5-minute request; stay well inside


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    d0 = datetime.datetime.strptime(argv[1], "%Y-%m-%d")
    d1 = datetime.datetime.strptime(argv[2], "%Y-%m-%d")
    cfg = Config()
    out = argv[3] if len(argv) > 3 else os.path.join(cfg.home, "data", "history")
    if not os.path.isdir(out):
        os.makedirs(out)
    from kiteconnect import KiteConnect
    tok = json.load(open(os.path.join(cfg.state, "kite_token.json")))
    k = KiteConnect(api_key=cfg.env.get("KITE_API_KEY", ""))
    k.set_access_token(tok["access_token"])
    try:
        k.profile()
    except Exception as e:
        print("Kite token not accepted (%s). Log in with /login in the bot, then run again." % type(e).__name__)
        return 1
    quotes = k.quote([s for _, s in SYMBOLS])
    for name, sym in SYMBOLS:
        token = int(quotes[sym]["instrument_token"])
        rows, a = [], d0
        while a <= d1:
            b = min(a + datetime.timedelta(days=CHUNK_DAYS), d1)
            part = k.historical_data(token, a.replace(hour=9, minute=0), b.replace(hour=15, minute=35), "5minute")
            rows.extend(part)
            a = b + datetime.timedelta(days=1)
        seen, n = set(), 0
        path = os.path.join(out, "%s_5m.csv" % name)
        with open(path, "w") as fh:
            w = csv.writer(fh)
            w.writerow(["day", "time", "open", "high", "low", "close"])
            for r in rows:
                t = to_ist_naive(r["date"])
                if t in seen:
                    continue
                seen.add(t)
                w.writerow([t.strftime("%Y-%m-%d"), t.strftime("%H:%M"), r["open"], r["high"], r["low"], r["close"]])
                n += 1
        days = len(set(x.strftime("%Y-%m-%d") for x in seen))
        print("%-7s %6d candles, %3d days -> %s" % (name, n, days, path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
