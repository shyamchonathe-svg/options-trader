"""Strategy v5 setups - pure functions, no chart/Kite dependency.  Python 3.6+ compatible.

Three families (agreed 24 Nov 2026, see docs/pics/rules_*_v3.png and inside_final_setup.png):

  PULLBACK   hammer + proper green candle on the OPTION chart with the index agreeing.  = the v3 entry with the H1 hammer
             (body .30, close position .65, lower wick .25, red candle before, low touched EMA10 within 6 candles, size
             >= 1.0 x the average range of the last 10 candles WITHOUT spikes), plus
               * FLOATING filter: the whole candle must not float >= FLOAT_MAX average candles above both EMAs
               * OLD-TREND flag: candles since a low last touched EMA20 (>= OLD_FLAG) - LOGGED ONLY, never blocks.
  REVERSAL   long-wick hammer far from the EMAs + strong follow-up candle; trades the snap-back.  Morning (AM) and
             afternoon (PM, after 14:00, EMAs flat).  Stop = low of the follow-up; partial booking and a trailing stop
             (the exit plan is carried in the signal and executed by the engine).
  INSIDE     big green option candle k, inside candle k+1, index shows the same picture on the same candles and its trend
             is fresh; entry when k+2 trades above the high of k+1; stop = low of the big candle k.

Data model as rules_v3: bars dict slot -> {"O","H","L","C"}; e10/e20 indexable by slot.  The signal candle is slot i, the
entry is the OPEN of slot i+1 (pullback / reversal) or the trigger price inside slot i+1... see inside_setup.
Everything looks only at bars <= i (inside_setup: <= k+1).
"""
from trader import rules_v3 as R

SETUPS_VERSION = "v5.0"

# ----------------------------------------------------------------------------- pullback (H1 + floating + old-trend flag)
H1 = dict(body=.30, clv=.65, lw=.25, red=2, touch=6, tol=1.003, size=1.0, spike=2.0)
FLOAT_MAX = 0.5          # reject when the signal candle's low is >= 0.5 average candles above both EMAs
OLD_FLAG = 10            # log flag: >= 10 candles since a low touched EMA20


def avg_range(by, k, n=10, spike=0):
    """Mean range of the previous n candles. spike>0: candles bigger than spike x the window median are left out."""
    v = [by[j]["H"] - by[j]["L"] for j in range(k - n, k) if j in by]
    if not v:
        return 0.0
    if spike:
        s = sorted(v)
        m = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2.0
        w = [x for x in v if x <= spike * m]
        v = w or v
    return sum(v) / float(len(v))


def hammer_ok(by, e10, k, p=H1):
    if k not in by or k - 1 not in by or k - 2 not in by:
        return False
    h = by[k]
    rng = h["H"] - h["L"]
    if rng <= 0:
        return False
    if h["C"] <= h["O"]:
        return False
    body = abs(h["C"] - h["O"])
    if body < p["body"] * rng:
        return False
    if (h["C"] - h["L"]) / rng < p["clv"]:
        return False
    if (min(h["O"], h["C"]) - h["L"]) / rng < p["lw"]:
        return False
    if not any(by[j]["C"] < by[j]["O"] for j in range(k - p["red"], k) if j in by):
        return False
    lows = [by[j]["L"] for j in range(k - p["touch"] + 1, k + 1) if j in by]
    if min(lows) > e10[k] * p["tol"]:
        return False
    if p["size"] and rng < p["size"] * avg_range(by, k, spike=p.get("spike", 0)):
        return False
    return True


def float_gap(by, e10, e20, i):
    """How far the WHOLE candle floats above both EMAs, in average-candle sizes (0 when it still touches one)."""
    lo = by[i]["L"] - max(e10[i], e20[i])
    av = avg_range(by, i, spike=2.0)
    return max(lo, 0.0) / av if av > 0 else 0.0


def old_age(by, e20, i, tol=1.003):
    """Candles since a candle LOW last touched EMA20 (a real pullback resets it; a slow trend hugging EMA10 does not)."""
    j = i
    while j - 1 >= 0 and j - 1 in by and by[j - 1]["L"] > e20[j - 1] * tol:
        j -= 1
    return i - j


