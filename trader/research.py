"""Research harness (SHADOW ONLY - never trades, never touches rules_v3).  Python 3.6 compatible.

Runs many candidate setups over the same stored candles and measures what each would have done, with the same
entry/stop/3R/12-candle exit mechanics as v3, so formulas can be compared like the exit variants A..E.

Setups
  HAMMER family  H0..H6 : v3 signal rules with the hammer test swapped for a different formula.
  INSIDE family  I1..I4 : big candle + small candle fully inside it, on the option (and on the index), near the crossover.
Every signal also records CONTEXT: how old the index/option trend is and how far each has already moved.
"""
from trader import rules_v3 as R, rules_v4 as V4

# ---------------------------------------------------------------- hammer formulas
HAMMERS = {
    "H0 v3 (current)":        dict(body=.30, clv=.65, lw=.25, red=2, touch=6, tol=1.003, size=0),
    "H1 v3 + min size":       dict(body=.30, clv=.65, lw=.25, red=2, touch=6, tol=1.003, size=1.0, spike=2.0),
    "P1 H1 + float<0.5 (old-trend = log flag)": dict(body=.30, clv=.65, lw=.25, red=2, touch=6, tol=1.003, size=1.0, spike=2.0, floatgap=0.5),
    "H2 touch EMA10 now":     dict(body=.30, clv=.65, lw=.25, red=2, touch=2, tol=1.003, size=0),
    "H3 long wick (40%)":     dict(body=.30, clv=.65, lw=.40, red=2, touch=6, tol=1.003, size=0),
    "H4 small hammer":        dict(body=.15, clv=.60, lw=.15, red=2, touch=6, tol=1.003, size=0),
    "H5 strict":              dict(body=.25, clv=.75, lw=.35, red=2, touch=3, tol=1.003, size=1.0),
    "H6 no hammer (baseline)": dict(body=0.0, clv=0.0, lw=0.0, red=2, touch=6, tol=1.003, size=0),
    # classic hammer shape: small body at the top, lower wick >= half the range, almost no upper wick
    "H7 classic hammer":       dict(body=.10, bmax=.35, clv=.65, lw=.50, uw=.15, red=2, touch=6, tol=1.003, size=0),
    "H8 classic, any colour":  dict(body=.05, bmax=.35, clv=.65, lw=.50, uw=.15, red=2, touch=6, tol=1.003, size=0, anycolor=True),
    "H9 classic (wick 40%)":   dict(body=.10, bmax=.40, clv=.65, lw=.40, uw=.20, red=2, touch=6, tol=1.003, size=0),
}


