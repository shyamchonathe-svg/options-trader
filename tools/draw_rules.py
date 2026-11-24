#!/usr/bin/env python3
"""Pictures of the trading rules (illustrative, invented candles). python3.11 tools/draw_rules.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pics")
os.makedirs(OUT, exist_ok=True)
GREEN, RED, BG = "#26a69a", "#ef5350", "#fafafa"


def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


def mk(spec):
    """spec: (open, close, lower_wick, upper_wick) -> (O,H,L,C)"""
    out = []
    for o, c, lw, uw in spec:
        out.append((o, max(o, c) + uw, min(o, c) - lw, c))
    return out


def candles(ax, bars, x0=0, w=0.6):
    for i, (o, h, l, c) in enumerate(bars):
        x = x0 + i; col = GREEN if c >= o else RED
        ax.plot([x, x], [l, h], color=col, lw=1.3, zorder=2)
        ax.add_patch(Rectangle((x - w / 2, min(o, c)), w, max(abs(c - o), 0.05), fc=col, ec=col, zorder=3))


def chart(ax, bars, title, e10=None, e20=None):
    cl = [b[3] for b in bars]
    candles(ax, bars)
    e10 = e10 or ema(cl, 3)
    e20 = e20 or ema(cl, 6)
    ax.plot(range(len(bars)), e20, color="#2e9e4f", lw=1.6, label="EMA20")
    ax.plot(range(len(bars)), e10, color="#f08a24", lw=1.6, label="EMA10")
    ax.set_title(title, fontsize=10.5, loc="left", fontweight="bold")
    ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#cccccc")
    return e10, e20


def note(ax, xy, text, xytext, color="#222", fs=9, arrow=True):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=fs, color=color, ha="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color, lw=0.8),
                arrowprops=dict(arrowstyle="->", color=color, lw=1.0) if arrow else None, zorder=10)


# =====================================================================================  1. hammer anatomy + triggers
fig = plt.figure(figsize=(15, 8.2)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.03, 0.08, 0.30, 0.82]); ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
ax.set_title("1. What counts as a HAMMER (shape + size)", loc="left", fontsize=13, fontweight="bold")
# big annotated hammer
x, lo, hi, o, c = 2.2, 1.0, 9.0, 5.6, 7.9
ax.plot([x, x], [lo, hi], color=GREEN, lw=3); ax.add_patch(Rectangle((x - .7, o), 1.4, c - o, fc=GREEN, ec=GREEN))
ax.annotate("", xy=(4.0, lo), xytext=(4.0, o), arrowprops=dict(arrowstyle="<->", color="#444"))
ax.text(4.2, (lo + o) / 2, "lower wick\n30 - 60 % of range", fontsize=10, va="center")
ax.annotate("", xy=(4.0, o), xytext=(4.0, c), arrowprops=dict(arrowstyle="<->", color="#444"))
ax.text(4.2, (o + c) / 2, "body 40 - 60 %\n(green; red allowed\nonly as the 1st hammer\nof a pair)", fontsize=10, va="center")
ax.annotate("", xy=(4.0, c), xytext=(4.0, hi), arrowprops=dict(arrowstyle="<->", color="#444"))
ax.text(4.2, (c + hi) / 2 + .1, "upper wick: tiny (< ~12 %)", fontsize=10, va="center")
ax.text(.2, .1, "Close in the top 10-25 % of the range.", fontsize=10)
ax.text(.2, -.5, "SIZE: range >= ~1.0 x the average range\nof the last 10 candles (median of your\nlabelled hammers = 1.4 x). Tiny ones are noise.", fontsize=10, color="#b00020")
# size compare
for k, (xx, rng, ok) in enumerate(((7.2, 3.0, True), (8.7, 0.9, False))):
    ax.plot([xx, xx], [1, 1 + rng], color=GREEN if ok else "#999", lw=3)
    ax.add_patch(Rectangle((xx - .3, 1 + rng * .55), .6, rng * .4, fc=GREEN if ok else "#999", ec="none"))
    ax.text(xx, 1 + rng + .35, "OK" if ok else "too small", ha="center", fontsize=9, color="#2e7d32" if ok else "#b00020")
ax.text(7.9, 5.4, "same shape,\ndifferent size", ha="center", fontsize=9, color="#555")

# trigger patterns
ax2 = fig.add_axes([0.36, 0.08, 0.62, 0.82]); ax2.axis("off"); ax2.set_xlim(0, 30); ax2.set_ylim(0, 22)
ax2.set_title("2. The TRIGGER = two hammers (or hammer + green), then ENTER at the next open", loc="left", fontsize=13, fontweight="bold")
H = lambda x0, g=True, s=1.0: (x0, g, s)


def hammer(a, x, base, g=True, s=1.0, lab=None):
    col = GREEN if g else RED
    top = base + 3.0 * s
    a.plot([x, x], [base, base + 4.0 * s], color=col, lw=2)
    o, c = (base + 1.8 * s, base + 3.6 * s) if g else (base + 3.6 * s, base + 2.0 * s)
    a.add_patch(Rectangle((x - .35, min(o, c)), .7, abs(c - o), fc=col, ec=col))
    if lab: a.text(x, base - .8, lab, ha="center", fontsize=9)


def small(a, x, base, g=True, h=1.2):
    col = GREEN if g else RED
    a.plot([x, x], [base - .3, base + h + .3], color=col, lw=1.5)
    a.add_patch(Rectangle((x - .35, base), .7, h, fc=col, ec=col))


def panel(y0, title, items, entry_x, sl_y, extra=None):
    ax2.text(0.2, y0 + 5.7, title, fontsize=10.5, fontweight="bold")
    for it in items: it()
    ax2.annotate("ENTRY\n(open of next\ncandle)", xy=(entry_x, y0 + 3.2), xytext=(entry_x + 3.6, y0 + 4.2), fontsize=9, color="#0d47a1",
                 arrowprops=dict(arrowstyle="->", color="#0d47a1"), ha="center")
    ax2.plot([entry_x - 5.5, entry_x + 1.2], [sl_y, sl_y], ls="--", color=RED, lw=1.3)
    ax2.text(entry_x - 5.4, sl_y - .6, "SL = low of 1st hammer", fontsize=8, color=RED, va="top")


# A: G,G consecutive
panel(14.5, "A.  Back to back: G,G  or  R,G",
      [lambda: hammer(ax2, 2, 14.8, True, 1, "hammer 1"), lambda: hammer(ax2, 4, 15.2, True, 1, "hammer 2"),
       lambda: hammer(ax2, 8, 14.8, False, 1, "red hammer 1"), lambda: hammer(ax2, 10, 15.2, True, 1, "green hammer 2"),
       lambda: ax2.text(6, 18.2, "or", fontsize=10, ha="center")], 5.7, 14.8)
ax2.annotate("", xy=(11.0, 17.0), xytext=(11.0, 17.0))
# B: hammers up to 3 candles apart
ax2.text(15.2, 20.2, "B.  <= 3 candles apart", fontsize=10.5, fontweight="bold")
hammer(ax2, 16, 14.8, True, 1, "hammer 1")
for k, (xx, g) in enumerate(((17, False), (18, True))): small(ax2, xx, 17.0 - 0.3 * k, g, 1.0)
hammer(ax2, 19, 15.2, True, 1, "hammer 2 (3 candles later)")
ax2.annotate("ENTRY (next open)", xy=(20.2, 17.8), xytext=(24.5, 19.2), fontsize=9, color="#0d47a1", arrowprops=dict(arrowstyle="->", color="#0d47a1"), ha="center")
ax2.plot([14.5, 21.5], [14.8, 14.8], ls="--", color=RED, lw=1.3); ax2.text(14.6, 14.2, "SL = low of 1st hammer", fontsize=8, color=RED, va="top")
# C: hammer + green
panel(4.5, "C.  Hammer + proper green candle",
      [lambda: hammer(ax2, 3, 4.8, True, 1, "hammer"),
       lambda: ax2.add_patch(Rectangle((4.65, 6.4), .7, 3.0, fc=GREEN, ec=GREEN)),
       lambda: ax2.plot([5, 5], [6.2, 9.7], color=GREEN, lw=1.5),
       lambda: ax2.text(5, 4.0, "decent green", ha="center", fontsize=9)], 6.4, 4.8)
ax2.text(15.2, 9.8, "All triggers need the context from picture 2:", fontsize=10.5, fontweight="bold")
ax2.text(15.2, 8.2, "-  option chart: EMA10 above EMA20 (for a CE;\n    mirror image for a PE - we always buy the option,\n    so the option chart always looks like a 'buy')\n-  at least one of the last 6 candle LOWS touched EMA10\n-  index trend agrees (index chart EMA10 > EMA20 for CE)\n-  hammers size ok (>= ~1.0 x average range)", fontsize=10, va="top")
fig.savefig(os.path.join(OUT, "rules_1_hammer_and_trigger.png"), dpi=110, bbox_inches="tight"); plt.close(fig)

# =====================================================================================  2. context scenarios on an option chart
fig, axs = plt.subplots(2, 2, figsize=(15, 9.4)); fig.patch.set_facecolor("white")

# A: deep pullback, EMAs crossed down then up again, double hammer
specA = [(100, 103, 0.6, 0.4), (103, 106, 0.5, 0.4), (106, 110, 0.5, 0.5), (110, 113, 0.5, 0.4), (113, 116, 0.5, 0.5), (116, 118, 0.6, 0.6),
         (118, 113, 0.4, 0.5), (113, 108, 0.4, 0.4), (108, 103, 0.4, 0.4), (103, 100, 0.4, 0.4), (100, 105, 0.6, 0.4),
         (105, 110, 0.5, 0.4), (110, 108, 0.6, 0.5), (108, 111.5, 4.8, 0.6), (111.5, 110.5, 0.5, 0.5), (110.5, 114, 5.0, 0.5),
         (114.5, 119, 0.5, 0.5), (119, 123, 0.5, 0.5)]
bars = mk(specA)
ax = axs[0][0]
e10, e20 = chart(ax, bars, "A. DEEP pullback: EMAs cross down, then up\n-> double hammer = TRADE")
ax.set_ylim(94, 128)
ax.annotate("", xy=(8.6, 112), xytext=(8.6, 112))
note(ax, (8.7, e20[8]), "EMA10 crosses BELOW EMA20\n(pullback was deep)", (5.0, 124.5), "#b26a00")
note(ax, (11.5, (e10[11] + e20[11]) / 2), "EMA10 back ABOVE EMA20\n(trend is back)", (9.0, 99.0), "#2e7d32")
note(ax, (13, bars[13][2]), "hammer 1", (12.0, 96.0), "#0d47a1")
note(ax, (15, bars[15][2]), "hammer 2", (15.6, 96.0), "#0d47a1")
ax.annotate("ENTRY\n(open of next candle)", xy=(16, bars[16][0]), xytext=(15.0, 108), fontsize=9, color="#0d47a1", ha="center", bbox=dict(boxstyle="round", fc="white", ec="#0d47a1"), arrowprops=dict(arrowstyle="->", color="#0d47a1"))
ax.axhline(bars[13][2], xmin=0.66, xmax=1, color=RED, ls="--", lw=1.4)
ax.text(17.4, bars[13][2] + .5, "SL = low\nof hammer 1", color=RED, fontsize=9, ha="right")


# B: mild pullback / sideways
specB = [(100, 104, .5, .4), (104, 108, .5, .5), (108, 111, .5, .4), (111, 114, .5, .5), (114, 117, .5, .5), (117, 119, .4, .5),
         (119, 118, .4, .5), (118, 118.8, .5, .5), (118.8, 117.6, .5, .5), (117.6, 118.6, .5, .5), (118.6, 117.8, .5, .5), (117.8, 118.5, .4, .4),
         (118.5, 120.6, 4.6, .5), (120.6, 119.8, .5, .4), (119.8, 122.5, 4.8, .5), (123, 127, .5, .5), (127, 130, .5, .5)]
bars = mk(specB)
ax = axs[0][1]
e10, e20 = chart(ax, bars, "B. MILD pullback: sideways pause, no cross\n-> double hammer = TRADE")
ax.set_ylim(94, 134)
note(ax, (9, e10[9]), "EMAs never crossed;\nprice just drifts sideways\nclose to EMA10", (6.5, 105), "#2e7d32")
note(ax, (12, bars[12][2]), "hammer 1", (10.2, 98.5), "#0d47a1")
note(ax, (14, bars[14][2]), "hammer 2", (14.2, 98.5), "#0d47a1")
ax.annotate("ENTRY", xy=(15, bars[15][0]), xytext=(15.5, 108), fontsize=9, color="#0d47a1", ha="center", bbox=dict(boxstyle="round", fc="white", ec="#0d47a1"), arrowprops=dict(arrowstyle="->", color="#0d47a1"))
ax.axhline(bars[12][2], xmin=0.60, xmax=1, color=RED, ls="--", lw=1.4); ax.text(16.4, bars[12][2] + .6, "SL = low of hammer 1", color=RED, fontsize=9, ha="right")
ax.text(0.2, 131, "Same test in both A and B: one of the last 6 candle lows touched EMA10 (the orange line).", fontsize=8.5, color="#666")

# C: NOT a trade - late in the trend, candles far from EMAs
specC = [(100, 104, .5, .4), (104, 108, .5, .5), (108, 112, .5, .4), (112, 117, .5, .5), (117, 122, .5, .5), (122, 127, .5, .5), (127, 132, .5, .5),
         (132, 137, .5, .5), (137, 142, .5, .5), (142, 147, .5, .5), (147, 152, .5, .5), (152, 155, 4.0, .5), (155, 159, .5, .5), (159, 162.5, 4.4, .6), (163, 166, .5, .5)]
bars = mk(specC)
ax = axs[1][0]
e10, e20 = chart(ax, bars, "C. NOT a trade: hammers at the END of a run\n(no low near EMA10 in last 6 candles)")
ax.set_ylim(96, 176)
for xk in (11, 13):
    note(ax, (xk, bars[xk][2]), "hammer", (xk - 3.5, 170 - (xk - 11) * 4), "#b71c1c")
ax.annotate("", xy=(11.0, e10[11]), xytext=(11.0, bars[11][2]), arrowprops=dict(arrowstyle="<->", color="#b71c1c"))
ax.text(7.0, 120, "gap between candle lows and EMA10:\nthe option is stretched, no pullback\n= REJECT", fontsize=9.5, color="#b71c1c")
ax.text(14.6, 99, "X  no trade", fontsize=14, color="#b71c1c", ha="right", fontweight="bold")

# D: NOT a trade - EMAs crossed down (trend is still down)
specD = [(130, 127, .5, .5), (127, 123, .5, .5), (123, 120, .5, .5), (120, 116, .5, .5), (116, 113, .5, .5), (113, 109, .5, .5),
         (109, 106, .5, .5), (106, 108, 3.5, .5), (108, 106.5, .4, .4), (106.5, 109, 3.6, .5), (109, 107, .4, .4), (107, 104, .4, .4), (104, 101, .5, .5), (101, 103.5, 3.5, .4), (103.5, 102, .4, .4), (102, 104.5, 3.5, .4)]
bars = mk(specD)
ax = axs[1][1]
e10, e20 = chart(ax, bars, "D. NOT a trade: EMA10 still BELOW EMA20\n(pullback not finished)")
ax.set_ylim(92, 136)
note(ax, (10, e10[10]), "EMA10 below EMA20\n= no trend to continue", (6.2, 130), "#b71c1c")
for xk in (7, 9, 13, 15):
    ax.annotate("hammer", xy=(xk, bars[xk][2]), xytext=(xk, 95), fontsize=8, color="#b71c1c", ha="center", arrowprops=dict(arrowstyle="->", color="#b71c1c"))
ax.text(15.6, 125, "X  no trade", fontsize=14, color="#b71c1c", ha="right", fontweight="bold")
for a in axs.ravel(): a.legend(loc="upper left", fontsize=8, frameon=False, bbox_to_anchor=(0.0, 0.93))
fig.suptitle("Context decides the trade, the hammer only times it (5-minute OPTION chart; examples are invented)", fontsize=14, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig(os.path.join(OUT, "rules_2_context_examples.png"), dpi=105); plt.close(fig)

# =====================================================================================  3. day flow
fig = plt.figure(figsize=(15, 7.4)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.01, 0.02, 0.98, 0.92]); ax.set_xlim(0, 30); ax.set_ylim(0, 16); ax.axis("off")
ax.set_title("3. The whole day on one page", loc="left", fontsize=14, fontweight="bold")


def box(x, y, w, h, text, fc="#e8f1fb", ec="#1565c0", fs=9.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15", fc=fc, ec=ec, lw=1.3))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal")


def arr(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color="#555", lw=1.4))


box(0.3, 11.8, 5.4, 3.4, "09:15  DAY FILTERS\n\nVIX open  > 15 : 2R target, 30 min hold\n12 - 15 : 4R, 60 min hold\n< 12 : NO trades\nVIX falls > 5 % by 09:30 : NO trades\n(2 trades per index max)", "#fff4e0", "#e65100")
box(6.4, 11.8, 5.2, 3.4, "GAP at open >= 0.25 %\n\ngap-up  -> only CE\ngap-down -> only PE\n(lifted once the gap is recovered\nwithin 09:15 - 10:15)", "#fff4e0", "#e65100")
box(12.3, 11.8, 5.6, 3.4, "INDEX CHART (direction)\n\nEMA10 > EMA20 and close > EMA20 -> buy CE\nEMA10 < EMA20 and close < EMA20 -> buy PE\n(chart of the OPTION decides the entry;\nindex only gives direction / context)", "#e8f5e9", "#2e7d32")
box(18.6, 11.8, 5.2, 3.4, "WHICH OPTION\n\nnearest strike only (ATM)\nNifty qty 390 (6 lots of 65)\nSensex qty 100\none position at a time per index", "#e8f5e9", "#2e7d32")
box(24.5, 11.8, 5.2, 3.4, "WHEN\n\nsignals: 09:30 - 14:45 (09:15 rules\nto come)\nmidday 10:35 - 13:00: blocked now\n(under review: best window\nin our research)", "#fdecea", "#c62828")
for x in (5.7, 11.6, 17.9, 23.8): arr(x, 13.5, x + 0.7, 13.5)
box(0.3, 6.2, 8.6, 4.4, "OPTION CHART CONTEXT\n\nEMA10 above EMA20 on the option.\nDeep pullback: EMAs crossed down and then up\nagain  ->  trade only after the re-cross.\nMild pullback: no cross, sideways pause.\nTouch test: one of the last 6 lows touched EMA10.", "#f3e5f5", "#6a1b9a")
box(9.6, 6.2, 8.6, 4.4, "TRIGGER (hammer shape + size)\n\nhammer + hammer (G,G or R,G), back to back\nhammer + hammer, <= 3 candles apart\nhammer + a proper green candle\nhammer: body 40-60 %, wick 30-60 %,\nrange >= ~1.0 x avg of last 10", "#f3e5f5", "#6a1b9a")
box(18.9, 6.2, 10.8, 4.4, "ORDER\n\nENTRY  =  open of the candle after the 2nd hammer\nSL  =  low of the 1st hammer (to be revisited)\nTARGET = 2R / 3R / 4R as set by the VIX regime\nEXIT  =  stop, target, or time limit (hold in candles)", "#e3f2fd", "#0d47a1")
arr(8.9, 8.4, 9.6, 8.4); arr(18.2, 8.4, 18.9, 8.4)
arr(14.7, 11.8, 14.7, 10.7)
box(0.3, 0.8, 29.4, 4.0, "STILL TO DECIDE:   (1) the stop rule (we will revisit)   (2) the first-hour / last-hour reversal sub-category (you will explain)   (3) the 09:15 candle without two candles (sub-category)\n"
    "(4) whether the midday block stays   (5) final hammer size   -   all of these are tested on the days we have before anything goes live", "#fffde7", "#f9a825", 10.5)
fig.savefig(os.path.join(OUT, "rules_3_day_flow.png"), dpi=105); plt.close(fig)
print("done", OUT)