def pullback_signal(i, by, e10, e20, ix_dir_i, side, rr=3.0):
    """Option-chart bar i. Same two-phase contract as rules_v3.signal_at: entry None until bar i+1 exists."""
    if i < 3 or i not in by or i - 1 not in by:
        return None
    if ix_dir_i != side:
        return None
    b = by[i]
    if b["C"] <= b["O"] or b["C"] < 0.99 * e10[i] or b["C"] < e20[i] or not e10[i] > e20[i]:
        return None
    hk = i if hammer_ok(by, e10, i) else (i - 1 if hammer_ok(by, e10, i - 1) else None)
    if hk is None:
        return None
    avg = sum(abs(by[j]["C"] - by[j]["O"]) for j in range(i - 5, i) if j in by) / 5.0
    if hk != i and abs(b["C"] - b["O"]) < 0.8 * avg:
        return None
    t_min = R.minute_of(i)
    if t_min > R.LAST_ENTRY_MIN:
        return None
    if float_gap(by, e10, e20, i) >= FLOAT_MAX:
        return None
    age = old_age(by, e20, i)
    sig = {"i": i, "hammer": hk, "midday": R.MIDDAY[0] <= t_min <= R.MIDDAY[1], "t": R.tstr(i), "setup": "pullback",
           "old_age": age, "old_flag": age >= OLD_FLAG}
    if i + 1 not in by:
        sig["entry"] = None
        return sig
    entry = by[i + 1]["O"]
    stop = b["O"]
    note = "stop=signal open"
    rng10 = sum(by[j]["H"] - by[j]["L"] for j in range(i - 9, i + 1) if j in by) / 10.0
    if entry - stop < 0.5 * rng10:
        stop = by[hk]["L"]
        note = "stop=hammer low"
    r = entry - stop
    if r <= 0:
        sig["entry"] = None
        sig["reject"] = "R<=0"
        return sig
    sig.update(entry=entry, stop=stop, R=r, target=entry + rr * r, note=note)
    return sig


# ----------------------------------------------------------------------------- reversal (morning / afternoon)
REVERSAL_AM = dict(mode="am", first=1, last=7, lw=.60, uw=.20, body_f=.60, big_f=1.5, near=.5, hold=3, book=2)
REVERSAL_PM = dict(mode="pm", first=58, last=68, lw=.50, uw=.20, body_f=.60, big_f=1.5, near=.5, hold=6, book=3)
REVERSALS = {"reversal_am": REVERSAL_AM, "reversal_pm": REVERSAL_PM}
REVERSAL_ENABLED = {"reversal_am": True, "reversal_pm": False}    # PM stays off until its 'sideways' test is tuned on examples
REVERSAL_MAX_STEPS = 3.0                                          # strike distance allowed for a reversal (pullback: 0.5)


