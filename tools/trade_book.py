#!/usr/bin/env python3
"""Trade book: every v3 trade with the candles and EMAs behind it, to check against the chart.
Usage: python3 tools/trade_book.py [live.db ...] > trade_book.txt"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import stop_study as S  # noqa: E402
from trader import rules_v3 as R  # noqa: E402
from trader.compare import VARIANTS, run_exit  # noqa: E402

T = []


def g(seq, k):
    try:
        return seq[k]
    except (KeyError, IndexError):
        return 0


def grab(label, index, ix_by, e10x, e20x, options, step, prev_close, rows):
    first = min(k for k in ix_by if k >= 0)
    for sig, by in S.candidates(ix_by, e10x, e20x, options, step, prev_close):
        o = options[sig["name"]]
        T.append(dict(day=label, index=index, sig=sig, by=by, e10=o[1], e20=o[2], ix=ix_by, ix10=e10x, ix20=e20x,
                      step=step, pc=prev_close, first_open=ix_by[first]["O"]))


def main(dbs):
    S.run_variants = grab
    S.main(dbs)
    T.sort(key=lambda t: (t["day"], t["index"]))
    for n, t in enumerate(T, 1):
        s, by, i = t["sig"], t["by"], t["sig"]["i"]
        strike, side = R.parse_strike(s["name"])
        gap = None if not t["pc"] else t["first_open"] / t["pc"] - 1
        print("=" * 100)
        print("TRADE %d  %s  %s  %s   signal candle %s  (entry = next candle %s open)" % (n, t["day"], t["index"], s["name"], R.tstr(i), R.tstr(i + 1)))
        print("-" * 100)
        d = R.index_direction(t["ix"][i]["C"], t["ix10"][i], t["ix20"][i])
        print("1 INDEX TREND: %s candle %s close %.2f | EMA10 %.2f EMA20 %.2f -> %s (option side %s)" % (
            t["index"], R.tstr(i), t["ix"][i]["C"], t["ix10"][i], t["ix20"][i], d, side))
        b = by[i]
        print("2 SIGNAL CANDLE: O %.2f H %.2f L %.2f C %.2f (green) | EMA10 %.2f EMA20 %.2f | close/EMA10 %.3f" % (
            b["O"], b["H"], b["L"], b["C"], t["e10"][i], t["e20"][i], b["C"] / t["e10"][i]))
        print("3 HAMMER candle: %s %s" % (R.tstr(s["hammer"]), "(the signal candle itself)" if s["hammer"] == i else "(the candle BEFORE the signal candle, signal candle confirms)"))
        print("4 TIME %s: %s" % (R.tstr(i), "midday block 10:35-13:00 NOT active" if not s["midday"] else "midday"))
        print("5 FILTERS: gap %s vs prev close %s (%s) | index at entry %.2f, strike %d -> %.2f steps (max 1.5)" % (
            "n/a" if gap is None else "%+.2f%%" % (100 * gap), "n/a" if not t["pc"] else "%.2f" % t["pc"],
            "no restriction" if gap is None or abs(gap) < R.GAP_TH else ("only CE" if gap > 0 else "only PE"),
            t["ix"].get(i + 1, t["ix"][i])["O"], strike, abs(t["ix"].get(i + 1, t["ix"][i])["O"] - strike) / t["step"]))
        print("6 ORDER: buy %.2f | stop %.2f (%s) | risk %.2f | 3R target %.2f" % (s["entry"], s["stop"], s["note"], s["R"], s["target"]))
        res = []
        for name, kw in VARIANTS:
            r = run_exit(by, i, s["entry"], s["stop"], **kw)
            res.append("%s %+.2fR@%s" % (name[0], r[0], R.tstr(r[1])))
        print("7 EXITS: " + " | ".join(res))
        print("   candle  time   | OPTION  open    high     low   close   EMA10   EMA20 | %s close  EMA10  EMA20" % t["index"])
        for k in range(max(0, i - 5), min(i + 14, 75)):
            if k not in by:
                continue
            x = by[k]
            mark = "<- signal" if k == i else ("<- ENTRY" if k == i + 1 else "")
            ixc = t["ix"].get(k)
            print("   %5d  %s | %8.2f %7.2f %7.2f %7.2f %7.2f %7.2f | %9.2f %7.2f %7.2f %s" % (
                k, R.tstr(k), x["O"], x["H"], x["L"], x["C"], t["e10"][k], t["e20"][k],
                ixc["C"] if ixc else 0, g(t["ix10"], k) if ixc else 0, g(t["ix20"], k) if ixc else 0, mark))
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
