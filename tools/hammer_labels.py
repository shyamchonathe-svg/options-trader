#!/usr/bin/env python3
"""Score hammer formulas against hand-labelled candles.  Read-only.  Python 3.6+.
  python3 tools/hammer_labels.py DB DAY research_labels/<day>.txt
Labelled candles = positives; every other candle of the same symbols = negatives (an approximation: an unlabelled candle
may still be a fine hammer).  Shape only (body, close position, wicks, colour); EMA conditions are ignored on purpose.
Prints each labelled candle's numbers, recall/false-matches for every named formula, and the best simple shape rules found
by a small search.  With ~25 labels this is a guide, not proof."""
import itertools, os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from trader import research as RS


def read_labels(path):
    out = []
    for line in open(path):
        line = line.split("#")[0].rstrip()
        if not line.strip(): continue
        parts = line.split()
        times = [p for p in parts if len(p) == 5 and p[2] == ":"]
        sym = " ".join(p for p in parts if p not in times)
        out.append((sym, times))
    return out


def load(db, day, sym):
    by = {}
    for s, o, h, l, c, src in db.execute(
            "select slot,o,h,l,c,src from bars where day=? and symbol=? and src in ('live','exact','backfill') order by slot, src='exact'", (day, sym)):
        by[s] = {"O": o, "H": h, "L": l, "C": c}
    return by


def feat(b):
    r = b["H"] - b["L"]
    if r <= 0: return None
    top, bot = max(b["O"], b["C"]), min(b["O"], b["C"])
    return dict(body=(top - bot) / r, clv=(b["C"] - b["L"]) / r, lw=(bot - b["L"]) / r, uw=(b["H"] - top) / r, green=b["C"] > b["O"])


def ok(f, p):
    return (f is not None and f["body"] >= p.get("body", 0) and f["body"] <= p.get("bmax", 1) and f["clv"] >= p["clv"]
            and f["lw"] >= p["lw"] and f["uw"] <= p.get("uw", 1) and (p.get("anycolor") or f["green"]))


def main(a):
    db = sqlite3.connect("file:%s?mode=ro" % a[0], uri=True)
    day, labels = a[1], read_labels(a[2])
    pos, neg = [], []
    print("LABELLED CANDLES")
    for sym, times in labels:
        by = load(db, day, sym)
        if not by: print("  !! no bars for", sym); continue
        want = set()
        for t in times:
            hh, mm = t.split(":"); want.add((int(hh) * 60 + int(mm) - 555) // 5)
        for k in sorted(by):
            f = feat(by[k])
            if f is None: continue
            (pos if k in want else neg).append((sym, k, f))
            if k in want:
                print("  %-24s %s  body %3.0f%%  close-pos %.2f  lower-wick %3.0f%%  upper-wick %3.0f%%  %s" % (
                    sym, RS.R.tstr(k), f["body"] * 100, f["clv"], f["lw"] * 100, f["uw"] * 100, "green" if f["green"] else "red"))
    print("\n%d labelled hammers, %d other candles on the same charts" % (len(pos), len(neg)))
    print("\nNAMED FORMULAS (shape only)      caught   of    false matches")
    for name, p in RS.HAMMERS.items():
        if name.startswith("H6"): continue
        tp = sum(1 for _, _, f in pos if ok(f, p)); fp = sum(1 for _, _, f in neg if ok(f, p))
        print("  %-30s %5d  %5d  %8d" % (name, tp, len(pos), fp))
    res = []
    for lw, bmax, uw, clv in itertools.product((.30, .35, .40, .45, .50, .55, .60), (.25, .30, .35, .40, .50, .60), (.05, .10, .15, .20, .30, 1.0), (.55, .65, .75)):
        p = dict(body=.05, bmax=bmax, clv=clv, lw=lw, uw=uw, anycolor=True)
        tp = sum(1 for _, _, f in pos if ok(f, p)); fp = sum(1 for _, _, f in neg if ok(f, p))
        if not tp: continue
        prec, rec = tp / float(tp + fp), tp / float(len(pos))
        res.append((2 * prec * rec / (prec + rec), tp, fp, p))
    res.sort(key=lambda r: (-r[0], r[2]))
    print("\nBEST SIMPLE SHAPES (any colour; tie-break fewer false matches)")
    print("  F1   caught false  lower-wick>=  body<=  upper-wick<=  close-pos>=")
    for f1, tp, fp, p in res[:8]:
        print("  %.2f  %3d   %4d     %3.0f%%         %3.0f%%    %4s%%         %.2f" % (f1, tp, fp, p["lw"] * 100, p["bmax"] * 100, int(p["uw"] * 100) if p["uw"] < 1 else "any", p["clv"]))
    miss = [(s, k, f) for s, k, f in pos if not ok(f, res[0][3])] if res else []
    if miss:
        print("\nLabelled candles the top rule still misses:")
        for s, k, f in miss: print("  %-24s %s body %.0f%% clv %.2f lw %.0f%% uw %.0f%%" % (s, RS.R.tstr(k), f["body"] * 100, f["clv"], f["lw"] * 100, f["uw"] * 100))


if __name__ == "__main__":
    main(sys.argv[1:])