def reversal_signal(i, by, e10, e20, p, rr=3.0):
    """i = the follow-up candle, i-1 = the long-wick hammer. Entry = open of i+1, stop = low of the follow-up."""
    k = i - 1
    if k < 0 or k not in by or i not in by:
        return None
    if not (p["first"] <= i <= p["last"]):
        return None
    h, f = by[k], by[i]
    rh, rf = h["H"] - h["L"], f["H"] - f["L"]
    if rh <= 0 or rf <= 0:
        return None
    top = max(h["O"], h["C"])
    if (min(h["O"], h["C"]) - h["L"]) / rh < p["lw"] or (h["H"] - top) / rh > p["uw"]:
        return None
    lo_k, hi_k = min(e10[k], e20[k]), max(e10[k], e20[k])
    lo_i, hi_i = min(e10[i], e20[i]), max(e10[i], e20[i])
    if p["mode"] == "am":
        if h["H"] >= lo_k:                      # the hammer must be WAY below both EMAs
            return None
    else:
        if k - 6 < 0 or abs(e20[k] - e20[k - 6]) / e20[k] > 0.004 or (hi_k - lo_k) / e20[k] > 0.006:   # EMAs sideways
            return None
        if h["L"] >= lo_k:
            return None
    if f["C"] <= f["O"] or abs(f["C"] - f["O"]) < p["body_f"] * rf:
        return None
    prev = [by[j]["H"] - by[j]["L"] for j in range(i - 10, i) if j in by]
    if len(prev) >= 5 and rf < p["big_f"] * avg_range(by, i, spike=2.0):
        return None
    if p["mode"] == "am":
        dist = 0.0 if lo_i <= f["C"] <= hi_i else min(abs(f["C"] - lo_i), abs(f["C"] - hi_i))
        if dist > p["near"] * rf:               # closes close to the EMAs
            return None
    elif f["C"] <= hi_i:                        # must close above the EMAs
        return None
    t_min = R.minute_of(i)
    if t_min > R.LAST_ENTRY_MIN:
        return None
    sig = {"i": i, "hammer": k, "midday": False, "t": R.tstr(i), "setup": "reversal_" + p["mode"], "plan": "rev",
           "hold": p["hold"], "book": p["book"]}
    if i + 1 not in by:
        sig["entry"] = None
        return sig
    entry, stop = by[i + 1]["O"], f["L"]
    r = entry - stop
    if r <= 0:
        sig["entry"] = None
        sig["reject"] = "R<=0"
        return sig
    sig.update(entry=entry, stop=stop, R=r, target=entry + rr * r, note="stop=follow-up low")
    return sig


# ----------------------------------------------------------------------------- inside candle
INSIDE_BIG = 1.5         # option candle k range >= 1.5 x average
INSIDE_IBIG = 1.0        # index candle k range >= 1.0 x average
INSIDE_SMALL = 0.6       # candle k+1 range <= 60% of k
INSIDE_FRESH = 6         # index trend at most 6 candles old


def trend_age(ix, ie10, ie20, i, side):
    """(candles since the index trend in `side` began, start slot)."""
    j = i
    while j - 1 in ix and R.index_direction(ix[j - 1]["C"], ie10[j - 1], ie20[j - 1]) == side:
        j -= 1
    return i - j, j


def _inside(by, k, big, need_green, side_for_index=None):
    if k not in by or k + 1 not in by:
        return False
    a, c = by[k], by[k + 1]
    rng = a["H"] - a["L"]
    if rng <= 0:
        return False
    if need_green:
        if a["C"] <= a["O"]:
            return False
    else:
        up = a["C"] > a["O"]
        if (side_for_index == "CE") != up:
            return False
    if abs(a["C"] - a["O"]) < 0.5 * rng:
        return False
    if rng < big * avg_range(by, k):
        return False
    tol = 0.05 * rng
    if c["H"] > a["H"] + tol or c["L"] < a["L"] - tol:
        return False
    return (c["H"] - c["L"]) <= INSIDE_SMALL * rng


def inside_setup(k, by, e10, e20, ix, ie10, ie20, side):
    """Evaluated when candle k+1 has CLOSED. Returns None or {"i": k+1, "trig": high of k+1, "stop": low of k, "k": k}.
    The trade fires only if a later price in slot k+2 trades above `trig` (entry = max(open of k+2, trig))."""
    i = k + 1
    if k < 3 or i not in by or i not in ix or k not in ix:
        return None
    if R.minute_of(i) > R.LAST_ENTRY_MIN:
        return None
    if not _inside(by, k, INSIDE_BIG, True):
        return None
    if by[k]["C"] < e20[k]:
        return None
    if R.index_direction(ix[i]["C"], ie10[i], ie20[i]) != side:
        return None
    age, _ = trend_age(ix, ie10, ie20, k, side)
    if R.index_direction(ix[k]["C"], ie10[k], ie20[k]) == side and age > INSIDE_FRESH:
        return None
    if not _inside(ix, k, INSIDE_IBIG, False, side):
        return None
    trig, stop = by[i]["H"], by[k]["L"]
    if trig - stop <= 0:
        return None
    return {"i": i, "k": k, "trig": trig, "stop": stop, "setup": "inside", "t": R.tstr(i),
            "midday": R.MIDDAY[0] <= R.minute_of(i) <= R.MIDDAY[1]}
