#!/usr/bin/env python3
"""Floating-candle distance: real option hammers whose whole candle sits above both EMAs, sorted by distance.
python3.11 tools/draw_floating.py"""
import os, sys, sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
from trader import research as RS
import hammer_labels as HL
OUT = os.path.join(HERE, "..", "docs", "pics")
GREEN, RED, BLUE, E10, E20 = "#26a69a", "#ef5350", "#0d47a1", "#f08a24", "#2e9e4f"

def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o

P = dict(RS.HAMMERS["H1 v3 + min size"], touch=1, tol=100.0, size=0)   # shape only; touch test bypassed
cand = []
for f in ("trader_2026-11-20.db", "trader_2026-11-23.db"):
    db = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "..", "..", "data", "live_vm", f), uri=True)
    for day, in db.execute("select distinct day from bars").fetchall():
        for sym, in db.execute("select distinct symbol from bars where day=?", (day,)).fetchall():
            if not (sym.endswith("CE") or sym.endswith("PE")): continue
            by = HL.load(db, day, sym); ks = sorted(by)
            if len(ks) < 20: continue
            cl = [by[i]["C"] for i in ks]
            e10 = dict(zip(ks, ema(cl, 10))); e20 = dict(zip(ks, ema(cl, 20)))
            for k in ks:
                if k < 12 or k > 66 or k - 1 not in by: continue
                if not RS.hammer_ok(by, e10, k, P): continue
                b = by[k]
                if not (e10[k] > e20[k] and b["L"] > e10[k] and b["L"] > e20[k]): continue   # whole candle above both EMAs
                av = RS._avg_range(by, k, spike=2.0)
                if av <= 0: continue
                cand.append((round((b["L"] - e10[k]) / av, 2), 100.0 * (b["L"] - e10[k]) / e10[k], day, sym, k, by, e10, e20))
cand=[c for c in cand if c[0]<=8]
cand.sort(key=lambda x: x[0])
# dedupe near-identical gaps, spread over the range
pick = []
for c in cand:
    if not pick or c[0] - pick[-1][0] >= 0.12: pick.append(c)
if len(pick) > 18:
    pick = [pick[int(i * (len(pick) - 1) / 17.0)] for i in range(18)]
print(len(cand), "candidates,", len(pick), "shown; gaps", [p[0] for p in pick])
cols = 6; rows = (len(pick) + cols - 1) // cols
fig, axs = plt.subplots(rows, cols, figsize=(19, 3.7 * rows)); fig.patch.set_facecolor("white")
fig.suptitle("FLOATING: real hammers, whole candle above both EMAs, sorted by distance.  Gap = (candle low - EMA10) / average candle size.  Where does 'floating' start?",
             fontsize=12, fontweight="bold", x=0.01, ha="left")
for a in axs.ravel(): a.axis("off")
for a, (g, pct, day, sym, k, by, e10, e20) in zip(axs.ravel(), pick):
    ks = sorted(by); sel = [i for i in ks if k - 8 <= i <= k + 2]
    for n, i in enumerate(sel):
        b = by[i]; col = GREEN if b["C"] >= b["O"] else RED
        a.plot([n, n], [b["L"], b["H"]], color=col, lw=1.3, zorder=2)
        a.add_patch(Rectangle((n - .3, min(b["O"], b["C"])), .6, max(abs(b["C"] - b["O"]), (b["H"] - b["L"]) * .01), fc=col, ec=col, zorder=3))
    xs = list(range(len(sel)))
    a.plot(xs, [e20[i] for i in sel], color=E20, lw=1.5); a.plot(xs, [e10[i] for i in sel], color=E10, lw=1.5)
    n0 = sel.index(k); b = by[k]
    a.add_patch(Rectangle((n0 - .55, b["L"]), 1.1, b["H"] - b["L"], fc="none", ec=BLUE, lw=1.8, zorder=4))
    ymin = min(by[i]["L"] for i in sel); ymax = max(by[i]["H"] for i in sel); pad = (ymax - ymin) * .08
    a.set_ylim(ymin - pad, ymax + pad); a.set_xlim(-.8, len(sel) - .2); a.axis("on"); a.set_xticks([]); a.set_yticks([])
    for s in a.spines.values(): s.set_color("#cccccc")
    a.set_title("gap %.2f   (%.1f%% above EMA10)\n%s %s  %s" % (g, pct, day[5:], RS.R.tstr(k) if hasattr(RS, "R") else "", sym[-9:]), fontsize=9.5, color=BLUE, fontweight="bold")
fig.subplots_adjust(left=.01, right=.99, top=.86, bottom=.02, hspace=.5, wspace=.08)
p = os.path.join(OUT, "research_floating_distance.png"); fig.savefig(p, dpi=75); print(p)
