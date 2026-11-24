#!/usr/bin/env python3
"""Final inside-candle setup (I2 filters + stop at low of big candle). python3.11 tools/draw_inside_final.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pics")
GREEN, RED, BLUE, DR, E10, E20, BG = "#26a69a", "#ef5350", "#0d47a1", "#b71c1c", "#f08a24", "#2e9e4f", "#fafafa"


def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


def draw(ax, bars, title):
    cl = [b[3] for b in bars]
    for i, (o, h, l, c) in enumerate(bars):
        col = GREEN if c >= o else RED
        ax.plot([i, i], [l, h], color=col, lw=1.6, zorder=2)
        ax.add_patch(Rectangle((i - .3, min(o, c)), .6, max(abs(c - o), .05), fc=col, ec=col, zorder=3))
    ax.plot(ema(cl, 6), color=E20, lw=1.8, label="EMA20", zorder=1); ax.plot(ema(cl, 3), color=E10, lw=1.8, label="EMA10", zorder=1)
    ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([]); ax.set_title(title, fontsize=12, loc="left", fontweight="bold")
    for s in ax.spines.values(): s.set_color("#cccccc")
    ax.legend(loc="upper left", fontsize=8, frameon=False)


OPT = [(110, 110.3, 107.7, 108), (108, 108.3, 105.7, 106), (106, 106.3, 104.2, 104.5), (104.5, 107.2, 104.3, 107.0),
       (107.0, 109.2, 106.8, 109.0), (109.0, 111.0, 108.8, 110.8), (110.8, 111.2, 110.0, 110.5),
       (110.5, 118.0, 110.2, 117.5), (116.8, 117.6, 114.8, 115.6), (115.8, 121.0, 115.6, 120.6), (120.6, 123.5, 120.4, 123.0), (123.0, 126.0, 122.8, 125.6), (125.6, 130.0, 125.4, 129.5)]
K = 7
IDX = [(100, 100.3, 98.6, 99.0), (99.0, 99.2, 97.8, 98.0), (98.0, 98.2, 97.0, 97.2), (97.2, 98.9, 97.1, 98.7), (98.7, 100.2, 98.5, 100.0),
       (100.0, 101.2, 99.9, 101.0), (101.0, 102.3, 100.9, 102.1), (102.1, 106.8, 102.0, 106.5), (106.2, 106.7, 104.8, 105.3), (105.5, 108.8, 105.4, 108.5),
       (108.5, 109.6, 108.3, 109.4), (109.4, 110.5, 109.2, 110.3), (110.3, 111.4, 110.2, 111.2)]
fig = plt.figure(figsize=(18, 10.5)); fig.patch.set_facecolor("white")
fig.suptitle("FINAL inside-candle setup  (= I2 filters + stop at the low of the BIG candle)    shown for a CE; a PE is the mirror image on the index", fontsize=14.5, fontweight="bold", x=0.01, ha="left")
ax = fig.add_axes([0.02, 0.36, 0.50, 0.54]); ai = fig.add_axes([0.02, 0.06, 0.50, 0.25])
draw(ax, OPT, "OPTION chart (what we buy)"); draw(ai, IDX, "INDEX chart (same candles k, k+1, k+2)")
ax.set_ylim(100, 146); ai.set_xlim(-0.6, 12.6); ax.set_xlim(-0.6, 13.6)
kb, ib = OPT[K], OPT[K + 1]
entry = ib[1]; stp = kb[2]; R = entry - stp; tgt = entry + 3 * R
ax.annotate("k: BIG green\nbody >= 50 % of range\nrange >= 1.5x avg10\ncloses above EMA20", xy=(K, kb[1]), xytext=(K - 3.4, 134), fontsize=9, ha="center", color=BLUE, bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
ax.annotate("k+1 INSIDE k\n(range <= 60 % of k)", xy=(K + 1, ib[2]), xytext=(K + 0.2, 103), fontsize=9, ha="center", color="#555", bbox=dict(boxstyle="round", fc="white", ec="#777"), arrowprops=dict(arrowstyle="->", color="#555"))
ax.annotate("k+2 breaks above the high of k+1\nENTRY at that price", xy=(K + 2, entry), xytext=(K + 4.2, 118), fontsize=9, ha="center", color=BLUE, bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
ax.plot([K - 0.6, 12.6], [stp, stp], ls="--", color=DR, lw=1.5); ax.text(K - 0.6, stp - 0.6, "STOP = low of the BIG candle k", color=DR, fontsize=9.5, va="top")
ax.plot([K + 1.6, 12.6], [tgt, tgt], ls=":", color="#2e7d32", lw=1.3); ax.text(12.6, tgt - 0.5, "3R target %.1f" % tgt, color="#2e7d32", fontsize=9.5, ha="right", va="top")
ax.annotate("", xy=(13.1, entry), xytext=(13.1, stp), arrowprops=dict(arrowstyle="<->", color=DR)); ax.text(13.25, (entry + stp) / 2, "risk\n%.1f" % R, color=DR, fontsize=9, va="center")
ai.annotate("INDEX must show the same:\nbig green k + inside k+1\n(range >= 1.0x avg10)", xy=(K, IDX[K][1]), xytext=(2.6, 107), fontsize=9, ha="center", color="#2e7d32", bbox=dict(boxstyle="round", fc="white", ec="#2e7d32"), arrowprops=dict(arrowstyle="->", color="#2e7d32"))
ai.annotate("", xy=(3.5, 94.6), xytext=(K, 94.6), arrowprops=dict(arrowstyle="<->", color="#2e7d32")); ai.text((3.5 + K) / 2, 95.2, "index trend <= 6 candles old", fontsize=9, color="#2e7d32", ha="center")
ai.set_ylim(94, 114)
axT = fig.add_axes([0.55, 0.06, 0.44, 0.84]); axT.axis("off"); axT.set_xlim(0, 10); axT.set_ylim(0, 10)
axT.text(0, 9.9, "The rules, in order", fontsize=13, fontweight="bold", va="top")
axT.text(0, 9.2,
         "1.  OPTION candle k is BIG and green:\n"
         "      body >= 50 % of its range, range >= 1.5x the average\n"
         "      range of the last 10 candles, close at or above EMA20.\n\n"
         "2.  OPTION candle k+1 sits INSIDE k:\n"
         "      its high/low within k (5 % tolerance) and its range <= 60 % of k.\n\n"
         "3.  INDEX chart shows the same picture on the same candles:\n"
         "      candle k is big in our direction (green for CE, red for PE),\n"
         "      range >= 1.0x average, candle k+1 inside it.\n\n"
         "4.  INDEX direction at k+1 agrees (index EMA10 / EMA20) and the\n"
         "      index trend is fresh: <= 6 candles since its EMA cross.\n\n"
         "5.  ENTRY: candle k+2 trades above the high of k+1;\n"
         "      entry price = that high (or the open if it gaps above).\n"
         "      No signal if k+2 never trades above it.\n\n"
         "6.  STOP = low of the BIG candle k   (wide - this is the final version).\n"
         "      TARGET = 3R in the research runs (the live exit set by VIX still to be decided).\n\n"
         "7.  Signals only until the last entry time (14:45).", fontsize=10.5, va="top", linespacing=1.15)
fig.savefig(os.path.join(OUT, "inside_final_setup.png"), dpi=95); plt.close(fig)
print("done")
