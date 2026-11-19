#!/usr/bin/env python3
"""Cross-check what YOU call a hammer against the formulas.  Read-only, Python 3.6+.
  python3 tools/hammer_check.py DB DAY SYMBOL_PATTERN HH:MM [HH:MM ...]   metrics + which formulas accept each candle
  python3 tools/hammer_check.py DB DAY SYMBOL_PATTERN --scan              every candle of the day each key formula accepts
Candle SHAPE only (body / close position / wick sizes / colour / a red candle in the previous two); the EMA10-touch test is
not applied here.  Uses the exchange-exact candles when present, else live.  DB = a copy/snapshot of trader.db."""
import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from trader import research as RS, rules_v3 as R

KEY = ["H0 v3 (current)", "H4 small hammer", "H3 long wick (40%)", "H7 classic hammer", "H8 classic, any colour", "H9 classic (wick 40%)"]


def load(db, day, pat):
    out, sym = {}, None
    for s, o, h, l, c, src, name in db.execute(
            "select slot,o,h,l,c,src,symbol from bars where day=? and symbol like ? and src in ('live','exact','backfill') order by symbol, slot, src='exact'", (day, pat)):
        sym = sym or name
        if name != sym: break
        out[s] = {"O": o, "H": h, "L": l, "C": c}
    return sym, out


def metrics(b):
    r = b["H"] - b["L"]
    if r <= 0: return None
    return dict(body=abs(b["C"] - b["O"]) / r, clv=(b["C"] - b["L"]) / r, lw=(min(b["O"], b["C"]) - b["L"]) / r,
                uw=(b["H"] - max(b["O"], b["C"])) / r, green=b["C"] > b["O"])


def accepts(by, k, p):
    ema = dict((j, by[j]["C"]) for j in by)           # shape only: make the EMA touch test pass
    q = dict(p); q["touch"] = 1; q["tol"] = 10.0
    return RS.hammer_ok(by, ema, k, q)


def main(a):
    db = sqlite3.connect("file:%s?mode=ro" % a[0], uri=True)
    sym, by = load(db, a[1], a[2])
    print("symbol:", sym)
    if a[3] == "--scan":
        for name in KEY:
            hits = [R.tstr(k) for k in sorted(by) if accepts(by, k, RS.HAMMERS[name])]
            print("%-26s %2d  %s" % (name, len(hits), " ".join(hits)))
        return
    for t in a[3:]:
        hh, mm = t.split(":"); k = (int(hh) * 60 + int(mm) - (9 * 60 + 15)) // 5
        b = by.get(k)
        if not b: print(t, "no candle"); continue
        m = metrics(b)
        print("\n%s (slot %d) O%.2f H%.2f L%.2f C%.2f  body %.0f%% close-pos %.2f lower-wick %.0f%% upper-wick %.0f%% %s" % (
            t, k, b["O"], b["H"], b["L"], b["C"], m["body"] * 100, m["clv"], m["lw"] * 100, m["uw"] * 100, "green" if m["green"] else "red"))
        print("   accepted by:", ", ".join(n for n in RS.HAMMERS if accepts(by, k, RS.HAMMERS[n])) or "none")


if __name__ == "__main__":
    main(sys.argv[1:])
