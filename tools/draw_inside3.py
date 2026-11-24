#!/usr/bin/env python3
"""I1 vs I2 vs I4 explained (option + index charts). python3.11 tools/draw_inside3.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pics")
GREEN, RED, BLUE, DR, E10, E20, BG = "#26a69a", "#ef5350", "#0d47a1", "#b71c1c", "#f08a24", "#2e9e4f", "#fafafa"


def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


def draw(ax, bars, title=None):
    cl = [b[3] for b in bars]
    for i, (o, h, l, c) in enumerate(bars):
        col = GREEN if c >= o else RED
        ax.plot([i, i], [l, h], color=col, lw=1.4, zorder=2)
        ax.add_patch(Rectangle((i - .3, min(o, c)), .6, max(abs(c - o), .05), fc=col, ec=col, zorder=3))
    ax.plot(ema(cl, 6), color=E20, lw=1.6, zorder=1); ax.plot(ema(cl, 3), color=E10, lw=1.6, zorder=1)
    ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#cccccc")
    if title: ax.set_title(title, fontsize=10, loc="left", color="#333")


OPT = [(110, 110.3, 107.7, 108), (108, 108.3, 105.7, 106), (106, 106.3, 104.2, 104.5), (104.5, 107.2, 104.3, 107.0),
       (107.0, 109.2, 106.8, 109.0), (109.0, 111.0, 108.8, 110.8), (110.8, 111.2, 110.0, 110.5),
       (110.5, 118.0, 110.2, 117.5), (116.8, 117.6, 114.8, 115.6), (115.8, 121.0, 115.6, 120.6), (120.6, 123.5, 120.4, 123.0)]
K = 7
IDX_PLAIN = [(100, 100.3, 98.6, 99.0), (99.0, 99.2, 97.8, 98.0), (98.0, 98.2, 97.0, 97.2), (97.2, 98.9, 97.1, 98.7), (98.7, 100.2, 98.5, 100.0),
             (100.0, 101.2, 99.9, 101.0), (101.0, 102.3, 100.9, 102.1), (102.1, 103.4, 102.0, 103.3), (103.3, 104.4, 103.1, 104.2), (104.2, 105.3, 104.1, 105.1), (105.1, 106.2, 105.0, 106.0)]
IDX_PAT = list(IDX_PLAIN)
IDX_PAT[K] = (102.1, 106.8, 102.0, 106.5)          # big green on the index too
IDX_PAT[K + 1] = (106.2, 106.7, 104.8, 105.3)      # inside it (red)
IDX_PAT[K + 2] = (105.5, 108.8, 105.4, 108.5)
IDX_PAT[K + 3:] = [(108.5, 109.6, 108.3, 109.4)]

fig = plt.figure(figsize=(18, 11.5)); fig.patch.set_facecolor("white")
fig.suptitle("What really separates I1, I2 and I4   (I3, I5, I6 removed - you rejected them)", fontsize=15, fontweight="bold", x=0.01, ha="left")
fig.text(0.01, 0.925, "ALL THREE share:  option candle k = BIG green (body >= 50 % of range, range >= 1.5x avg10, closes above its EMA20)  +  candle k+1 sits inside k (range <= 60 % of k)  +  entry when k+2 breaks above k+1's high  +  "
         "INDEX direction agrees at k+1 (index EMA10/EMA20)  +  INDEX trend is fresh: <= 6 candles since its EMA cross.", fontsize=10, color="#333", wrap=True)
cols = [("I1", "index: direction + freshness only", False, "in"), ("I2", "index must ALSO show the same big + inside pattern", True, "in"), ("I4", "like I2, but a much WIDER stop", True, "big")]
for n, (code, sub, idxpat, stop) in enumerate(cols):
    x0 = 0.015 + n * 0.328
    ax = fig.add_axes([x0, 0.50, 0.31, 0.37]); ax_i = fig.add_axes([x0, 0.255, 0.31, 0.19]); ax_t = fig.add_axes([x0, 0.02, 0.31, 0.19]); ax_t.axis("off")
    draw(ax, OPT, "OPTION chart")
    draw(ax_i, IDX_PAT if idxpat else IDX_PLAIN, "INDEX chart (same candles k, k+1, k+2)")
    ax.set_ylim(100, 142)
    fig.text(x0, 0.895, "%s   %s" % (code, sub), fontsize=12, fontweight="bold")
    kb, ib = OPT[K], OPT[K + 1]
    entry = ib[1]; stp = ib[2] if stop == "in" else kb[2]; R = entry - stp
    ax.annotate("k BIG green", xy=(K, kb[1]), xytext=(K - 3.2, 132), fontsize=9, ha="center", color=BLUE, bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
    ax.annotate("k+1 inside", xy=(K + 1, ib[2]), xytext=(K + 0.6, 103), fontsize=9, ha="center", color="#555", bbox=dict(boxstyle="round", fc="white", ec="#777"), arrowprops=dict(arrowstyle="->", color="#555"))
    ax.plot([K - 0.6, 10.6], [stp, stp], ls="--", color=DR, lw=1.4); ax.text(K - 0.6, stp - 0.5, "STOP (low of %s)" % ("k+1" if stop == "in" else "k"), color=DR, fontsize=9, va="top")
    ax.plot([K + 1.6, 10.6], [entry, entry], color=BLUE, lw=1.0, ls=":"); ax.text(10.6, entry + 0.4, "entry %.1f" % entry, color=BLUE, fontsize=9, ha="right")
    tgt = entry + 3 * R
    ax.plot([K + 1.6, 10.6], [min(tgt, 141), min(tgt, 141)], color="#2e7d32", lw=1.0, ls=":")
    ax.text(10.6, min(tgt, 141) - 0.4, "3R target %.1f" % tgt, color="#2e7d32", fontsize=9, ha="right", va="top")
    ax.annotate("", xy=(10.9, entry), xytext=(10.9, stp), arrowprops=dict(arrowstyle="<->", color=DR))
    ax.text(11.1, (entry + stp) / 2, "risk\n%.1f" % R, color=DR, fontsize=9, va="center")
    ax.set_xlim(-0.6, 12.2)
    if idxpat:
        ax_i.annotate("index also BIG + inside", xy=(K, IDX_PAT[K][1]), xytext=(2.6, 107.6), fontsize=9, ha="center", color="#2e7d32", bbox=dict(boxstyle="round", fc="white", ec="#2e7d32"), arrowprops=dict(arrowstyle="->", color="#2e7d32"))
    else:
        ax_i.text(0.03, 0.9, "only the EMAs matter here:\nEMA10 > EMA20 and cross <= 6 candles ago.\nIndex candles can look like anything.", transform=ax_i.transAxes, fontsize=9, color="#555", va="top")
    txt = {"I1": "WHAT IT NEEDS\n option pattern  +  index direction/fresh\nMOST signals (fewest conditions)\nSTOP tight: low of the inside candle\nrisk %.1f  ->  3R target close by" % R,
           "I2": "WHAT IT NEEDS\n everything in I1  +  the INDEX chart has\n its own big green candle k and an inside k+1\n (index range >= 1.0x avg10)\nFEWER signals, same tight stop (risk %.1f)" % R,
           "I4": "WHAT IT NEEDS\n same filters as I2\nONLY the stop differs: low of the BIG candle k\nrisk %.1f vs %.1f  (%.1fx bigger)\n3R target %.1f is far away, so it hits less often" % (R, ib[1] - ib[2], R / (ib[1] - ib[2]), tgt)}[code]
    ax_t.text(0, 0.95, txt, fontsize=10, va="top", bbox=dict(boxstyle="round", fc="#fffde7", ec="#f9a825"))
fig.savefig(os.path.join(OUT, "research_inside_I1_I2_I4.png"), dpi=95); plt.close(fig)
print("done")
