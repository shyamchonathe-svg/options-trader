#!/usr/bin/env python3
"""Does the gap-direction filter help? python3 tools/gap_study.py [trader.db ...]
Runs the named hammer setups with the gap filter OFF and splits the signals into: allowed by the gap rule vs blocked by it.
Same 3R / 12-candle exit, ATM filter on, midday split shown. Research days + any live DBs given."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from trader import research as RS  # noqa: E402
import research_run as RR  # noqa: E402


def line(name, x):
    n, w, a, t = RR.stats(x)
    return "%-44s n=%4d  win%%=%3.0f  avgR=%6.2f  sumR=%7.1f" % (name, n, w, a, t)


def main(dbs):
    H = {"H0 v3 hammer": RS.HAMMERS["H0 v3 hammer"]} if "H0 v3 hammer" in RS.HAMMERS else dict(list(RS.HAMMERS.items())[:1])
    rows = []
    for c in RR.fixture_cases():
        for r in RS.run_case(c, hammers=H, insides={}, use_gap=False): r["src"] = "research"; rows.append(r)
    for p in dbs:
        for c in RR.db_cases(p):
            for r in RS.run_case(c, hammers=H, insides={}, use_gap=False): r["src"] = "live"; rows.append(r)
    print("setup used:", list(H))
    for src in ("research", "live", None):
        sel = [r for r in rows if src is None or r["src"] == src]
        if not sel: continue
        print("\n== %s days ==" % (src or "ALL"))
        al = [r for r in sel if not r["gap_blocked"]]; bl = [r for r in sel if r["gap_blocked"]]
        print(line("allowed by gap rule", al)); print(line("BLOCKED by gap rule", bl))
        print(line("  blocked, outside midday", [r for r in bl if not r["midday"]]))
        print(line("  allowed, outside midday", [r for r in al if not r["midday"]]))
        big = [r for r in bl if abs(r["gap"]) >= 0.005]
        print(line("  blocked on big gaps (>=0.5%)", big))
        print(line("  blocked on small gaps (0.25-0.5%)", [r for r in bl if abs(r["gap"]) < 0.005]))
    print("\nBlocked days (day index gap):")
    seen = set()
    for r in rows:
        k = (r["day"], r["index"])
        if r["gap_blocked"] and k not in seen:
            seen.add(k); print(" ", r["day"], r["index"], "%.2f%%" % (100 * r["gap"]), r["src"])


if __name__ == "__main__":
    main(sys.argv[1:])
