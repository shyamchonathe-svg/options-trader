"""Strategy v3 rules - pure functions, no chart/Kite dependency.  Python 3.6+ compatible.

Data model (same as the research code):
  bars : dict  idx -> {"O","H","L","C"}   idx 0 = 09:15 bar, 5-minute slots (idx = (minutes since 09:15)/5)
  e10, e20 : EMA10 / EMA20 of CLOSE, indexable by idx (list or dict); seeded with previous-session bars.

The SAME functions are used (a) by the replay/backtest harness and (b) by the live runner.
Everything here looks only at bars <= i when deciding a signal at bar i; the entry is the OPEN of bar i+1.
"""
import re

GAP_TH = 0.0025          # |gap| >= 0.25% of previous close -> only the gap side is allowed
MAX_DIST_STEPS = 1.5     # strike must be within 1.5 strike-steps of the index
ATM_STEPS = 0.5          # strict ATM
LAST_ENTRY_MIN = 14 * 60 + 45
MIDDAY = (10 * 60 + 35, 13 * 60)
MAX_SLOT = 77            # upper bound used by the research code (bars exist to idx 74)


def ema(vals, n):
    a = 2.0 / (n + 1); e = vals[0]; out = []
    for v in vals:
        e = a * v + (1 - a) * e; out.append(e)
    return out


def minute_of(i):
    return 9 * 60 + 15 + 5 * i


def tstr(i):
    m = minute_of(i)
    return "%02d:%02d" % (m // 60, m % 60)


def index_direction(c, e10, e20):
    """Direction from the INDEX bar close and its EMAs."""
    if e10 > e20 and c > e20: return "CE"
    if e10 < e20 and c < e20: return "PE"
    return None


def gap_side(first_open, prev_close, th=GAP_TH):
    """Return (gap, side). side = 'CE' gap-up, 'PE' gap-down, None = no restriction (or unknown prev close)."""
    if not prev_close: return 0.0, None
    gap = first_open / prev_close - 1.0
    if gap >= th: return gap, "CE"
    if gap <= -th: return gap, "PE"
    return gap, None


def is_hammer(by, e10, k):
    if k not in by or k - 1 not in by or k - 2 not in by: return False
    h = by[k]; rng = h["H"] - h["L"]
    if rng <= 0 or h["C"] <= h["O"] or (h["C"] - h["O"]) < 0.30 * rng: return False
    clv = (h["C"] - h["L"]) / rng; lw = (min(h["O"], h["C"]) - h["L"]) / rng
    red_before = by[k - 1]["C"] < by[k - 1]["O"] or by[k - 2]["C"] < by[k - 2]["O"]
    touched = min(by[j]["L"] for j in range(k - 5, k + 1) if j in by) <= e10[k] * 1.003
    return clv >= .65 and lw >= .25 and red_before and touched


def signal_at(i, by, e10, e20, ix_dir_i, side, rr=3.0):
    """Evaluate option-chart bar i. ix_dir_i = index direction at bar i ('CE'/'PE'/None).
    Returns None (no signal) or a dict describing the signal and the planned trade (entry needs bar i+1).
    Does NOT apply gap / ATM / one-per-day filters (those are in select_day_trades)."""
    if i < 3 or i not in by or i - 1 not in by: return None
    if ix_dir_i != side: return None
    b = by[i]
    if b["C"] <= b["O"] or b["C"] < 0.99 * e10[i] or b["C"] < e20[i] or not e10[i] > e20[i]: return None
    hk = i if is_hammer(by, e10, i) else (i - 1 if is_hammer(by, e10, i - 1) else None)
    if hk is None: return None
    avg = sum(abs(by[j]["C"] - by[j]["O"]) for j in range(i - 5, i) if j in by) / 5.0
    if hk != i and abs(b["C"] - b["O"]) < 0.8 * avg: return None
    t_min = minute_of(i)
    if t_min > LAST_ENTRY_MIN: return None
    midday = MIDDAY[0] <= t_min <= MIDDAY[1]
    sig = {"i": i, "hammer": hk, "midday": midday, "t": tstr(i)}
    if i + 1 not in by:           # entry bar not formed yet (live: wait for it)
        sig["entry"] = None; return sig
    entry = by[i + 1]["O"]; stop = b["O"]; note = "stop=signal open"
    rng10 = sum(by[j]["H"] - by[j]["L"] for j in range(i - 9, i + 1) if j in by) / 10.0
    if entry - stop < 0.5 * rng10:
        stop = by[hk]["L"]; note = "stop=hammer low"
    R = entry - stop
    if R <= 0:
        sig["entry"] = None; sig["reject"] = "R<=0"; return sig
    sig.update(entry=entry, stop=stop, R=R, target=entry + rr * R, note=note)
    return sig


def simulate_exit(by, i, entry, stop, rr=3.0, max_hold=12):
    """Research exit used for the headline numbers: stop on wick touch, 3R limit target on wick touch, time exit
    at the close of the last allowed bar. Returns (R_multiple, exit_idx, reason)."""
    R = entry - stop; tgt = entry + rr * R; last = None
    for j in range(i + 1, min(i + 1 + max_hold, MAX_SLOT)):
        if j not in by: continue
        b = by[j]; last = j
        if b["L"] <= stop: return -1.0, j, "stop"
        if b["H"] >= tgt: return rr, j, "target"
    j = last if last is not None else i + 1
    return (by[j]["C"] - entry) / R, j, "time"


def parse_strike(name):
    m = re.search(r"(\d{4,})(CE|PE)", name)
    return int(m.group(1)), m.group(2)


def select_day_trades(ix_by, ix_e10, ix_e20, options, step, prev_close, rr=3.0, midday_filter=True):
    """One index, one day.  options: dict name -> (by, e10, e20).  Returns (trades, rejected).
    Applies, in order: signal rules, midday, gap direction, strike distance (<=1.5 steps), one position per day."""
    first = min(k for k in ix_by if k >= 0)
    gap, gside = gap_side(ix_by[first]["O"], prev_close)
    cands = []
    for name, (by, e10, e20) in options.items():
        strike, side = parse_strike(name)
        busy = -1
        for i in range(3, 68):
            if i <= busy or i not in by or i - 1 not in by or i not in ix_by: continue
            dirn = index_direction(ix_by[i]["C"], ix_e10[i], ix_e20[i])
            sig = signal_at(i, by, e10, e20, dirn, side, rr)
            if sig is None: continue
            if sig["midday"] and midday_filter: continue
            if sig.get("entry") is None: continue
            busy = i + 1
            ip = ix_by.get(i + 1, ix_by.get(i))["O"]
            dist = abs(ip - strike) / step
            why = []
            if gside and side != gside: why.append("gap-dir")
            if dist > MAX_DIST_STEPS: why.append("not-ATM")
            sig.update(name=name, side=side, strike=strike, dist=dist, atm=dist <= ATM_STEPS, why=why, gap=gap)
            cands.append((sig, by))
    cands.sort(key=lambda c: (c[0]["i"], c[0]["name"]))
    trades, rejected = [], []
    for sig, by in cands:
        if sig["why"]: rejected.append(sig); continue
        if trades: sig["why"] = ["one-position"]; rejected.append(sig); continue
        r, j, why = simulate_exit(by, sig["i"], sig["entry"], sig["stop"], rr)
        sig.update(R_mult=r, exit_idx=j, exit_reason=why)
        trades.append(sig)
    return trades, rejected
