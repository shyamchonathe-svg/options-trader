#!/usr/bin/env python3
"""Research map, readable version. python3.11 tools/draw_research.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from trader import research as RS

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "docs", "pics")
GREEN, YEL, BLUE = "#26a69a", "#fff3b0", "#0d47a1"

# ------------------------------------------------------------------ hammers
cols = [("Variant", 0.0, 3.6), ("Loosest candle\nit accepts", 3.6, 2.2), ("Body\n(of range)", 5.8, 1.9), ("Close in\ntop", 7.7, 1.6),
        ("Lower\nwick", 9.3, 1.6), ("Upper\nwick", 10.9, 1.6), ("Low touched EMA10\nwithin last", 12.5, 2.4), ("Size filter\n(range vs avg10)", 14.9, 2.2), ("Colour /\nred before", 17.1, 2.0)]
W = 19.1
base = RS.HAMMERS["H0 v3 (current)"]


def cells(p):
    if p["body"] == 0:
        return ["any", "any", "any", "any", "6 candles", "off", "green + red before"]
    body = ">= %d%%" % (p["body"] * 100) + (" , <= %d%%" % (p["bmax"] * 100) if "bmax" in p else "")
    return [body, "%d%%" % round((1 - p["clv"]) * 100), ">= %d%%" % (p["lw"] * 100),
            ("<= %d%%" % (p["uw"] * 100)) if "uw" in p else "free", "%d candles" % p["touch"],
            "range >= 1.0x" if p["size"] else "off", "ANY colour" if p.get("anycolor") else "green + red before"]


b0 = cells(base)
rows = list(RS.HAMMERS.items())
rh = 1.25
fig = plt.figure(figsize=(19, 1.6 + rh * len(rows) * 0.62 + 3.2)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.01, 0.02, 0.98, 0.90]); ax.axis("off")
ax.set_xlim(0, W); ax.set_ylim(-3.6, rh * len(rows) + 1.7)
fig.suptitle("HAMMER variants we tested   (yellow cell = differs from H0, today's rule)", fontsize=15, fontweight="bold", x=0.01, ha="left")
top = rh * len(rows)
for name, x, w in cols:
    ax.add_patch(Rectangle((x, top), w, 1.4, fc="#263238", ec="white"))
    ax.text(x + w / 2, top + 0.7, name, color="white", ha="center", va="center", fontsize=10, fontweight="bold")
for r, (name, p) in enumerate(rows):
    y = top - (r + 1) * rh
    c = cells(p)
    ax.add_patch(Rectangle((0, y), W, rh, fc="#fafafa" if r % 2 == 0 else "white", ec="#dddddd"))
    ax.text(0.15, y + rh / 2, name, fontsize=11.5, va="center", fontweight="bold")
    # icon (big)
    cx = 3.6 + 1.1; H = rh * 0.86; y0 = y + rh * 0.07
    if p["body"] == 0:
        ax.text(cx, y + rh / 2, "any candle", fontsize=10, ha="center", va="center", color="#777")
    else:
        lw = p["lw"]; bd = p["bmax"] if "bmax" in p else max(p["body"], p["clv"] - lw)
        col = "#9e9e9e" if p.get("anycolor") else GREEN
        ax.plot([cx, cx], [y0, y0 + H], color=col, lw=3)
        ax.add_patch(Rectangle((cx - .32, y0 + lw * H), .64, max(bd * H, 0.04), fc=col, ec=col))
        ax.annotate("", xy=(cx + .55, y0), xytext=(cx + .55, y0 + lw * H), arrowprops=dict(arrowstyle="<->", color="#c62828", lw=1.0))
    xs = [5.8, 7.7, 9.3, 10.9, 12.5, 14.9, 17.1]; ws = [1.9, 1.6, 1.6, 1.6, 2.4, 2.2, 2.0]
    for k in range(7):
        diff = c[k] != b0[k] and name != "H0 v3 (current)"
        if diff: ax.add_patch(Rectangle((xs[k] + .05, y + .06), ws[k] - .1, rh - .12, fc=YEL, ec="#f9a825"))
        ax.text(xs[k] + ws[k] / 2, y + rh / 2, c[k], ha="center", va="center", fontsize=10.5, fontweight="bold" if diff else "normal")
ax.text(0.1, -0.6, "Icon = the LOOSEST candle each rule accepts (red arrow = minimum lower wick).  Real hammers are inside these limits.", fontsize=10, color="#555")
ax.text(0.1, -1.4, "Grid search on top of these:  ~140 more combinations  (body 15/30 %, close-top 40/35/25 %, lower wick 15/25/40 %, low-touch 2/3/6 candles, size off/on)\n"
        "and the 'classic' family (lower wick 50/60 %, body max 35/50 %, upper wick 10/20 %, touch 3/6, size off/on).", fontsize=10, color=BLUE, va="top")
ax.text(0.1, -2.9, "Your labelled hammers (19-20 Nov, 28 of them) sit at:  body 40-60 %,  lower wick 30-60 %,  upper wick < ~12 %,  close in top 10-25 %,  range / avg10 median 1.4 (p20 0.98)  ->  closest to H1.", fontsize=10.5, color="#b00020", va="top")
fig.savefig(os.path.join(OUT, "research_hammers.png"), dpi=100); plt.close(fig)

# ------------------------------------------------------------------ inside
INS = list(RS.INSIDE.items())
cols = [("Variant", 0.0, 6.0), ("Index chart\nmust agree", 6.0, 2.4), ("Trend age\n(from EMA cross)", 8.4, 2.6), ("Stop", 11.0, 2.6), ("Big candle\nrange", 13.6, 2.2)]
W = 15.8
base = RS.INSIDE[INS[0][0]]


def icells(p):
    return ["yes (size >= 1.0x)" if p["index"] and p["ibig"] else ("yes (any size)" if p["index"] else "no"),
            "<= %d candles" % p["fresh"] if p["fresh"] < 999 else "any time",
            "low of inside candle" if p["stop"] == "inside" else "low of BIG candle", ">= %.1fx avg10" % p["big"]]


b0 = icells(base)
fig = plt.figure(figsize=(17, 8.5)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.01, 0.02, 0.62, 0.88]); ax.axis("off"); ax.set_xlim(0, W); ax.set_ylim(-1.8, 1.0 * len(INS) * 1.2 + 1.8)
fig.suptitle("INSIDE-candle variants   (yellow = differs from I1)", fontsize=15, fontweight="bold", x=0.01, ha="left")
rh = 1.2; top = rh * len(INS)
for name, x, w in cols:
    ax.add_patch(Rectangle((x, top), w, 1.5, fc="#263238", ec="white"))
    ax.text(x + w / 2, top + 0.75, name, color="white", ha="center", va="center", fontsize=10, fontweight="bold")
xs = [6.0, 8.4, 11.0, 13.6]; ws = [2.4, 2.6, 2.6, 2.2]
for r, (name, p) in enumerate(INS):
    y = top - (r + 1) * rh
    c = icells(p)
    ax.add_patch(Rectangle((0, y), W, rh, fc="#fafafa" if r % 2 == 0 else "white", ec="#dddddd"))
    ax.text(0.15, y + rh / 2, name, fontsize=10.5, va="center", fontweight="bold")
    for k in range(4):
        diff = c[k] != b0[k] and r > 0
        if diff: ax.add_patch(Rectangle((xs[k] + .05, y + .06), ws[k] - .1, rh - .12, fc=YEL, ec="#f9a825"))
        ax.text(xs[k] + ws[k] / 2, y + rh / 2, c[k], ha="center", va="center", fontsize=10, fontweight="bold" if diff else "normal")
ax.text(0.1, -0.5, "Grid on top: ~144 combos (big candle 1.2/1.5/2.0x, inside size 40/60/80 %, trend age 3/6/12/any, option vs option+index, stop inside vs big).", fontsize=9.5, color=BLUE)
# pattern diagram
ix = fig.add_axes([0.66, 0.15, 0.32, 0.70]); ix.set_xlim(-1, 6); ix.set_ylim(0, 13); ix.axis("off")
ix.set_title("The pattern", loc="left", fontsize=12.5, fontweight="bold")
ix.add_patch(Rectangle((0.7, 2), 0.7, 8, fc=GREEN, ec=GREEN)); ix.plot([1.05, 1.05], [1.5, 10.5], color=GREEN, lw=2)
ix.add_patch(Rectangle((2.0, 5.2), 0.7, 1.8, fc="#ef5350", ec="#ef5350")); ix.plot([2.35, 2.35], [4.7, 7.6], color="#ef5350", lw=2)
ix.add_patch(Rectangle((3.3, 6.1), 0.7, 5.2, fc=GREEN, ec=GREEN)); ix.plot([3.65, 3.65], [5.8, 11.9], color=GREEN, lw=2)
ix.text(1.05, 0.2, "k: BIG green\nbody >= 50 % of range\nrange >= 1.2-2.0 x avg10", ha="center", fontsize=9)
ix.text(2.35, 8.3, "k+1 sits INSIDE k\n(range <= 40-80 % of k)", ha="center", fontsize=9)
ix.text(3.9, 0.2, "k+2 breaks above the\nhigh of k+1 -> ENTER", ha="center", fontsize=9, color=BLUE)
ix.plot([0.2, 4.6], [5.2, 5.2], ls="--", color="#c62828", lw=1.2); ix.text(4.6, 4.7, "SL: low of k+1\n(or low of k)", fontsize=9, color="#c62828", ha="right", va="top")
fig.savefig(os.path.join(OUT, "research_inside.png"), dpi=100); plt.close(fig)
print("done")
