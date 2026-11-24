#!/usr/bin/env python3
"""Gallery of the candles the user labelled as proper hammers (real data). python3.11 tools/draw_labelled.py [outdir]"""
import os, sys, sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
from trader import research as RS
import hammer_labels as HL

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "docs", "pics")
DB = os.path.join(HERE, "..", "..", "data", "live_vm", "trader_2026-11-20.db")
GREEN, RED, BLUE, E10, E20 = "#26a69a", "#ef5350", "#0d47a1", "#f08a24", "#2e9e4f"


def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
items = []
for day in ("2026-11-19", "2026-11-20"):
    for sym, times in HL.read_labels(os.path.join(HERE, "..", "research_labels", day + ".txt")):
        by = HL.load(db, day, sym)
        if not by: continue
        for t in times:
            hh, mm = t.split(":"); k = (int(hh) * 60 + int(mm) - 555) // 5
            if k in by: items.append((day, sym, t, k, by))
print(len(items), "labelled candles found")
short = {"H0 v3 (current)": "H0", "H1 v3 + min size": "H1", "H2 touch EMA10 now": "H2", "H3 long wick (40%)": "H3", "H4 small hammer": "H4", "H5 strict": "H5",
         "H7 classic hammer": "H7", "H8 classic, any colour": "H8", "H9 classic (wick 40%)": "H9"}
cols = 6; rows = (len(items) + cols - 1) // cols
fig, axs = plt.subplots(rows, cols, figsize=(19, 3.3 * rows)); fig.patch.set_facecolor("white")
fig.suptitle("The %d candles YOU labelled as proper hammers (real data, 19-20 Nov).  Blue box = the labelled candle; orange EMA10, green EMA20" % len(items), fontsize=14, fontweight="bold", x=0.01, ha="left")
for a in axs.ravel(): a.axis("off")
for a, (day, sym, t, k, by) in zip(axs.ravel(), items):
    ks = sorted(by); cl = [by[i]["C"] for i in ks]
    e10 = dict(zip(ks, ema(cl, 10))); e20 = dict(zip(ks, ema(cl, 20)))
    lo, hi = k - 6, k + 3
    sel = [i for i in ks if lo <= i <= hi]
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
    f = HL.feat(b); r = b["H"] - b["L"]
    prev = [by[i]["H"] - by[i]["L"] for i in ks if k - 10 <= i < k]
    sz = r / (sum(prev) / len(prev)) if prev and sum(prev) > 0 else 0
    caught = [short[nm] for nm, p in RS.HAMMERS.items() if nm in short and HL.ok(f, p)]
    nm = sym.replace("BFO:SENSEX26", "SX ").replace("NFO:NIFTY26", "NF ").replace("NSE:NIFTY 50", "NIFTY idx").replace("BSE:SENSEX", "SENSEX idx")
    a.set_title("%s %s  %s" % (day[5:], t, nm), fontsize=9.5, loc="left", fontweight="bold")
    a.set_xlabel("body %d%%  wick %d%%  upper %d%%  size %.1fx\nshape rules that accept it: %s" % (f["body"] * 100, f["lw"] * 100, f["uw"] * 100, sz, " ".join(caught) or "none"), fontsize=8.5)
    a.xaxis.set_label_position("bottom")
plt.subplots_adjust(hspace=0.55, wspace=0.12, top=0.93, bottom=0.05, left=0.01, right=0.99)
fig.savefig(os.path.join(OUT, "labelled_hammers_gallery.png"), dpi=90); plt.close(fig)
print("done")
