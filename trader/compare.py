"""Exit-rule comparison on the SAME entries (paper trades + late-sim), from the stored 5-minute bars.
Answers: would trailing have captured trending days better than the fixed 3R / 12-bar exit, and at what cost?
This never changes what the paper trader does; it only replays alternative exits offline (a v4 question).
Conventions match rules_v3.simulate_exit: stop-first when stop and target are touched in the same bar, time exit at the
close of the last allowed bar. Entry = open of the bar after the signal bar. Slot 69 = 15:00 (no new holding past it)."""
from trader import rules_v3 as R

END_SLOT = 69

# name, dict(rr, hold, be, trail_n, arm)
VARIANTS = [
    ("A  v3 now: 3R target, 12 bars",                 dict(rr=3.0, hold=12)),
    ("B  stop to entry after +2R, 3R, 12 bars",       dict(rr=3.0, hold=12, be=2.0)),
    ("C  trail 3-bar low after +1R, no target, 12 bars", dict(rr=None, hold=12, trail=3, arm=1.0)),
    ("D  trail 3-bar low after +1R, no target, to 15:00", dict(rr=None, hold=None, trail=3, arm=1.0)),
    ("E  trail 5-bar low after +1R, no target, to 15:00", dict(rr=None, hold=None, trail=5, arm=1.0)),
]


def run_exit(by, sig_slot, entry, stop, rr=3.0, hold=12, be=None, trail=None, arm=1.0):
    """by: slot -> {O,H,L,C}. Returns (r_multiple, exit_slot, reason)."""
    r0 = entry - stop
    if r0 <= 0:
        return None
    e = sig_slot + 1
    last_slot = e + hold if hold else END_SLOT + 1
    tgt = entry + rr * r0 if rr else None
    cur, armed, last = stop, False, None
    for j in range(e, min(last_slot, R.MAX_SLOT)):
        b = by.get(j)
        if b is None:
            continue
        last = j
        if b["L"] <= cur:
            return (cur - entry) / r0, j, "stop" if cur == stop else "trail"
        if tgt is not None and b["H"] >= tgt:
            return rr, j, "target"
        if be is not None and b["H"] >= entry + be * r0:
            cur = max(cur, entry)
        if trail:
            if b["H"] >= entry + arm * r0:
                armed = True
            if armed:
                lows = [by[k]["L"] for k in range(j - trail + 1, j + 1) if k in by and k >= e]
                if lows:
                    cur = max(cur, min(lows))
    j = last if last is not None else e
    return (by[j]["C"] - entry) / r0 if j in by else 0.0, j, "time"


def _bars(store, day, symbol, cache):
    k = (day, symbol)
    if k not in cache:
        by = {}
        for src in ("backfill", "live"):
            for b in store.get_bars(day, symbol, src):
                by[b["slot"]] = {"O": b["o"], "H": b["h"], "L": b["l"], "C": b["c"]}
        cache[k] = by
    return cache[k]


def entries(store):
    q = ("SELECT s.day, s.symbol, s.slot, s.entry, s.stop, t.mode FROM trades t JOIN signals s ON s.id=t.signal_id "
         "WHERE s.entry IS NOT NULL AND s.stop IS NOT NULL ORDER BY s.day, s.slot, s.symbol")
    return [dict(r) for r in store.db.execute(q)]


def compare(store, include_sim=True):
    cache, rows = {}, []
    for t in entries(store):
        if t["mode"] == "late-sim" and not include_sim:
            continue
        by = _bars(store, t["day"], t["symbol"], cache)
        res = [run_exit(by, t["slot"], t["entry"], t["stop"], **kw) for _, kw in VARIANTS]
        if all(r is not None for r in res):
            rows.append(res)
    n = len(rows)
    if n == 0:
        return "Exit comparison: no trades with stored bars yet."
    out = ["Exit comparison on %d trade(s) (paper%s), same entries, R multiples:" % (n, " + late-sim" if include_sim else ""),
           "  %-52s %5s %7s %7s %7s %7s" % ("rule", "win%", "avg R", "total", "best", "worst")]
    for k, (name, _) in enumerate(VARIANTS):
        rs = [row[k][0] for row in rows]
        out.append("  %-52s %4.0f%% %+7.2f %+7.1f %+7.1f %+7.1f" % (
            name, 100.0 * len([x for x in rs if x > 0]) / n, sum(rs) / n, sum(rs), max(rs), min(rs)))
    trend = len([row for row in rows if row[4][0] >= 3.0])
    out.append("  trending trades (rule E reached >= +3R): %d of %d" % (trend, n))
    out.append("  Small samples mislead: do NOT pick a winner before ~50 trades. This is a v4 question, v3 stays frozen.")
    return "\n".join(out)
