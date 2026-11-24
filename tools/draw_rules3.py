#!/usr/bin/env python3
"""Rule pictures v3 (24 Nov, second feedback). python3.11 tools/draw_rules3.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pics")
os.makedirs(OUT, exist_ok=True)
GREEN, RED, BG, E10, E20, BLUE, DR = "#26a69a", "#ef5350", "#fafafa", "#f08a24", "#2e9e4f", "#0d47a1", "#b71c1c"


def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


def mk(spec):  # (open, close, lower wick, upper wick) -> (O,H,L,C)
    return [(o, max(o, c) + uw, min(o, c) - lw, c) for o, c, lw, uw in spec]


def candles(ax, bars, w=0.6):
    for i, (o, h, l, c) in enumerate(bars):
        col = GREEN if c >= o else RED
        ax.plot([i, i], [l, h], color=col, lw=1.4, zorder=2)
        ax.add_patch(Rectangle((i - w / 2, min(o, c)), w, max(abs(c - o), 0.05), fc=col, ec=col, zorder=3))


def chart(ax, bars, title, e10=None, e20=None, ts=10):
    cl = [b[3] for b in bars]
    candles(ax, bars)
    e10 = e10 if e10 is not None else ema(cl, 5)
    e20 = e20 if e20 is not None else ema(cl, 10)
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


def entry(ax, x, price, xytext, text="ENTRY\n(next open)"):
    ax.annotate(text, xy=(x, price), xytext=xytext, fontsize=8.5, color=BLUE, ha="center",
                bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE), zorder=10)


def sl(ax, x0, x1, y, label, below=True):
    ax.plot([x0, x1], [y, y], ls="--", color=DR, lw=1.3)
    ax.text(x0, y - 0.2 if below else y + 0.2, label, color=DR, fontsize=8, va="top" if below else "bottom")


def body_above(bars, e10, e20, i):
    """check: whole body of bar i above both EMAs"""
    o, h, l, c = bars[i]
    return min(o, c) > max(e10[i], e20[i])


# ====================================================================================== IMAGE 1
fig = plt.figure(figsize=(17, 10)); fig.patch.set_facecolor("white")
ax = fig.add_axes([0.01, 0.04, 0.17, 0.86]); ax.set_xlim(0, 10); ax.set_ylim(-3.2, 10.5); ax.axis("off")
ax.set_title("The HAMMER", loc="left", fontsize=12.5, fontweight="bold")
x, lo, hi, o, c = 2.0, 1.0, 9.0, 5.6, 7.9
ax.plot([x, x], [lo, hi], color=GREEN, lw=3); ax.add_patch(Rectangle((x - .7, o), 1.4, c - o, fc=GREEN, ec=GREEN))
for a, b, t in ((lo, o, "lower wick\n30 - 60 %"), (o, c, "body 40 - 60 %\n(1st hammer of a\npair may be red)"), (c, hi, "upper wick\ntiny (< ~12 %)")):
    ax.annotate("", xy=(3.6, a), xytext=(3.6, b), arrowprops=dict(arrowstyle="<->", color="#444"))
    ax.text(3.8, (a + b) / 2, t, fontsize=9, va="center")
ax.text(0.0, 0.3, "Close in top 10 - 25 %.", fontsize=9)
ax.text(0.0, -0.4, "SIZE (rule H1): range >=\n~1.0 x avg of last 10\ncandles. Tiny = noise.", fontsize=9, color="#b00020", va="top")
ax.text(0.0, -2.2, "REVERSAL hammer (D, E): wick\nis LONGER than usual (> 60 %).", fontsize=9, color=BLUE, va="top")

W, Hh = 0.255, 0.38
X = [0.205, 0.47, 0.735]

# --- A back to back
barsA = [(106, 106.2, 104.2, 104.5), (104.5, 104.7, 102.7, 103.0), (103.0, 103.3, 101.7, 102.0), (102.0, 102.7, 101.8, 102.4),
         (101.9, 103.5, 100.8, 103.4), (104.4, 106.0, 103.1, 105.9), (105.9, 106.3, 105.8, 106.2), (106.2, 108.0, 106.0, 107.8)]
e20 = [104.4, 103.8, 103.1, 102.6, 102.4, 102.7, 103.2, 103.8]
e10 = [105.2, 104.4, 103.6, 102.9, 102.9, 103.2, 103.8, 104.6]
axA = fig.add_axes([X[0], 0.53, W, Hh]); chart(axA, barsA, "A. Pullback: hammer + hammer, back to back (G,G or R,G)", e10, e20, 9.5)
assert body_above(barsA, e10, e20, 5), "A body"
axA.set_ylim(99.5, 111.0)
note(axA, (4, 100.8), "1st: body touches\nboth EMAs (or sits above)", (2.2, 100.4), BLUE)
note(axA, (5, 103.9), "2nd: WHOLE body above\nboth EMAs (wick may\ndip to EMA20)", (3.4, 109.0), BLUE)
entry(axA, 6, 105.9, (6.4, 109.8)); sl(axA, 3.3, 7, 100.8, "SL = low of 1st hammer")

# --- B <=3 apart
barsB = [(99.0, 100.9, 98.8, 100.8), (100.8, 102.2, 100.6, 102.1), (101.8, 103.2, 100.2, 103.0), (103.0, 103.3, 102.2, 102.4),
         (102.4, 102.9, 102.3, 102.7), (102.7, 103.0, 102.0, 102.1), (104.3, 106.0, 101.7, 105.8), (105.8, 107.5, 105.7, 107.4)]
e20 = [99.6, 100.0, 100.6, 101.2, 101.6, 101.8, 102.0, 102.8]
e10 = [100.0, 100.6, 101.3, 102.0, 102.3, 102.4, 102.7, 103.7]
axB = fig.add_axes([X[1], 0.53, W, Hh]); chart(axB, barsB, "B. Pullback: two hammers, at most 3 candles apart", e10, e20, 9.5)
assert body_above(barsB, e10, e20, 6), "B body"
axB.set_ylim(96.5, 110)
note(axB, (2, 100.2), "1st hammer", (1.2, 97.6), BLUE)
note(axB, (6, 104.9), "2nd: WHOLE body\nabove both EMAs", (4.6, 108.4), BLUE)
axB.annotate("", xy=(2.1, 98.7), xytext=(5.9, 98.7), arrowprops=dict(arrowstyle="<->", color="#444")); axB.text(4.0, 98.1, "3 candles", fontsize=8.5, ha="center")
entry(axB, 7, 105.8, (7.0, 109.0)); sl(axB, 2.5, 7.4, 100.2, "SL = low of 1st hammer")

# --- C hammer (H1) + green
barsC = [(106.5, 106.9, 105.0, 105.2), (105.2, 105.5, 103.8, 104.0), (104.0, 104.3, 103.4, 103.6), (103.2, 104.7, 101.9, 104.6),
         (104.8, 107.2, 104.7, 107.0), (107.0, 107.4, 106.9, 107.2), (107.2, 108.9, 107.1, 108.6)]
e20 = [104.6, 104.2, 103.8, 103.6, 103.9, 104.5, 105.2]
e10 = [105.4, 104.9, 104.4, 104.0, 104.4, 105.2, 106.0]
axC = fig.add_axes([X[2], 0.53, W, Hh]); chart(axC, barsC, "C. Pullback: ONE H1 hammer + green candle of proper size", e10, e20, 9.5)
assert body_above(barsC, e10, e20, 4), "C body"
axC.set_ylim(99.8, 112)
note(axC, (3, 103.0), "H1 hammer: BODY touches the EMAs\n(same place as hammer 1 of A / B,\nnever down below the EMAs)", (1.6, 109.2), BLUE)
note(axC, (4, 105.9), "proper green candle:\nWHOLE body above both", (5.0, 100.8), BLUE)
entry(axC, 5, 107.0, (5.5, 110.6)); sl(axC, 1.0, 5.6, 101.9, "SL = low of hammer", below=True)

# --- D morning reversal
barsD = [(101.0, 103.7, 92.0, 103.5), (103.5, 112.0, 103.2, 111.5), (111.6, 115.6, 111.4, 115.3), (115.3, 116.8, 115.0, 116.2), (116.2, 116.9, 113.5, 114.0), (114.0, 114.5, 112.0, 112.5)]
e20 = [113.6, 113.4, 113.5, 113.7, 114.0, 114.1]
e10 = [113.2, 112.6, 113.0, 113.8, 114.4, 114.4]
axD = fig.add_axes([X[0], 0.07, W, Hh]); chart(axD, barsD, "D. REVERSAL, MORNING (e.g. 09:15 / 09:20)", e10, e20, 9.5)
axD.set_ylim(89, 124)
note(axD, (0, 94.5), "hammer WAY BELOW the EMAs,\nvery long wick (> usual)", (2.0, 92.5), BLUE)
note(axD, (1, 107), "strong follow-up candle\ncloses close to the EMAs", (2.0, 121.0), BLUE)
entry(axD, 2, 111.6, (3.9, 120.0), "ENTRY\n(open of next)")
sl(axD, 0.3, 5, 103.2, "SL = low of the follow-up candle", below=False)
axD.text(3.5, 96.5, "max hold 3 candles\nafter 2 candles: book 50 %\nthen trail aggressively", fontsize=8.5, ha="center", color="#333", bbox=dict(boxstyle="round", fc="#fff4e0", ec="#e65100"))
axD.text(0.0, 118, "market too oversold /\noverbought: snap-back", fontsize=8.5, color="#555")

# --- E afternoon reversal
barsE = [(100.2, 100.5, 99.5, 99.8), (99.8, 100.2, 99.0, 99.2), (99.2, 99.9, 98.8, 99.6), (99.6, 100.0, 98.8, 99.0), (99.0, 99.6, 98.5, 99.3),
         (99.3, 99.4, 98.4, 98.6), (98.4, 99.9, 95.6, 99.8), (99.8, 103.2, 99.6, 103.0), (103.1, 104.4, 103.0, 104.2), (104.2, 105.3, 104.1, 105.1),
         (105.1, 106.2, 105.0, 106.0), (106.0, 107.2, 105.9, 107.0), (107.0, 107.6, 106.2, 106.5)]
e20 = [100.5, 100.4, 100.3, 100.2, 100.1, 100.0, 100.0, 100.0, 100.4, 100.9, 101.5, 102.1, 102.8]
e10 = [100.2, 100.1, 100.0, 100.0, 99.9, 99.8, 99.7, 99.8, 100.6, 101.4, 102.3, 103.2, 104.0]
axE = fig.add_axes([X[1], 0.07, W, Hh]); chart(axE, barsE, "E. REVERSAL, AFTERNOON (after ~14:00)", e10, e20, 9.5)
axE.set_ylim(93.5, 111)
note(axE, (3, 100.2), "EMAs sideways", (2.0, 103.5), "#2e7d32")
note(axE, (6, 96.5), "strong hammer", (4.0, 94.8), BLUE)
note(axE, (7, 101.2), "strong follow-up, CLOSES\nabove the EMAs", (8.5, 96.0), BLUE)
entry(axE, 8, 103.1, (10.3, 109.7), "ENTRY")
sl(axE, 6.0, 12.6, 99.6, "SL = low of the follow-up candle", below=True)
axE.text(0.1, 109.7, "hold 3 - 6 candles; book 50 %\nafter 3 candles, then trail\naggressively", fontsize=8.5, color="#333", va="top", bbox=dict(boxstyle="round", fc="#fff4e0", ec="#e65100"))

# --- summary text
axT = fig.add_axes([X[2], 0.05, W, 0.42]); axT.axis("off"); axT.set_xlim(0, 10); axT.set_ylim(0, 10)
axT.text(0, 9.9, "Three setups, one idea: context first", fontsize=11.5, fontweight="bold", va="top")
axT.text(0, 9.0,
         "PULLBACK CONTINUATION  (A, B, C)\n"
         " - EMA10 > EMA20, last-6 low touched EMA10\n"
         " - 1st hammer body touches / above EMAs\n   (never below them), H1 size\n"
         " - 2nd hammer / green: WHOLE body above both\n"
         " - entry open after 2nd, SL low of 1st\n\n"
         "REVERSAL, MORNING  (D)\n"
         " - hammer far below EMAs, extra-long wick\n"
         " - strong follow-up closes near the EMAs\n"
         " - SL low of follow-up; max 3 candles; 50 %\n   off after 2; trail hard\n\n"
         "REVERSAL, AFTERNOON  (E)\n"
         " - after ~14:00, EMAs flat\n"
         " - strong hammer + strong follow-up above EMAs\n"
         " - SL low of follow-up; hold 3-6 candles;\n   50 % off after 3; trail hard", fontsize=9.3, va="top", linespacing=1.15)
fig.suptitle("1. What a hammer is, and the three trigger families   (invented candles, EMAs schematic)", fontsize=14, fontweight="bold", x=0.01, ha="left")
fig.savefig(os.path.join(OUT, "rules_1_hammer_and_trigger_v3.png"), dpi=100); plt.close(fig)

# ====================================================================================== IMAGE 2
fig, axs = plt.subplots(2, 3, figsize=(17, 9.6)); fig.patch.set_facecolor("white")

# A deep pullback
specA = [(100, 103, .6, .4), (103, 106, .5, .4), (106, 110, .5, .5), (110, 113, .5, .4), (113, 116, .5, .5), (116, 118, .6, .6),
         (118, 113, .4, .5), (113, 108, .4, .4), (108, 103, .4, .4), (103, 100, .4, .4), (100, 105, .6, .4),
         (105, 110, .5, .4), (110, 108, .6, .5), (108, 111.5, 1.8, .4), (111.5, 111.0, .5, .5)]
bars = mk(specA) + [(112.5, 116.8, 110.4, 116.5), (116.5, 119.5, 116.3, 119.0), (119.0, 123.2, 118.8, 123.0)]
ax = axs[0][0]
e10, e20 = chart(ax, bars, "A. DEEP pullback: EMAs cross down, then up\n-> TRADE: 2nd hammer WHOLE body above both EMAs")
assert body_above(bars, e10, e20, 15), (bars[15], e10[15], e20[15])
ax.set_ylim(94, 128)
note(ax, (8.7, e20[8]), "EMA10 crossed BELOW EMA20\n(deep pullback)", (5.0, 124.5), "#b26a00")
note(ax, (11.5, (e10[11] + e20[11]) / 2), "EMA10 back ABOVE EMA20", (4.5, 99.0), "#2e7d32")
note(ax, (13, bars[13][2]), "hammer 1\n(low/body in EMA zone)", (9.4, 96.0), BLUE)
note(ax, (15, bars[15][2]), "hammer 2\n(whole body above both)", (15.0, 99.5), BLUE)
entry(ax, 16, bars[16][0], (14.8, 108), "ENTRY")
ax.plot([12.5, 17], [bars[13][2]] * 2, ls="--", color=DR, lw=1.3)

# B mild
specB = [(100, 104, .5, .4), (104, 108, .5, .5), (108, 111, .5, .4), (111, 114, .5, .5), (114, 117, .5, .5), (117, 119, .4, .5),
         (119, 118, .4, .5), (118, 118.8, .5, .5), (118.8, 117.6, .5, .5), (117.6, 118.6, .5, .5), (118.6, 117.8, .5, .5), (117.8, 118.5, .4, .4),
         (118.5, 120.6, 2.5, .5), (120.6, 119.8, .5, .4)]
bars = mk(specB) + [(121.9, 124.8, 120.4, 124.5), (125, 127.5, 124.8, 127.0), (127.0, 130.5, 126.8, 130.0)]
ax = axs[0][1]
e10, e20 = chart(ax, bars, "B. MILD pullback: sideways pause, no cross\n-> TRADE: same hammer rules")
assert body_above(bars, e10, e20, 14), (bars[14], e10[14], e20[14])
ax.set_ylim(94, 134)
note(ax, (9, e10[9]), "EMAs never crossed;\nprice drifts sideways\nonto EMA10/20", (6.0, 105), "#2e7d32")
note(ax, (12, bars[12][2]), "hammer 1", (9.0, 98.5), BLUE)
note(ax, (14, bars[14][2]), "hammer 2", (14.5, 98.5), BLUE)
entry(ax, 15, bars[15][0], (15.3, 108), "ENTRY")
ax.plot([11.5, 16.5], [bars[12][2]] * 2, ls="--", color=DR, lw=1.3)

# C1 slow trend hugging
sp = []; p = 100.0
for i in range(13):
    sp.append((p, p + 1.0, .25, .25)); p += 1.0
sp.append((p, p + 0.9, 2.3, .15))
bars = mk(sp)
ax = axs[0][2]
e10, e20 = chart(ax, bars, "C1. NOT a trade: slow trend, candles HUG the EMA10\n(trend 10-12 candles old = exhaustion)")
ax.set_ylim(96, 122)
ax.annotate("", xy=(0, 98.2), xytext=(12.8, 98.2), arrowprops=dict(arrowstyle="<->", color=DR))
ax.text(6.4, 96.6, "trend already 10 - 12 candles old", ha="center", fontsize=9, color=DR)
note(ax, (13, bars[13][2]), "hammer here =\nexhaustion candle", (10.6, 118.5), DR)
ax.text(0.3, 112, "every candle touches EMA10 ->\nthe 6-candle touch test passes,\nbut it is the wrong place.\nA hammer is only good at the\nSTART of a continuation.", fontsize=9, color=DR, va="center")
ax.text(13.6, 98.0, "X  no trade", fontsize=13, color=DR, ha="right", fontweight="bold")

# C2 floating: every candle opens AND closes (and lows) above EMA10; EMA10 slowly curving away from EMA20
n = 14
e20 = [100 + 0.9 * i for i in range(n)]
e10 = [100.4 + 0.9 * i + 0.045 * i * i for i in range(n)]
bars = []
for i in range(n):
    base = e10[i] + 3.2 + 0.12 * i
    if i < n - 1:
        bars.append((base, base + 2.0 + 0.08 * i + 0.4, base - 0.4, base + 2.0 + 0.08 * i))
    else:
        o, c = base + 1.2, base + 3.0
        bars.append((o, c + 0.3, e10[i] + 1.3, c))                  # hammer: still NOT touching EMA10
ax = axs[1][0]
chart(ax, bars, "C2. NOT a trade: candles FLOAT above EMA10\nEMA10 slowly turning parabolic, away from EMA20", e10, e20)
assert all(min(b[0], b[3]) > e10[i] and b[2] > e10[i] for i, b in enumerate(bars))
ax.set_ylim(94, 150)
note(ax, (13, bars[13][2]), "hammer: even its low does\nnot reach EMA10", (9.5, 146), DR)
ax.annotate("", xy=(10, e10[10]), xytext=(10, e20[10]), arrowprops=dict(arrowstyle="<->", color=DR))
ax.text(10.2, (e10[10] + e20[10]) / 2 - 3.5, "gap widening", fontsize=8.5, color=DR)
ax.text(0.2, 128, "every candle opens AND closes above\nEMA10 (lows too): never touches it.\nNothing to pull back from - the\nhammer is a blow-off, not a restart.", fontsize=9, color=DR, va="center")
ax.text(13.6, 98, "X  no trade", fontsize=13, color=DR, ha="right", fontweight="bold")

# D
bars = mk([(130, 127, .5, .5), (127, 123, .5, .5), (123, 120, .5, .5), (120, 116, .5, .5), (116, 113, .5, .5), (113, 109, .5, .5),
           (109, 106, .5, .5), (106, 108, 3.5, .5), (108, 106.5, .4, .4), (106.5, 109, 3.6, .5), (109, 107, .4, .4), (107, 104, .4, .4), (104, 101, .5, .5), (101, 103.5, 3.5, .4), (103.5, 102, .4, .4), (102, 104.5, 3.5, .4)])
ax = axs[1][1]
e10, e20 = chart(ax, bars, "D. NOT a trade: EMA10 still BELOW EMA20\n(pullback not finished)")
ax.set_ylim(92, 136)
note(ax, (10, e10[10]), "EMA10 below EMA20\n= no trend to continue", (6.2, 130), DR)
for xk in (7, 9, 13, 15):
    ax.annotate("hammer", xy=(xk, bars[xk][2]), xytext=(xk, 95), fontsize=8, color=DR, ha="center", arrowprops=dict(arrowstyle="->", color=DR))
ax.text(15.6, 125, "X  no trade", fontsize=13, color=DR, ha="right", fontweight="bold")

ax = axs[1][2]; ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 10)
ax.text(0, 9.8, "Checklist for the pullback continuation (option chart)", fontsize=11.5, fontweight="bold", va="top")
ax.text(0, 8.9,
        "TRADE only if ALL are true\n"
        "  -  EMA10 above EMA20 (re-crossed up after a deep\n     pullback, or never crossed in a mild one)\n"
        "  -  hammer body touches or is above the EMAs\n     (never below them)\n"
        "  -  hammer 2 / green: WHOLE body above both EMAs\n"
        "  -  a low in the last 6 candles touched EMA10\n"
        "  -  the move is young (not 10-12 candles hugging)\n"
        "  -  candles are not floating above EMA10\n"
        "  -  H1 size; index direction agrees\n\n"
        "REJECT if ANY\n"
        "  -  EMA10 below EMA20 (D)\n"
        "  -  old slow trend hugging EMA10 (C1)\n"
        "  -  candles all open+close above EMA10, never\n     touching it, EMA10 curving away (C2)\n\n"
        "Reversal hammers (picture 1, D and E) are a\nseparate family: they trade AGAINST the EMAs.",
        fontsize=10, va="top")
for a in axs.ravel()[:5]: a.legend(loc="upper left", fontsize=8, frameon=False, bbox_to_anchor=(0.0, 0.88))
fig.suptitle("2. Context decides the trade, the hammer only times it   (5-minute OPTION chart; invented examples)", fontsize=14, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(os.path.join(OUT, "rules_2_context_examples_v3.png"), dpi=100); plt.close(fig)
print("done")
