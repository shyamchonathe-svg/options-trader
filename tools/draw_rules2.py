#!/usr/bin/env python3
"""Reworked rule pictures (24 Nov feedback) + research map. python3.11 tools/draw_rules2.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pics")
os.makedirs(OUT, exist_ok=True)
GREEN, RED, BG, E10, E20 = "#26a69a", "#ef5350", "#fafafa", "#f08a24", "#2e9e4f"
BLUE = "#0d47a1"


def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


def mk(spec):
    return [(o, max(o, c) + uw, min(o, c) - lw, c) for o, c, lw, uw in spec]


def candles(ax, bars, w=0.6):
    for i, (o, h, l, c) in enumerate(bars):
        col = GREEN if c >= o else RED
        ax.plot([i, i], [l, h], color=col, lw=1.4, zorder=2)
        ax.add_patch(Rectangle((i - w / 2, min(o, c)), w, max(abs(c - o), 0.05), fc=col, ec=col, zorder=3))


def chart(ax, bars, title, e10=None, e20=None, ts=10):
    cl = [b[3] for b in bars]
    candles(ax, bars)
    e10 = e10 if e10 is not None else ema(cl, 3)
    e20 = e20 if e20 is not None else ema(cl, 6)
    ax.plot(range(len(bars)), e20, color=E20, lw=1.7, label="EMA20", zorder=1)
    ax.plot(range(len(bars)), e10, color=E10, lw=1.7, label="EMA10", zorder=1)
    ax.set_title(title, fontsize=ts, loc="left", fontweight="bold")
    ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#cccccc")
    return e10, e20


def note(ax, xy, text, xytext, color="#222", fs=8.5):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=fs, color=color, ha="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color, lw=0.8),
                arrowprops=dict(arrowstyle="->", color=color, lw=1.0), zorder=10)


def entry_sl(ax, n_entry, entry_price, sl, xs0, ytxt):
    ax.annotate("ENTRY\n(next open)", xy=(n_entry, entry_price), xytext=(n_entry + 0.2, ytxt), fontsize=8.5, color=BLUE, ha="center",
                bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE), zorder=10)
    ax.plot([xs0, n_entry + 0.6], [sl, sl], ls="--", color=RED, lw=1.3)
    ax.text(xs0, sl - 0.15, "SL = low of 1st hammer", color=RED, fontsize=8, va="top")


# ====================================================================================== 1. hammer + trigger (reworked)
fig = plt.figure(figsize=(16, 8.6)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.01, 0.03, 0.27, 0.88]); ax.set_xlim(0, 10); ax.set_ylim(-3, 10.5); ax.axis("off")
ax.set_title("1a. The HAMMER (shape + size)", loc="left", fontsize=12.5, fontweight="bold")
x, lo, hi, o, c = 2.0, 1.0, 9.0, 5.6, 7.9
ax.plot([x, x], [lo, hi], color=GREEN, lw=3); ax.add_patch(Rectangle((x - .7, o), 1.4, c - o, fc=GREEN, ec=GREEN))
for a, b, t in ((lo, o, "lower wick\n30 - 60 % of range"), (o, c, "body 40 - 60 %\n(green; the 1st hammer\nof a pair may be red)"), (c, hi, "upper wick: tiny\n(< ~12 %)")):
    ax.annotate("", xy=(3.7, a), xytext=(3.7, b), arrowprops=dict(arrowstyle="<->", color="#444"))
    ax.text(3.9, (a + b) / 2, t, fontsize=9.5, va="center")
ax.text(0.0, 0.2, "Close in the top 10 - 25 % of the range.", fontsize=9.5)
ax.text(0.0, -0.4, "SIZE: range >= ~1.0 x avg range\nof the last 10 candles\n(labelled hammers: median 1.4 x).\nSame shape but tiny = noise.", fontsize=9.5, color="#b00020", va="top")
for xx, rng, ok in ((7.6, 3.0, True), (9.0, 0.9, False)):
    ax.plot([xx, xx], [-2.6, -2.6 + rng], color=GREEN if ok else "#999", lw=3)
    ax.add_patch(Rectangle((xx - .3, -2.6 + rng * .55), .6, rng * .4, fc=GREEN if ok else "#999", ec="none"))

# three trigger panels
specs = {}
# A  back to back
barsA = mk([(106, 104.5, .3, .5), (104.5, 103, .3, .5), (103, 102, .3, .4), (102, 102.4, .2, .3),
            (101.9, 103.4, 1.1, .2), (103.5, 105.1, 1.6, .15), (105.1, 107, .3, .3), (107, 108.6, .3, .3)])
barsA[4] = (101.9, 103.5, 100.8, 103.4)       # hammer 1 : wick below both EMAs, body touches both
barsA[5] = (103.5, 105.3, 101.95, 105.1)      # hammer 2 : body above both, wick touches EMA20
e20 = [104.0, 103.4, 102.7, 102.1, 101.8, 102.0, 102.6, 103.3]
e10 = [105.0, 104.2, 103.4, 102.7, 102.4, 102.9, 103.7, 104.5]
axA = fig.add_axes([0.31, 0.50, 0.21, 0.40])
chart(axA, barsA, "A. hammer + hammer, back to back\n    (G,G  or  R,G)", e10, e20, ts=10)
axA.set_ylim(99.5, 110.5)
note(axA, (4, 100.8), "1st: low/body\ntouches both EMAs", (2.0, 100.6), BLUE)
note(axA, (5, 103.0), "2nd: BODY above both\nEMAs, wick may touch EMA20", (5.1, 109.3), BLUE)
entry_sl(axA, 6, 105.1, 100.8, 3.2, 107.6)
# B <=3 apart
barsB = [(99, 100.7, 100.9 - 1.9, 100.7)]
barsB = [(99.0, 100.9, 98.8, 100.8), (100.8, 102.2, 100.6, 102.1),
         (101.8, 103.2, 100.2, 103.0), (103.0, 103.3, 102.2, 102.4), (102.4, 102.9, 102.3, 102.7),
         (102.7, 103.0, 102.0, 102.1), (103.2, 105.0, 101.7, 104.8), (104.8, 106.5, 104.7, 106.4)]
e20 = [99.6, 100.0, 100.6, 101.2, 101.6, 101.8, 102.0, 102.5]
e10 = [100.0, 100.6, 101.3, 102.0, 102.3, 102.4, 102.7, 103.4]
axB = fig.add_axes([0.545, 0.50, 0.21, 0.40])
chart(axB, barsB, "B. two hammers, at most 3 candles apart\n    (anything in between)", e10, e20, ts=10)
axB.set_ylim(96.5, 109.5)
note(axB, (2, 100.2), "1st hammer", (1.2, 97.6), BLUE)
note(axB, (6, 101.7), "2nd hammer", (5.0, 108.2), BLUE)
axB.annotate("", xy=(2.1, 98.6), xytext=(5.9, 98.6), arrowprops=dict(arrowstyle="<->", color="#444"))
axB.text(4.0, 98.0, "3 candles", fontsize=8.5, ha="center")
entry_sl(axB, 7, 104.8, 100.2, 1.2, 106.9)
# C hammer + green
barsC = mk([(106.5, 105.2, .3, .4), (105.2, 104.0, .3, .3), (104.0, 103.0, .3, .3), (102.6, 104.0, 1.0, .2), (104.0, 105.9, .2, .15),
         (105.9, 107.2, .3, .3), (107.2, 108.5, .3, .3)])
barsC[3] = (102.6, 104.2, 101.6, 104.0)
barsC[4] = (104.0, 106.1, 103.9, 105.9)
e20 = [104.8, 104.5, 103.9, 103.2, 103.4, 104.0, 104.8]
e10 = [105.8, 105.2, 104.4, 103.8, 104.2, 105.0, 105.9]
axC = fig.add_axes([0.78, 0.50, 0.21, 0.40])
chart(axC, barsC, "C. hammer + a green candle of proper size\n    (pullback has stopped)", e10, e20, ts=10)
axC.set_ylim(99.8, 111)
note(axC, (3, 101.6), "hammer: its low may\ntouch EMA20", (1.8, 100.9), BLUE)
note(axC, (4, 105.0), "decent green candle,\nclosing above both EMAs", (4.4, 109.6), BLUE)
entry_sl(axC, 5, 105.9, 101.6, 0.8, 108.2)
# summary text
axT = fig.add_axes([0.31, 0.03, 0.68, 0.40]); axT.axis("off"); axT.set_xlim(0, 10); axT.set_ylim(0, 10)
axT.text(0, 9.6, "Common to A, B and C", fontsize=12.5, fontweight="bold", va="top")
axT.text(0, 8.5,
         "1.  Context first (see picture 2): EMA10 above EMA20 on the OPTION chart;\n     index direction agrees (index is optional help, option chart matters more).\n\n"
         "2.  1st hammer (or the hammer in C): its low or body touches the EMAs - it forms IN the EMA zone, not up in the air.\n\n"
         "3.  2nd hammer (or the green candle): BODY closes above both EMAs. A wick may dip to EMA20.\n\n"
         "4.  Within the last 6 candles at least one low touched EMA10 - so we are not buying a hammer at the end of a long run.\n\n"
         "5.  ENTRY = open of the candle after the 2nd hammer.   SL = low of the 1st hammer (stop rule to be revisited).\n\n"
         "6.  Hammer size matters: a tiny hammer in the zone is not a trigger.", fontsize=10.5, va="top")
fig.suptitle("1. What a hammer is, and the trigger   (invented candles, EMAs schematic)", fontsize=14, fontweight="bold", x=0.01, ha="left")
fig.savefig(os.path.join(OUT, "rules_1_hammer_and_trigger_v2.png"), dpi=105); plt.close(fig)

# ====================================================================================== 2. context scenarios (reworked)
fig, axs = plt.subplots(2, 3, figsize=(17, 9.6)); fig.patch.set_facecolor("white")

# A deep pullback
bars = mk([(100, 103, .6, .4), (103, 106, .5, .4), (106, 110, .5, .5), (110, 113, .5, .4), (113, 116, .5, .5), (116, 118, .6, .6),
           (118, 113, .4, .5), (113, 108, .4, .4), (108, 103, .4, .4), (103, 100, .4, .4), (100, 105, .6, .4),
           (105, 110, .5, .4), (110, 108, .6, .5), (108, 111.5, 4.8, .6), (111.5, 110.5, .5, .5), (110.5, 114, 5.0, .5),
           (114.5, 119, .5, .5), (119, 123, .5, .5)])
ax = axs[0][0]
e10, e20 = chart(ax, bars, "A. DEEP pullback: EMAs cross down, then up\n-> TRADE: 2nd hammer BODY above both EMAs")
ax.set_ylim(94, 128)
note(ax, (8.7, e20[8]), "EMA10 crossed BELOW EMA20\n(deep pullback)", (5.0, 124.5), "#b26a00")
note(ax, (11.5, (e10[11] + e20[11]) / 2), "EMA10 back ABOVE EMA20", (4.5, 99.0), "#2e7d32")
note(ax, (13, bars[13][2]), "hammer 1\n(low/body in EMA zone)", (10.6, 96.0), BLUE)
note(ax, (15, bars[15][2]), "hammer 2\n(body above both)", (15.8, 96.0), BLUE)
ax.annotate("ENTRY", xy=(16, bars[16][0]), xytext=(15.0, 108), fontsize=8.5, color=BLUE, ha="center", bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
ax.plot([12.5, 17], [bars[13][2]] * 2, ls="--", color=RED, lw=1.3)

# B mild pullback
bars = mk([(100, 104, .5, .4), (104, 108, .5, .5), (108, 111, .5, .4), (111, 114, .5, .5), (114, 117, .5, .5), (117, 119, .4, .5),
           (119, 118, .4, .5), (118, 118.8, .5, .5), (118.8, 117.6, .5, .5), (117.6, 118.6, .5, .5), (118.6, 117.8, .5, .5), (117.8, 118.5, .4, .4),
           (118.5, 120.6, 4.6, .5), (120.6, 119.8, .5, .4), (119.8, 122.5, 4.8, .5), (123, 127, .5, .5), (127, 130, .5, .5)])
ax = axs[0][1]
e10, e20 = chart(ax, bars, "B. MILD pullback: sideways pause, no cross\n-> TRADE: same hammer rules")
ax.set_ylim(94, 134)
note(ax, (9, e10[9]), "EMAs never crossed;\nprice drifts sideways\nonto EMA10/20", (6.0, 105), "#2e7d32")
note(ax, (12, bars[12][2]), "hammer 1", (9.0, 98.5), BLUE)
note(ax, (14, bars[14][2]), "hammer 2", (14.5, 98.5), BLUE)
ax.annotate("ENTRY", xy=(15, bars[15][0]), xytext=(15.3, 108), fontsize=8.5, color=BLUE, ha="center", bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
ax.plot([11.5, 16.5], [bars[12][2]] * 2, ls="--", color=RED, lw=1.3)

# C1 slow trend hugging EMA10
sp = []
p = 100.0
for i in range(13):
    sp.append((p, p + 1.0, .25, .25)); p += 1.0
sp.append((p, p + 0.9, 2.3, .15))  # late hammer
bars = mk(sp)
ax = axs[0][2]
e10, e20 = chart(ax, bars, "C1. NOT a trade: slow trend, candles HUG the EMA10\n(trend 10-12 candles old = exhaustion)")
ax.set_ylim(96, 122)
ax.annotate("", xy=(0, 98.2), xytext=(12.8, 98.2), arrowprops=dict(arrowstyle="<->", color="#b71c1c"))
ax.text(6.4, 96.6, "trend already 10 - 12 candles old", ha="center", fontsize=9, color="#b71c1c")
note(ax, (13, bars[13][2]), "hammer here =\nexhaustion candle", (10.6, 118.5), "#b71c1c")
ax.text(0.3, 112, "every candle touches EMA10 ->\nthe 6-candle touch test PASSES,\nbut it is the wrong place.\nA hammer is only good at the\nSTART of a continuation.", fontsize=9, color="#b71c1c", va="center")
ax.text(13.6, 98.0, "X  no trade", fontsize=13, color="#b71c1c", ha="right", fontweight="bold")

# C2 floating above EMA10, EMA10 accelerating
sp = [(100, 102, .4, .4), (102, 104.5, .4, .4), (104.5, 107.5, .4, .4), (107.5, 111, .4, .4), (111, 115.5, .4, .4), (115.5, 121, .4, .4),
      (121, 127, .4, .4), (127, 134, .4, .4), (134, 141.5, .4, .4), (141.5, 149.5, .4, .4), (149.5, 152.5, 4.5, .4), (153, 160, .4, .4), (160, 163.5, 4.8, .5), (164, 168, .4, .4)]
bars = mk(sp)
ax = axs[1][0]
e10, e20 = chart(ax, bars, "C2. NOT a trade: candles FLOAT above EMA10\nEMA10 turns exponential, running away from EMA20")
ax.set_ylim(94, 180)
for xk, ty in ((10, 172), (12, 160)):
    note(ax, (xk, bars[xk][2]), "hammer", (xk - 3.2, ty), "#b71c1c")
ax.annotate("", xy=(11, e10[11]), xytext=(11, e20[11]), arrowprops=dict(arrowstyle="<->", color="#b71c1c"))
ax.text(0.2, 152, "candles open AND close above EMA10,\nnot even touching it ('hanging in the air');\nEMA10 pulls away from EMA20", fontsize=9, color="#b71c1c")
ax.text(13.6, 100, "X  no trade", fontsize=13, color="#b71c1c", ha="right", fontweight="bold")

# D
bars = mk([(130, 127, .5, .5), (127, 123, .5, .5), (123, 120, .5, .5), (120, 116, .5, .5), (116, 113, .5, .5), (113, 109, .5, .5),
           (109, 106, .5, .5), (106, 108, 3.5, .5), (108, 106.5, .4, .4), (106.5, 109, 3.6, .5), (109, 107, .4, .4), (107, 104, .4, .4), (104, 101, .5, .5), (101, 103.5, 3.5, .4), (103.5, 102, .4, .4), (102, 104.5, 3.5, .4)])
ax = axs[1][1]
e10, e20 = chart(ax, bars, "D. NOT a trade: EMA10 still BELOW EMA20\n(pullback not finished)")
ax.set_ylim(92, 136)
note(ax, (10, e10[10]), "EMA10 below EMA20\n= no trend to continue", (6.2, 130), "#b71c1c")
for xk in (7, 9, 13, 15):
    ax.annotate("hammer", xy=(xk, bars[xk][2]), xytext=(xk, 95), fontsize=8, color="#b71c1c", ha="center", arrowprops=dict(arrowstyle="->", color="#b71c1c"))
ax.text(15.6, 125, "X  no trade", fontsize=13, color="#b71c1c", ha="right", fontweight="bold")

# checklist
ax = axs[1][2]; ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 10)
ax.text(0, 9.8, "Checklist the engine would apply (option chart)", fontsize=11.5, fontweight="bold", va="top")
ax.text(0, 8.9,
        "TRADE only if ALL are true\n"
        "  -  EMA10 above EMA20 now (re-crossed up after a deep\n     pullback, or never crossed in a mild one)\n"
        "  -  hammer 1 forms in the EMA zone (low/body touches)\n"
        "  -  hammer 2 / green candle: BODY above both EMAs\n"
        "  -  a low within the last 6 candles touched EMA10\n"
        "  -  the move is young (not 10-12 candles of hugging)\n"
        "  -  candles are not floating far above EMA10\n"
        "  -  hammer size ok;  index direction agrees\n\n"
        "REJECT if ANY\n"
        "  -  EMA10 below EMA20 (D)\n"
        "  -  old slow trend, hugging EMA10 (C1)\n"
        "  -  candles hanging above EMA10, EMAs fanning out (C2)",
        fontsize=10, va="top")
for a in axs.ravel()[:5]: a.legend(loc="upper left", fontsize=8, frameon=False, bbox_to_anchor=(0.0, 0.88))
fig.suptitle("2. Context decides the trade, the hammer only times it   (5-minute OPTION chart; invented examples)", fontsize=14, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(os.path.join(OUT, "rules_2_context_examples_v2.png"), dpi=100); plt.close(fig)

# ====================================================================================== 3. research map
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
try:
    from trader import research as RS
    HAM = RS.HAMMERS
except Exception:
    HAM = {}
fig = plt.figure(figsize=(17, 11)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.01, 0.02, 0.98, 0.93]); ax.set_xlim(0, 34); ax.set_ylim(0, 24); ax.axis("off")
fig.suptitle("Everything we tested in the research harness (shapes are the MINIMUM each rule accepts)", fontsize=15, fontweight="bold", x=0.01, ha="left")
ax.text(0, 23.3, "HAMMER variants (single candle test, then v3 signal rules around it)", fontsize=12, fontweight="bold")
ax.text(0, 22.5, "icon = loosest candle the variant accepts      touch = a low in the last N candles within 0.3 % of EMA10      size = range >= 1.0 x avg of last 10      red = red candle among the 2 before", fontsize=8.5, color="#555")
row = 21.2
for name, p in HAM.items():
    base = row - 0.9
    lw = p["lw"]; clv = p["clv"]
    bd = p.get("bmax", max(p["body"], clv - lw)) if p["body"] > 0 else 0
    if "bmax" in p: bd = p["bmax"]
    else: bd = max(p["body"], clv - lw)
    uwf = max(0.0, 1 - lw - bd)
    x = 0.8; H = 1.5
    col = GREEN if not p.get("anycolor") else "#999"
    if p["body"] == 0:
        ax.text(x - 0.5, base + 0.5, "any candle", fontsize=8, color="#777")
    else:
        ax.plot([x, x], [base, base + H], color=col, lw=2)
        ax.add_patch(Rectangle((x - .25, base + lw * H), .5, bd * H, fc=col, ec=col))
    txt = "%s" % name
    ax.text(2.6, base + 0.95, txt, fontsize=9.5, fontweight="bold", va="center")
    d = "body >= %d%%%s   close in top %d%%   lower wick >= %d%%%s   touch %d   size %s%s" % (
        p["body"] * 100, (" (max %d%%)" % (p["bmax"] * 100)) if "bmax" in p else "", round((1 - clv) * 100), lw * 100,
        (", upper wick <= %d%%" % (p["uw"] * 100)) if "uw" in p else "", p["touch"], "on" if p["size"] else "off",
        "   ANY colour" if p.get("anycolor") else "   red-before yes")
    ax.text(2.6, base + 0.35, d, fontsize=8.5, va="center", color="#333")
    row -= 1.55
ax.text(0, row + 0.3, "+ GRID SEARCH: ~140 hammer combos\n   (body 15/30, close-top 40/35/25, wick 15/25/40, touch 2/3/6, size off/on)\n   + classic (wick 50/60, bodymax 35/50, upper wick 10/20, touch 3/6, size off/on)", fontsize=9, color="#0d47a1", va="top")

# inside candle side
X0 = 19.5
ax.text(X0, 23.3, "INSIDE-candle variants (introduced 18 Nov)", fontsize=12, fontweight="bold")
ix = ax.inset_axes([X0 / 34, 0.60, 0.20, 0.28]); ix.set_xlim(-1, 5); ix.set_ylim(0, 12); ix.axis("off")
ix.add_patch(Rectangle((0.7, 2), 0.6, 7.5, fc=GREEN, ec=GREEN)); ix.plot([1, 1], [1.6, 9.9], color=GREEN, lw=1.5)
ix.add_patch(Rectangle((1.7, 5.2), 0.6, 1.6, fc=RED, ec=RED)); ix.plot([2, 2], [4.8, 7.5], color=RED, lw=1.5)
ix.add_patch(Rectangle((2.7, 6.0), 0.6, 4.8, fc=GREEN, ec=GREEN)); ix.plot([3, 3], [5.8, 11.2], color=GREEN, lw=1.5)
ix.text(1, 0.3, "k: BIG green\nbody>=50%,\nrange >= 1.2-2.0x avg", ha="center", fontsize=7.5)
ix.text(2, 8.4, "k+1 inside k\n(range <= 40-80% of k)", ha="center", fontsize=7.5)
ix.text(3.3, 0.3, "k+2 breaks above\nk+1 high -> ENTER", ha="center", fontsize=7.5, color=BLUE)
ix.plot([0, 4.3], [5.2, 5.2], ls="--", color=RED, lw=1); ix.text(4.3, 4.6, "SL: low of k+1\n(or low of k)", fontsize=7.5, color=RED, ha="right", va="top")
rows = [("I1", "option only, trend fresh (<= 6 candles from cross), SL inside"),
        ("I2", "option + index agree, fresh <= 6, SL inside"),
        ("I3", "option + index agree, any time, SL inside"),
        ("I4", "option + index, fresh <= 6, WIDE stop (low of big candle)"),
        ("I5", "option only, any time, SL inside"),
        ("I6", "option + index (any size), any time, SL inside")]
yy = 12.6
for n, t in rows:
    ax.text(X0, yy, n, fontsize=10, fontweight="bold"); ax.text(X0 + 1.2, yy, t, fontsize=8.8); yy -= 0.8
ax.text(X0, yy - 0.2, "+ GRID SEARCH: ~144 combos\n  (big 1.2/1.5/2.0 x, inside size 40/60/80 %, fresh 3/6/12/any,\n   option vs option+index, stop inside vs big)", fontsize=8.8, color=BLUE, va="top")
ax.text(X0, yy - 2.6, "NEXT (your logic, C1)", fontsize=11.5, fontweight="bold", color="#b26a00")
ax.text(X0, yy - 3.0,
        "double hammer (G,G / R,G / <=3 apart / hammer+green)\n"
        "1st hammer in EMA zone, 2nd body above both EMAs\n"
        "EMA10 > EMA20, last-6 low touched EMA10\n"
        "reject: old hugging trend, floating candles\n"
        "entry open after 2nd hammer, SL low of 1st\n"
        "size grid: 0.8 / 1.0 / 1.2 / 1.5 x avg range", fontsize=9, va="top")
fig.savefig(os.path.join(OUT, "research_map.png"), dpi=100); plt.close(fig)
print("done")