def _avg_range(by, k, n=10, spike=0):
    """Mean range of the previous n candles. spike>0: candles bigger than spike x the window median are
    left out, so one big candle just before a hammer cannot inflate the reference (H1)."""
    v = [by[j]["H"] - by[j]["L"] for j in range(k - n, k) if j in by]
    if not v: return 0.0
    if spike:
        m = sorted(v)[len(v) // 2] if len(v) % 2 else sum(sorted(v)[len(v) // 2 - 1:len(v) // 2 + 1]) / 2.0
        w = [x for x in v if x <= spike * m]
        v = w or v
    return sum(v) / float(len(v))


def hammer_ok(by, e10, k, p):
    if k not in by or k - 1 not in by or k - 2 not in by: return False
    h = by[k]; rng = h["H"] - h["L"]
    if rng <= 0: return False
    if not p.get("anycolor") and h["C"] <= h["O"]: return False
    body = abs(h["C"] - h["O"])
    if body < p["body"] * rng or body > p.get("bmax", 1.0) * rng: return False
    if (h["H"] - max(h["O"], h["C"])) > p.get("uw", 1.0) * rng: return False
    if (h["C"] - h["L"]) / rng < p["clv"]: return False
    if (min(h["O"], h["C"]) - h["L"]) / rng < p["lw"]: return False
    if not any(by[j]["C"] < by[j]["O"] for j in range(k - p["red"], k) if j in by): return False
    lows = [by[j]["L"] for j in range(k - p["touch"] + 1, k + 1) if j in by]
    if min(lows) > e10[k] * p["tol"]: return False
    if p["size"] and rng < p["size"] * _avg_range(by, k, spike=p.get("spike", 0)): return False
    return True


# ---------------------------------------------------------------- context (how late are we?)
def trend_age(ix, ie10, ie20, i, side):
    """(candles since the index trend in `side` began, start slot).  start 0 = already on at the open (carried)."""
    j = i
    while j - 1 in ix and R.index_direction(ix[j - 1]["C"], ie10[j - 1], ie20[j - 1]) == side: j -= 1
    return i - j, j


def option_age(by, e10, e20, i):
    k = i
    while k - 1 in by and e10[k - 1] > e20[k - 1] and by[k - 1]["C"] > e20[k - 1]: k -= 1
    return i - k, k


def context(ix, ie10, ie20, by, e10, e20, i, side):
    ia, ij = trend_age(ix, ie10, ie20, i, side)
    oa, ok = option_age(by, e10, e20, i)
    st = ix[max(ij, 0)]["O"]
    imv = (ix[i]["C"] - st) * (1 if side == "CE" else -1) / st * 100.0
    ob = by[max(ok, 0)]["O"]
    omv = (by[i]["C"] / ob - 1.0) * 100.0 if ob else 0.0
    return dict(idx_age=ia, opt_age=oa, idx_move=imv, opt_move=omv, carried=(ij <= 0 or ok <= 0))


# ---------------------------------------------------------------- setups
def ema_age(by, e10, e20, i, tol=1.003):
    """Age of the move: candles since a candle LOW last touched EMA20.  A real pullback (A, B) dips to EMA20, so
    it resets the age; a slow trend that only hugs EMA10 (C1) never does, so it keeps ageing."""
    j = i
    while j - 1 >= 0 and j - 1 in by and by[j - 1]["L"] > e20[j - 1] * tol: j -= 1
    return i - j


def float_gap(by, e10, e20, i):
    """How far the WHOLE candle floats above both EMAs, in average-candle sizes (0 if it still touches one)."""
    lo = by[i]["L"] - max(e10[i], e20[i])
    av = _avg_range(by, i, spike=2.0)
    return max(lo, 0.0) / av if av > 0 else 0.0


def hammer_signal(i, by, e10, e20, dirn, side, p, rr=3.0):
    """v3 signal_at with a swappable hammer formula.  Returns dict(i, entry, stop, entry_slot) or None."""
    if i < 3 or i not in by or i - 1 not in by or i + 1 not in by: return None
    if dirn != side: return None
    b = by[i]
    if b["C"] <= b["O"] or b["C"] < 0.99 * e10[i] or b["C"] < e20[i] or not e10[i] > e20[i]: return None
    hk = i if hammer_ok(by, e10, i, p) else (i - 1 if hammer_ok(by, e10, i - 1, p) else None)
    if hk is None: return None
    avg = sum(abs(by[j]["C"] - by[j]["O"]) for j in range(i - 5, i) if j in by) / 5.0
    if hk != i and abs(b["C"] - b["O"]) < 0.8 * avg: return None
    if R.minute_of(i) > R.LAST_ENTRY_MIN: return None
    if p.get("young") and ema_age(by, e10, e20, i) >= p["young"]: return None          # C1: old slow trend = exhaustion
    if p.get("floatgap") and float_gap(by, e10, e20, i) >= p["floatgap"]: return None   # C2: starting to float
    entry, stop = by[i + 1]["O"], b["O"]
    rng10 = sum(by[j]["H"] - by[j]["L"] for j in range(i - 9, i + 1) if j in by) / 10.0
    if entry - stop < 0.5 * rng10: stop = by[hk]["L"]
    if entry - stop <= 0: return None
    return dict(i=i, entry=entry, stop=stop)


REVERSAL = {
    # hammer at k (long lower wick), strong follow-up candle i=k+1; entry open of i+1; stop = low of the follow-up.
    "RV-AM morning":   dict(mode="am", first=1, last=7,  lw=.60, uw=.20, body_f=.60, big_f=1.5, near=.5, hold=3, book=2),
    "RV-PM afternoon": dict(mode="pm", first=58, last=68, lw=.50, uw=.20, body_f=.60, big_f=1.5, near=.5, hold=6, book=3),
}


def reversal_exit(p):
    def run(by, i, entry, stop, rr=None):
        R_ = entry - stop; e = i + 1; trail = stop; booked = False; part = 0.0; last = None
        for n in range(p["hold"]):
            j = e + n
            if j not in by: break
            b = by[j]; last = j
            if b["L"] <= trail:
                if not booked: return -1.0, j, "stop"
                r = 0.5 * part + 0.5 * (trail - entry) / R_
                return r, j, ("target" if r > 0 else "stop")
            if not booked and n + 1 == p["book"]:
                part = (b["C"] - entry) / R_; booked = True
            if booked: trail = max(trail, b["L"])          # aggressive: stop moves to the low of the candle just closed
        if last is None: return 0.0, e, "time"
        c = (by[last]["C"] - entry) / R_
        r = 0.5 * part + 0.5 * c if booked else c
        return r, last, ("target" if r > 0 else "time")
    return run


def reversal_signal(i, by, e10, e20, p, rr=3.0):
    k = i - 1
    if k < 0 or k not in by or i not in by or i + 1 not in by: return None
    if not (p["first"] <= i <= p["last"]): return None
    h, f = by[k], by[i]
    rh, rf = h["H"] - h["L"], f["H"] - f["L"]
    if rh <= 0 or rf <= 0: return None
    top = max(h["O"], h["C"])
    if (min(h["O"], h["C"]) - h["L"]) / rh < p["lw"] or (h["H"] - top) / rh > p["uw"]: return None
    lo_k, hi_k = min(e10[k], e20[k]), max(e10[k], e20[k])
    lo_i, hi_i = min(e10[i], e20[i]), max(e10[i], e20[i])
    if p["mode"] == "am":
        if h["H"] >= lo_k: return None                       # the hammer must be WAY below both EMAs
    else:
        if k - 6 < 0 or abs(e20[k] - e20[k - 6]) / e20[k] > 0.004 or (hi_k - lo_k) / e20[k] > 0.006: return None   # EMAs sideways
        if h["L"] >= lo_k: return None
    if f["C"] <= f["O"] or abs(f["C"] - f["O"]) < p["body_f"] * rf: return None
    prev = [by[j]["H"] - by[j]["L"] for j in range(i - 10, i) if j in by]
    if len(prev) >= 5 and rf < p["big_f"] * _avg_range(by, i, spike=2.0): return None
    if p["mode"] == "am":
        dist = 0.0 if lo_i <= f["C"] <= hi_i else min(abs(f["C"] - lo_i), abs(f["C"] - hi_i))
        if dist > p["near"] * rf: return None                # closes close to the EMAs
    elif f["C"] <= hi_i: return None                         # must close above the EMAs
    entry, stop = by[i + 1]["O"], f["L"]
    if entry - stop <= 0: return None
    return dict(i=i, entry=entry, stop=stop, exit=reversal_exit(p), nogap=True)


INSIDE = {
    "I1 option only, near cross":     dict(index=False, fresh=6, stop="inside", big=1.5, ibig=0),
    "I2 option+index, near cross":    dict(index=True,  fresh=6, stop="inside", big=1.5, ibig=1.0),
    "I3 option+index, any time":      dict(index=True,  fresh=999, stop="inside", big=1.5, ibig=1.0),
    "I4 option+index, near cross, wide stop": dict(index=True, fresh=6, stop="big", big=1.5, ibig=1.0),
    "I5 option only, any time":       dict(index=False, fresh=999, stop="inside", big=1.5, ibig=0),
    "I6 option+index(any size), any time": dict(index=True, fresh=999, stop="inside", big=1.5, ibig=0),
}


def _inside(by, k, big, need_green, side_for_index=None, small=0.6):
    """Candle k is a big candle and candle k+1 sits inside it.  need_green: option (True) / index uses the side."""
    if k not in by or k + 1 not in by: return False
    a, c = by[k], by[k + 1]
    rng = a["H"] - a["L"]
    if rng <= 0: return False
    if need_green:
        if a["C"] <= a["O"]: return False
    else:
        up = a["C"] > a["O"]
        if (side_for_index == "CE") != up: return False
    if abs(a["C"] - a["O"]) < 0.5 * rng: return False
    if rng < big * _avg_range(by, k): return False
    tol = 0.05 * rng
    if c["H"] > a["H"] + tol or c["L"] < a["L"] - tol: return False
    return (c["H"] - c["L"]) <= small * rng


def inside_signal(k, by, e10, e20, ix, ie10, ie20, side, p, rr=3.0):
    """Big candle k, inside candle k+1, entry when k+2 breaks above k+1's high.  Signal slot reported = k+1."""
    i = k + 1
    if k < 3 or k + 2 not in by or i not in ix or k not in ix: return None
    if R.minute_of(i) > R.LAST_ENTRY_MIN: return None
    if not _inside(by, k, p["big"], True, None, p.get("small", 0.6)): return None
    if by[k]["C"] < e20[k]: return None
    if R.index_direction(ix[i]["C"], ie10[i], ie20[i]) != side: return None
    age, _ = trend_age(ix, ie10, ie20, k, side)
    if R.index_direction(ix[k]["C"], ie10[k], ie20[k]) == side and age > p["fresh"]: return None
    if p["index"] and not _inside(ix, k, p["ibig"], False, side, p.get("small", 0.6)): return None
    trig = by[i]["H"]
    nxt = by[k + 2]
    if nxt["H"] < trig: return None                      # never triggered
    entry = max(nxt["O"], trig)
    stop = by[i]["L"] if p["stop"] == "inside" else by[k]["L"]
    if entry - stop <= 0: return None
    return dict(i=i, entry=entry, stop=stop)


# ---------------------------------------------------------------- parameter grids (broad search; rank on research days, verify on live days)
def hammer_grid():
    g = {}
    for body in (.15, .30):
        for clv in (.60, .65, .75):
            for lw in (.15, .25, .40):
                for touch in (2, 3, 6):
                    for size in (0, 1.0):
                        n = "g-ham body%d clv%d wick%d touch%d size%s" % (body * 100, clv * 100, lw * 100, touch, "on" if size else "off")
                        g[n] = dict(body=body, clv=clv, lw=lw, red=2, touch=touch, tol=1.003, size=size)
    for lw in (.50, .60):
        for bmax in (.35, .50):
            for uw in (.10, .20):
                for touch in (3, 6):
                    for size in (0, 1.0):
                        n = "g-ham classic wick%d bodymax%d uwmax%d touch%d size%s" % (lw * 100, bmax * 100, uw * 100, touch, "on" if size else "off")
                        g[n] = dict(body=.10, bmax=bmax, clv=.65, lw=lw, uw=uw, red=2, touch=touch, tol=1.003, size=size)
    return g


def inside_grid():
    g = {}
    for big in (1.2, 1.5, 2.0):
        for small in (0.4, 0.6, 0.8):
            for fresh in (3, 6, 12, 999):
                for index in (False, True):
                    for stop in ("inside", "big"):
                        n = "g-ins big%.1f small%.1f fresh%s %s stop-%s" % (big, small, fresh if fresh < 999 else "any",
                                                                          "opt+idx" if index else "opt", stop)
                        g[n] = dict(index=index, fresh=fresh, stop=stop, big=big, ibig=1.0 if index else 0, small=small)
    return g


# ---------------------------------------------------------------- driver
def run_case(case, rr=3.0, hammers=None, insides=None, use_gap=True, reversals=None):
    """case: dict(day, index, step, prev_close, ix=(by,e10,e20), opts={name:(by,e10,e20,strike,side)}).
    Returns list of result rows (one per signal) for every setup."""
    ix, ie10, ie20 = case["ix"]
    first = min(k for k in ix if k >= 0)
    gap, gside = R.gap_side(ix[first]["O"], case["prev_close"])
    rows = []
    hammers = HAMMERS if hammers is None else hammers
    insides = INSIDE if insides is None else insides
    reversals = {} if reversals is None else reversals

    def finish(setup, name, strike, side, by, e10, e20, sg):
        i = sg["i"]
        ip = ix.get(i + 1, ix.get(i))["O"]
        dist = abs(ip - strike) / float(case["step"])
        blocked = bool(gside and side != gside) and not sg.get("nogap")   # reversals trade AGAINST a gap on purpose
        blocked_rec = blocked and not V4.gap_lifted(gside, case["prev_close"], ix, i)
        if dist > R.MAX_DIST_STEPS or (use_gap and (blocked_rec if use_gap == "recover" else blocked)): return None
        res, j, why = (sg["exit"] if "exit" in sg else R.simulate_exit)(by, i, sg["entry"], sg["stop"], rr)
        c = context(ix, ie10, ie20, by, e10, e20, i, side)
        c.update(old_age=ema_age(by, e10, e20, i), old_flag=ema_age(by, e10, e20, i) >= 10, setup=setup, day=case["day"], index=case["index"], name=name, side=side, t=R.tstr(i + 1),
                 slot=i, midday=R.MIDDAY[0] <= R.minute_of(i) <= R.MIDDAY[1], R=res, why=why,
                 risk_pct=100.0 * (sg["entry"] - sg["stop"]) / sg["entry"], gap_blocked=blocked, gap_blocked_rec=blocked_rec, gap=gap)
        return c

    for name, (by, e10, e20, strike, side) in case["opts"].items():
        for setup, p in hammers.items():
            busy = -1
            for i in range(3, 68):
                if i <= busy or i not in by or i not in ix: continue
                d = R.index_direction(ix[i]["C"], ie10[i], ie20[i])
                sg = hammer_signal(i, by, e10, e20, d, side, p, rr)
                if not sg: continue
                r = finish(setup, name, strike, side, by, e10, e20, sg)
                busy = i + 1
                if r: rows.append(r)
        for setup, p in reversals.items():
            busy = -1
            for i in range(1, 69):
                if i <= busy or i not in by or i not in ix: continue
                sg = reversal_signal(i, by, e10, e20, p, rr)
                if not sg: continue
                r = finish(setup, name, strike, side, by, e10, e20, sg)
                busy = i + p["hold"] + 1
                if r: rows.append(r)
        for setup, p in insides.items():
            busy = -1
            for k in range(3, 66):
                if k + 1 <= busy: continue
                sg = inside_signal(k, by, e10, e20, ix, ie10, ie20, side, p, rr)
                if not sg: continue
                r = finish(setup, name, strike, side, by, e10, e20, sg)
                busy = k + 2
                if r: rows.append(r)
    return rows


def summarize(rows, title, filt=lambda r: True):
    sel = [r for r in rows if filt(r)]
    setups = []
    for r in sel:
        if r["setup"] not in setups: setups.append(r["setup"])
    out = [title, "%-40s %4s %4s %4s %4s %6s %7s %7s" % ("setup", "n", "win", "stop", "time", "win%", "avgR", "sumR")]
    for s in sorted(setups):
        x = [r for r in sel if r["setup"] == s]
        w = sum(1 for r in x if r["why"] == "target"); st = sum(1 for r in x if r["why"] == "stop")
        tm = len(x) - w - st; tot = sum(r["R"] for r in x)
        out.append("%-40s %4d %4d %4d %4d %5.0f%% %7.2f %7.1f" % (s, len(x), w, st, tm, 100.0 * w / len(x), tot / len(x), tot))
    return "\n".join(out)
