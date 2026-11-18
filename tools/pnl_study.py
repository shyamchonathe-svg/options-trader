#!/usr/bin/env python3
"""P&L of every known v3 trade under each exit plan, in rupees with the fixed-capital sizing (Rs 1,00,000 per index, 90% used,
whole lots, no compounding, brokerage/taxes NOT included). Same entries/stops as v3. Usage: python3 tools/pnl_study.py [live.db ...]"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import stop_study as S  # noqa: E402
from trader import rules_v3 as R  # noqa: E402
from trader.compare import VARIANTS, run_exit  # noqa: E402

CAP, USE = 100000.0, 0.9


def collect(dbs):
    """Reuse stop_study's data loading, but keep candidates (v3 stop) instead of stop variants."""
    trades = []
    orig = S.run_variants

    def grab(label, index, ix_by, e10x, e20x, options, step, prev_close, rows):
        for sig, by in S.candidates(ix_by, e10x, e20x, options, step, prev_close):
            trades.append({"day": label, "index": index, "opt": sig["name"], "t": sig["t"], "i": sig["i"],
                           "entry": sig["entry"], "stop": sig["stop"], "by": by})
    S.run_variants = grab
    try:
        S.main(dbs)
    finally:
        S.run_variants = orig
    return sorted(trades, key=lambda t: (t["day"], t["index"]))


def main(dbs):
    trades = collect(dbs)
    names = [n for n, _ in VARIANTS]
    print("Capital Rs 1,00,000 per index, 90%% used (Rs 90,000), whole lots (Nifty 65, Sensex 20). %d trades.\n" % len(trades))
    hdr = "%-10s %-6s %-14s %-5s %8s %6s %5s" % ("day", "index", "option", "time", "entry", "risk", "qty")
    print(hdr + "".join("  %10s" % n[0] for n in names))
    tot = [dict(NIFTY=0.0, SENSEX=0.0) for _ in names]
    rs = [[] for _ in names]
    for t in trades:
        lot = S.LOT[t["index"]]
        qty = int(CAP * USE // (t["entry"] * lot)) * lot
        risk = t["entry"] - t["stop"]
        cells = []
        for k, (_, kw) in enumerate(VARIANTS):
            r = run_exit(t["by"], t["i"], t["entry"], t["stop"], **kw)
            pnl = qty * r[0] * risk
            tot[k][t["index"]] += pnl
            rs[k].append(r[0])
            cells.append("%+10.0f" % pnl)
        print("%-10s %-6s %-14s %-5s %8.2f %6.2f %5d" % (t["day"], t["index"], t["opt"], t["t"], t["entry"], risk, qty) + "".join("  " + c for c in cells))
    print()
    print("%-52s %5s %7s %9s %11s %11s %11s" % ("exit plan", "win%", "total R", "wins/n", "Nifty Rs", "Sensex Rs", "TOTAL Rs"))
    n = len(trades)
    for k, nm in enumerate(names):
        w = len([x for x in rs[k] if x > 0])
        a, b = tot[k]["NIFTY"], tot[k]["SENSEX"]
        print("%-52s %4.0f%% %+7.2f %4d/%-4d %+11.0f %+11.0f %+11.0f" % (nm, 100.0 * w / n, sum(rs[k]), w, n, a, b, a + b))
    print("\nEnding capital (start Rs 2,00,000 across both indices, no compounding):")
    for k, nm in enumerate(names):
        print("  %-52s Rs %s" % (nm, "{:,.0f}".format(200000 + tot[k]["NIFTY"] + tot[k]["SENSEX"])))


if __name__ == "__main__":
    main(sys.argv[1:])
