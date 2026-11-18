#!/usr/bin/env python3
"""Download the day's exchange files into <dest>/<YYYY-MM-DD>/ (run on the VM after ~18:30; the lab network blocks it).
Usage: python3 tools/bhavcopy.py [YYYY-MM-DD] [--dest DIR]
Files: NSE F&O bhavcopy (zip), BSE F&O bhavcopy (csv), NSE index closes (csv). Exit code 0 only if all three arrived.
The URLs are the exchanges' public archive paths; if one changes, only the URLS table below needs editing."""
import datetime
import os
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}


def urls(d):
    ymd, dmy = d.strftime("%Y%m%d"), d.strftime("%d%m%Y")
    return [("BhavCopy_NSE_FO_0_0_0_%s_F_0000.csv.zip" % ymd,
             "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_%s_F_0000.csv.zip" % ymd),
            ("BhavCopy_BSE_FO_0_0_0_%s_F_0000.CSV" % ymd,
             "https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_%s_F_0000.CSV" % ymd),
            ("ind_close_all_%s.csv" % dmy,
             "https://nsearchives.nseindia.com/content/indices/ind_close_all_%s.csv" % dmy)]


def fetch(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if len(data) < 500 or data[:15].lower().startswith((b"<!doctype", b"<html")):
        raise ValueError("not a data file (%d bytes)" % len(data))
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main(argv):
    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
    day, args = None, list(argv)
    while args:
        a = args.pop(0)
        if a == "--dest":
            dest = args.pop(0)
        else:
            day = a
    d = datetime.datetime.strptime(day, "%Y-%m-%d").date() if day else datetime.date.today()
    out = os.path.join(dest, d.isoformat())
    os.makedirs(out, exist_ok=True)
    bad = 0
    for name, url in urls(d):
        p = os.path.join(out, name)
        if os.path.exists(p) and os.path.getsize(p) > 500:
            print("have  %s" % name)
            continue
        try:
            print("got   %s (%d bytes)" % (name, fetch(url, p)))
        except Exception as e:
            bad += 1
            print("FAIL  %s: %s" % (name, e))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
