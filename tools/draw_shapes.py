#!/usr/bin/env python3
"""Hammer shapes (2 images) + inside-candle variants with EMA. python3.11 tools/draw_shapes.py [outdir]"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from trader import research as RS

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "docs", "pics")
GREEN, RED, BLUE, DR, E10, E20, BG = "#26a69a", "#ef5350", "#0d47a1", "#b71c1c", "#f08a24", "#2e9e4f", "#fafafa"
LAB = dict(lw=.45, body=.47, uw=.08)   # median of the 28 labelled hammers


def candle(ax, x, lw, body, uw, col, w=0.5, ls="-", fill=True, lwid=3):
    ax.plot([x, x], [0, lw + body + uw], color=col, lw=lwid, ls=ls, zorder=2)
    ax.add_patch(Rectangle((x - w / 2, lw), w, max(body, 0.015), fc=col if fill else "none", ec=col, lw=1.5, ls=ls, zorder=3))


def shapes(p):
    lw = p["lw"]
    if p["body"] == 0:
        return None
    thin = max(p["body"], p["clv"] - lw)
    thin = min(thin, 1 - lw)
    fat = min(p.get("bmax", 1 - lw), 1 - lw)
    fat = max(fat, thin)
    return (lw, thin, max(0.0, 1 - lw - thin)), (lw, fat, max(0.0, 1 - lw - fat))


def passes(p, lw=LAB["lw"], body=LAB["body"], uw=LAB["uw"]):
    if p["body"] == 0: return True, "any candle passes"
    why = []
    if body < p["body"]: why.append("body too thin")
    if "bmax" in p and body > p["bmax"]: why.append("body too fat (max %d%%)" % (p["bmax"] * 100))
    if lw < p["lw"]: why.append("wick too short (needs %d%%)" % (p["lw"] * 100))
    if (lw + body) < p["clv"]: why.append("closes too low")
    if "uw" in p and uw > p["uw"]: why.append("upper wick too long")
    return (not why), ", ".join(why)


def cell(ax, name, p, note=""):
    ax.set_xlim(-0.8, 3.6); ax.set_ylim(-0.12, 1.12); ax.axis("off")
    ax.add_patch(Rectangle((-0.78, -0.1), 4.34, 1.2, fc="#fafafa", ec="#cfcfcf", zorder=0))
    ax.plot([-0.5, 3.4], [0, 0], color="#999", lw=0.8, ls=":"); ax.plot([-0.5, 3.4], [1, 1], color="#999", lw=0.8, ls=":")
    ax.text(3.45, 1.0, "high", fontsize=8, color="#888", ha="right", va="bottom"); ax.text(3.45, 0.0, "low", fontsize=8, color="#888", ha="right", va="top")
    sh = shapes(p)
    col = "#9e9e9e" if p.get("anycolor") else GREEN
    if sh is None:
        ax.text(0.9, 0.5, "NO shape test\n(any candle passes)", ha="center", va="center", fontsize=13, color="#777")
    else:
        a = sh[0]
        candle(ax, 0.5, *a, col)
        ax.text(0.5, 1.04, "LOOSEST candle\nthis rule accepts", ha="center", fontsize=9.5, va="bottom", color="#1b5e20")
        ax.annotate("", xy=(0.95, 0), xytext=(0.95, a[0]), arrowprops=dict(arrowstyle="<->", color=DR, lw=1.3))
        ax.text(1.03, a[0] / 2, "wick >= %d%%" % (p["lw"] * 100), color=DR, fontsize=10, va="center")
    ok, why = passes(p)
    candle(ax, 2.9, LAB["lw"], LAB["body"], LAB["uw"], "#555", fill=False, ls="--", lwid=1.8)
    ax.text(2.9, 1.04, "YOUR typical\nlabelled hammer", ha="center", fontsize=9.5, va="bottom", color="#555")
    ax.text(2.0, 0.5, "PASS" if ok else "FAIL", fontsize=16, fontweight="bold", color="#2e7d32" if ok else DR, ha="center", va="center")
    if not ok: ax.text(2.0, 0.38, why, fontsize=8.5, color=DR, ha="center", va="top")
    ax.text(-0.7, -0.09, note, fontsize=10, va="top")


def note(p):
    if p["body"] == 0:
        return "touch 6   size off"
    s = "body >= %d%%" % (p["body"] * 100)
    if "bmax" in p: s += " (<= %d%%)" % (p["bmax"] * 100)
    s += "   close in top %d%%" % round((1 - p["clv"]) * 100)
    if "uw" in p: s += "   upper wick <= %d%%" % (p["uw"] * 100)
    s += "\nlow within 0.3%% of EMA10 in last %d candles   size %s%s" % (p["touch"], "range>=1.0x avg10" if p["size"] else "off", "   ANY colour" if p.get("anycolor") else "")
    return s


items = list(RS.HAMMERS.items())
groups = [("HAMMER shapes, part 1: the v3 family  (H0 - H5)", items[:6], "research_shapes_1.png"),
          ("HAMMER shapes, part 2: baseline and 'classic' family  (H6 - H9)", items[6:], "research_shapes_2.png")]
for title, its, fn in groups:
    fig, axs = plt.subplots(2, 3, figsize=(18, 11)); fig.patch.set_facecolor("white")
    fig.suptitle(title + "\nGREEN = loosest candle the rule accepts.  DASHED = your typical labelled hammer, and whether the rule lets it through."+"", fontsize=14, fontweight="bold", x=0.01, ha="left")
    for a in axs.ravel(): a.axis("off")
    for a, (name, p) in zip(axs.ravel(), its):
        cell(a, name, p, note(p))
        a.set_title(name, fontsize=13, fontweight="bold", loc="left", pad=34)
    plt.subplots_adjust(hspace=0.45, wspace=0.12, top=0.82, bottom=0.04, left=0.02, right=0.99)
    fig.savefig(os.path.join(OUT, fn), dpi=95); plt.close(fig)

# ====================================================================== inside variants with EMA
def ema(v, n):
    a = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = a * x + (1 - a) * e; o.append(e)
    return o


def draw(ax, bars, e10, e20):
    for i, (o, h, l, c) in enumerate(bars):
        col = GREEN if c >= o else RED
        ax.plot([i, i], [l, h], color=col, lw=1.4, zorder=2)
        ax.add_patch(Rectangle((i - .3, min(o, c)), .6, max(abs(c - o), .05), fc=col, ec=col, zorder=3))
    ax.plot(e20, color=E20, lw=1.6, zorder=1); ax.plot(e10, color=E10, lw=1.6, zorder=1)
    ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#cccccc")


# near-cross scenario (fresh trend): dip, EMA10 crosses above EMA20 4 candles before k
near = [(110, 110.3, 107.7, 108), (108, 108.3, 105.7, 106), (106, 106.3, 104.2, 104.5), (104.5, 107.2, 104.3, 107.0),
        (107.0, 109.2, 106.8, 109.0), (109.0, 111.0, 108.8, 110.8), (110.8, 111.2, 110.0, 110.5),
        (110.5, 118.0, 110.2, 117.5),   # k  (idx7) big green
        (116.8, 117.6, 114.8, 115.6),   # k+1 inside, red
        (115.8, 121.0, 115.6, 120.6), (120.6, 123.5, 120.4, 123.0)]
ne10 = ema([b[3] for b in near], 3); ne20 = ema([b[3] for b in near], 6)
# any-time scenario: long old trend (12+ candles), k appears late
old = []; p = 100.0
for i in range(11):
    old.append((p, p + 1.4, p - 0.3, p + 1.2)); p += 1.2
old += [(p, p + 6.5, p - 0.3, p + 6.2), (p + 5.6, p + 6.4, p + 3.9, p + 4.6), (p + 4.8, p + 10.0, p + 4.6, p + 9.6), (p + 9.6, p + 12.0, p + 9.4, p + 11.6)]
oe10 = ema([b[3] for b in old], 3); oe20 = ema([b[3] for b in old], 6)
K_NEAR, K_OLD = 7, 11


def idx_strip(ax, mode, agree_label):
    ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#cccccc")
    if mode == "off":
        ax.text(0.5, 0.5, "INDEX chart ignored", ha="center", va="center", fontsize=10, color="#777", transform=ax.transAxes)
        return
    import math
    x = list(range(11)); y = [100 + 1.2 * i + 0.4 * math.sin(i) for i in x]
    ax.plot(x, [v - 1.0 for v in y], color=E20, lw=1.5); ax.plot(x, [v + 0.1 for v in y], color=E10, lw=1.5)
    ax.plot(x, [v + 0.6 for v in y], color="#1565c0", lw=1.0, alpha=.7)
    ax.text(0.02, 0.8, "INDEX: EMA10 > EMA20 (agrees)  " + agree_label, fontsize=9.5, color="#2e7d32", transform=ax.transAxes, va="center")


combos = [("I1", "option only, near cross, SL inside", dict(scn="near", idx="off", stop="in", lab="")),
          ("I2", "option + index, near cross, SL inside", dict(scn="near", idx="on", stop="in", lab="(big candle too)")),
          ("I3", "option + index, ANY time, SL inside", dict(scn="old", idx="on", stop="in", lab="(big candle too)")),
          ("I4", "option + index, near cross, WIDE stop", dict(scn="near", idx="on", stop="big", lab="(big candle too)")),
          ("I5", "option only, ANY time, SL inside", dict(scn="old", idx="off", stop="in", lab="")),
          ("I6", "option + index(any size), ANY time, SL inside", dict(scn="old", idx="on", stop="in", lab="(any size ok)"))]
fig = plt.figure(figsize=(19, 12.5)); fig.patch.set_facecolor("white")
fig.suptitle("INSIDE-candle variants  (option chart with EMA10 orange / EMA20 green; invented candles)", fontsize=15, fontweight="bold", x=0.01, ha="left")
for n, (code, desc, c) in enumerate(combos):
    col, row = n % 3, n // 3
    x0 = 0.015 + col * 0.328; y0 = 0.53 - row * 0.47
    ax = fig.add_axes([x0, y0 + 0.07, 0.31, 0.33]); ax2 = fig.add_axes([x0, y0, 0.31, 0.055])
    bars, e10, e20, k = (near, ne10, ne20, K_NEAR) if c["scn"] == "near" else (old, oe10, oe20, K_OLD)
    draw(ax, bars, e10, e20)
    lo = min(b[2] for b in bars) - 1; hi = max(b[1] for b in bars) + 4
    ax.set_ylim(lo, hi)
    ax.set_title("%s   %s" % (code, desc), fontsize=11.5, fontweight="bold", loc="left")
    kb, ib, tb = bars[k], bars[k + 1], bars[k + 2]
    ax.annotate("k  BIG green\n(>= 1.5x avg10)", xy=(k, kb[1]), xytext=(k - 2.8, hi - 2.0), fontsize=9, ha="center", color=BLUE,
                bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
    ax.annotate("k+1 inside", xy=(k + 1, ib[1]), xytext=(k + 1.3, lo + 1.5 if c["scn"] == "near" else lo + 3), fontsize=9, ha="center", color="#555",
                bbox=dict(boxstyle="round", fc="white", ec="#777"), arrowprops=dict(arrowstyle="->", color="#555"))
    ax.annotate("ENTRY: k+2 breaks\nabove k+1 high", xy=(k + 2, ib[1]), xytext=(k + 2.0, hi - 0.5), fontsize=9, ha="center", color=BLUE, va="top",
                bbox=dict(boxstyle="round", fc="white", ec=BLUE), arrowprops=dict(arrowstyle="->", color=BLUE))
    sly = ib[2] if c["stop"] == "in" else kb[2]
    ax.plot([k - 0.5, k + 3.2], [sly, sly], ls="--", color=DR, lw=1.4)
    ax.text(k + 3.2, sly - 0.3, "SL: low of %s" % ("k+1" if c["stop"] == "in" else "k (wide)"), color=DR, fontsize=9, ha="right", va="top")
    # trend age marker
    cross = 3 if c["scn"] == "near" else 0
    if c["scn"] == "near":
        ax.annotate("", xy=(cross + 0.5, lo + 0.5), xytext=(k, lo + 0.5), arrowprops=dict(arrowstyle="<->", color="#2e7d32"))
        ax.text((cross + 0.5 + k) / 2, lo + 0.9, "trend fresh: <= 6 candles", fontsize=9, color="#2e7d32", ha="center")
    else:
        ax.annotate("", xy=(0, lo + 0.5), xytext=(k, lo + 0.5), arrowprops=dict(arrowstyle="<->", color="#e65100"))
        ax.text(k / 2, lo + 1.0, "trend already 10+ candles old (allowed)", fontsize=9, color="#e65100", ha="center")
    idx_strip(ax2, c["idx"], c["lab"])
fig.savefig(os.path.join(OUT, "research_inside_variants.png"), dpi=95); plt.close(fig)
print("done")
