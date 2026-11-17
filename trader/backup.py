"""Daily data backup: export one day's rows (bars, signals, trades, events, health, recon) as gzipped CSV.
The `kv` table is NEVER exported (it holds the Kite access token and login state). Opens the DB read-only, so it cannot
disturb the running trader. Idempotent: re-running a day overwrites that day's files.
Usage: python -m trader.backup --out DIR [--day YYYY-MM-DD] [--db PATH]"""
import argparse
import csv
import gzip
import io
import os
import sqlite3
import sys
import time

# table -> SQL selecting one day's rows (? = day)
TABLES = {
    "bars": "SELECT * FROM bars WHERE day=? ORDER BY symbol, slot, src",
    "signals": "SELECT * FROM signals WHERE day=? ORDER BY slot, symbol",
    "trades": "SELECT t.* FROM trades t JOIN signals s ON s.id=t.signal_id WHERE s.day=? ORDER BY t.id",
    "events": "SELECT * FROM events WHERE substr(ts,1,10)=? ORDER BY ts",
    "health": "SELECT * FROM health WHERE substr(ts,1,10)=? ORDER BY ts",
    "recon": "SELECT * FROM recon WHERE day=? ORDER BY symbol, slot",
}


def export_day(db_path, out_dir, day):
    """Returns {table: rows}. Files: <out_dir>/<day>/<table>.csv.gz"""
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        d = os.path.join(out_dir, day)
        os.makedirs(d, exist_ok=True)
        counts = {}
        for name, sql in TABLES.items():
            cur = con.execute(sql, (day,))
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            counts[name] = len(rows)
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(cols)
            w.writerows(rows)
            # mtime=0 -> identical content gives an identical file, so git sees no change on a re-run
            with open(os.path.join(d, name + ".csv.gz"), "wb") as raw:
                with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as g:
                    g.write(buf.getvalue().encode("utf-8"))
        return counts
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--day", default=time.strftime("%Y-%m-%d"))
    home = os.environ.get("TRADER_HOME") or os.path.expanduser("~/trader")
    ap.add_argument("--db", default=os.path.join(home, "state", "trader.db"))
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        print("no database at %s" % a.db)
        return 2
    c = export_day(a.db, a.out, a.day)
    print("backup %s: %s" % (a.day, ", ".join("%s=%d" % kv for kv in sorted(c.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
