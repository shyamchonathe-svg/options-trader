"""Trade analysis ("look at the chart again"): for any stored day, time and option, show every v3 condition, whether it
matched, the numbers behind it, what the bot actually did, and what would have happened. Uses only stored bars, so any
day in the database can be re-examined. Pure read-only; the same rule functions as the live engine (rules_v3)."""
import re

from trader import rules_v3 as R
from trader.engine import Series

STEPS = {"NIFTY": 50, "SENSEX": 100}
INDEX_KEY = {"NIFTY": "NSE:NIFTY 50", "SENSEX": "BSE:SENSEX"}
_OPT = re.compile(r"(NIFTY|SENSEX)\w*?(\d{5})(CE|PE)$")


def parse_option(sym):
    m = _OPT.search(sym)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else None


def slot_of(hhmm):
    h, m = hhmm.split(":")
    t = int(h) * 60 + int(m)
    if t < 555 or (t - 555) % 5:
        raise ValueError("time must be a 5-minute bar start from 09:15 to 15:25, e.g. 09:35")
    return (t - 555) // 5


class Day(object):
    """Bars and EMAs of one stored day, seeded the way the live system seeds them (previous session's closes)."""

    def __init__(self, store, day, source="hist"):
        self.store, self.day = store, day
        self.source = source
        self.series, self.prev_close = {}, {}
        rows = store.db.execute("SELECT DISTINCT symbol FROM bars WHERE day=?", (day,)).fetchall()
        self.symbols = sorted(r[0] for r in rows)
        prev = store.db.execute("SELECT MAX(day) FROM bars WHERE day<?", (day,)).fetchone()[0]
        self.prev_day = prev
        for s in self.symbols:
            seed = []
            if prev:
                seed = [b["c"] for b in store.get_bars(prev, s, "backfill")] or [b["c"] for b in store.get_bars(prev, s, "live")]
            if seed and s in INDEX_KEY.values():
                self.prev_close[s] = seed[-1]
            bars = store.get_bars(day, s, source) or store.get_bars(day, s, "live")
            ser = Series(seed)
            for b in bars:
                ser.add(b["slot"], {"O": b["o"], "H": b["h"], "L": b["l"], "C": b["c"]})
            self.series[s] = ser

    def match(self, text):
        """'NIFTY25300PE', 'nifty 25300 pe', '25300PE' or a part of the stored symbol -> stored option symbols."""
        t = text.upper().replace(" ", "")
        m = re.match(r"^(NIFTY|SENSEX)?(\d{4,6})(CE|PE)$", t)
        if m:
            return [s for s in self.symbols if parse_option(s) and parse_option(s)[1:] == (int(m.group(2)), m.group(3))
                    and (not m.group(1) or parse_option(s)[0] == m.group(1))]
        return [s for s in self.symbols if t in s.upper().replace(" ", "") and parse_option(s)]


def _chk(label, ok, detail):
    return {"label": label, "ok": ok, "detail": detail}


def hammer_detail(by, e10, k):
    """Same test as rules_v3.is_hammer, but itemised."""
    if k not in by or k - 1 not in by or k - 2 not in by:
        return [_chk("enough candles before it", False, "need the 2 candles before %s" % R.tstr(k))]
    h = by[k]
    rng = h["H"] - h["L"]
    if rng <= 0:
        return [_chk("candle has a range", False, "flat candle")]
    body = (h["C"] - h["O"]) / rng
    clv = (h["C"] - h["L"]) / rng
    lw = (min(h["O"], h["C"]) - h["L"]) / rng
    red = by[k - 1]["C"] < by[k - 1]["O"] or by[k - 2]["C"] < by[k - 2]["O"]
    low6 = min(by[j]["L"] for j in range(k - 5, k + 1) if j in by)
    return [_chk("green body of at least 30% of the range", h["C"] > h["O"] and body >= 0.30, "body %.0f%% of range" % (100 * body)),
            _chk("closes in the top 35% of its range", clv >= .65, "close at %.0f%% of range" % (100 * clv)),
            _chk("lower wick at least 25% of range", lw >= .25, "lower wick %.0f%%" % (100 * lw)),
            _chk("a red candle in the 2 before it", red, "previous candles %s" % ", ".join(
                "red" if by[j]["C"] < by[j]["O"] else "green" for j in (k - 2, k - 1))),
            _chk("touched the 10-EMA in the last 6 candles", low6 <= e10[k] * 1.003,
                 "lowest low %.2f vs 10-EMA %.2f (limit %.2f)" % (low6, e10[k], e10[k] * 1.003))]


def check(d, sym, i):
    """All conditions for option `sym`, signal candle slot i. Returns dict(items, verdict, sig, ...)."""
    name, strike, side = parse_option(sym)
    s = d.series[sym]
    by, e10, e20 = s.by, s.e10, s.e20
    ixs = d.series.get(INDEX_KEY[name])
    out = {"sym": sym, "slot": i, "items": [], "sig": None, "filters": [], "signal_ok": False}
    if i not in by or i - 1 not in by or i < 3:
        out["items"].append(_chk("candle data available", False, "no stored candle for %s" % R.tstr(i)))
        return out
    b = by[i]
    dirn = None
    if ixs is not None and i in ixs.by:
        dirn = R.index_direction(ixs.by[i]["C"], ixs.e10[i], ixs.e20[i])
        idx_detail = "index close %.2f, 10-EMA %.2f, 20-EMA %.2f -> %s" % (
            ixs.by[i]["C"], ixs.e10[i], ixs.e20[i], {"CE": "UP trend", "PE": "DOWN trend", None: "no clear trend"}[dirn])
    else:
        idx_detail = "index candle missing"
    it = out["items"]
    it.append(_chk("index trend favours a %s" % side, dirn == side, idx_detail))
    it.append(_chk("signal candle is green", b["C"] > b["O"], "open %.2f close %.2f" % (b["O"], b["C"])))
    it.append(_chk("close not below 99% of the 10-EMA", b["C"] >= 0.99 * e10[i], "close %.2f vs %.2f" % (b["C"], 0.99 * e10[i])))
    it.append(_chk("close above the 20-EMA", b["C"] >= e20[i], "close %.2f vs 20-EMA %.2f" % (b["C"], e20[i])))
    it.append(_chk("10-EMA above 20-EMA", e10[i] > e20[i], "%.2f vs %.2f" % (e10[i], e20[i])))
    hi, hp = hammer_detail(by, e10, i), hammer_detail(by, e10, i - 1)
    hi_ok, hp_ok = all(c["ok"] for c in hi), all(c["ok"] for c in hp)
    if hi_ok:
        it.append(_chk("hammer pattern on this candle", True, "; ".join(c["detail"] for c in hi)))
    elif hp_ok:
        avg = sum(abs(by[j]["C"] - by[j]["O"]) for j in range(i - 5, i) if j in by) / 5.0
        body = abs(b["C"] - b["O"])
        it.append(_chk("hammer pattern on the candle before (%s)" % R.tstr(i - 1), True, "; ".join(c["detail"] for c in hp)))
        it.append(_chk("this candle confirms it (body at least 80% of recent average)", body >= 0.8 * avg,
                       "body %.2f vs 80%% of average %.2f" % (body, 0.8 * avg)))
    else:
        for tag, lst in (("this candle", hi), ("candle before", hp)):
            for c in lst:
                it.append(_chk("hammer test (%s): %s" % (tag, c["label"]), c["ok"], c["detail"]))
    t_min = R.minute_of(i)
    it.append(_chk("before the 14:45 last-entry time", t_min <= R.LAST_ENTRY_MIN, "candle %s" % R.tstr(i)))
    mid = R.MIDDAY[0] <= t_min <= R.MIDDAY[1]
    it.append(_chk("outside the 10:35-13:00 no-trade window", not mid, "candle %s" % R.tstr(i)))
    out["signal_ok"] = all(c["ok"] for c in it)
    if i + 1 not in by:
        out["items"].append(_chk("next candle exists (entry price)", False, "no candle at %s" % R.tstr(i + 1)))
        out["signal_ok"] = False
        return out
    sig = R.signal_at(i, by, e10, e20, dirn, side, 3.0)
    out["sig"] = sig if sig and sig.get("entry") is not None else None
    # the mirror above and the real rule function must agree (midday is applied outside signal_at)
    core = all(c["ok"] for c in it if not c["label"].startswith("outside"))
    if core != bool(sig and True):
        out["mismatch"] = True
    # ---- filters applied after the pattern
    f = out["filters"]
    ip = ixs.by[i + 1]["O"] if (ixs is not None and i + 1 in ixs.by) else (ixs.by[i]["O"] if ixs is not None and i in ixs.by else None)
    step = STEPS[name]
    gap_side = None
    pc = d.prev_close.get(INDEX_KEY[name])
    if ixs is not None and pc:
        first = min(ixs.by) if ixs.by else None
        if first is not None:
            gap, gap_side = R.gap_side(ixs.by[first]["O"], pc)
            f.append(_chk("gap direction allows a %s" % side, not gap_side or gap_side == side,
                          "day opened %+.2f%% vs previous close %.2f%s" % (100 * gap, pc, "" if not gap_side else " (only %s allowed)" % gap_side)))
    if ip is not None:
        dist = abs(ip - strike) / float(step)
        f.append(_chk("strike within 1.5 steps of the index", dist <= R.MAX_DIST_STEPS,
                      "index %.2f, strike %d -> %.2f steps" % (ip, strike, dist)))
    prior = [t for t in d.store.trades_for_day(d.day)
             if parse_option(t["symbol"]) and parse_option(t["symbol"])[0] == name and t["entry_t"] < R.tstr(i + 1)]
    f.append(_chk("no other trade taken in %s today" % name.title(), not prior,
                  "already traded %s at %s" % (prior[0]["symbol"], prior[0]["entry_t"]) if prior else "first trade of the day"))
    return out


def outcome(d, c):
    """What would happen after entry (stored candles only)."""
    sig = c["sig"]
    if not sig:
        return None
    by = d.series[c["sym"]].by
    r, j, why = R.simulate_exit(by, sig["i"], sig["entry"], sig["stop"], 3.0)
    return r, j, why


def actual(d, c):
    sid = d.store.db.execute("SELECT * FROM signals WHERE day=? AND symbol=? AND slot=?", (d.day, c["sym"], c["slot"])).fetchone()
    return sid


def _mark(ok):
    return "PASS" if ok else "FAIL"


def format_check(d, c):
    from trader.present import pretty_symbol
    L = ["%s  %s  candle %s  (day %s, %s candles)" % (pretty_symbol(c["sym"]), "", R.tstr(c["slot"]), d.day,
                                                      "exchange" if d.source == "hist" else "live")]
    for x in c["items"]:
        L.append("  [%s] %s - %s" % (_mark(x["ok"]), x["label"], x["detail"]))
    if c["signal_ok"] and c["sig"]:
        s = c["sig"]
        L.append("  => PATTERN MATCHED. Buy at the next candle (%s) open %.2f, stop %.2f (%s), target %.2f, risk %.2f per unit" % (
            R.tstr(c["slot"] + 1), s["entry"], s["stop"], s["note"], s["target"], s["R"]))
        for x in c["filters"]:
            L.append("  [%s] %s - %s" % (_mark(x["ok"]), x["label"], x["detail"]))
    else:
        bad = [x["label"] for x in c["items"] if not x["ok"]]
        L.append("  => NO SIGNAL. Failed: %s" % "; ".join(bad[:4]))
    allok = c["signal_ok"] and c["sig"] and all(x["ok"] for x in c["filters"])
    L.append("  => VERDICT: %s" % ("TRADE would be taken" if allok else ("pattern matched but BLOCKED by a filter" if c["signal_ok"] and c["sig"] else "no trade")))
    if c["sig"] and c["signal_ok"]:
        o = outcome(d, c)
        if o:
            r, j, why = o
            L.append("  => If entered: %s at %s, result %+.1fR" % ({"stop": "stop-loss hit", "target": "3R target hit", "time": "time exit"}[why], R.tstr(j), r))
    row = actual(d, c)
    if row is not None:
        L.append("  => What the bot recorded: %s%s" % (row["status"], (" (" + row["reasons"] + ")") if row["reasons"] else ""))
    elif c["signal_ok"] and c["sig"]:
        L.append("  => What the bot recorded: nothing for this candle")
    if c.get("mismatch"):
        L.append("  (note: checklist and rule engine disagree - report this)")
    return "\n".join(L)


def analyze(store, day, hhmm=None, query=None, source="hist", verbose=False):
    d = Day(store, day, source)
    if not d.symbols:
        return "No data stored for %s." % day
    if hhmm and query:
        i = slot_of(hhmm)
        syms = d.match(query)
        if not syms:
            return "No option matching '%s' on %s. Try e.g. NIFTY25300PE or SENSEX82100PE." % (query, day)
        return "\n\n".join(format_check(d, check(d, s, i)) for s in syms[:3])
    if hhmm:        # all options near the money at that candle, one line each
        i = slot_of(hhmm)
        lines = ["Candle %s on %s - every option near the money (use /analyze %s %s <option> for the full checklist):" % (hhmm, day, day, hhmm)]
        for s in d.symbols:
            p = parse_option(s)
            if not p:
                continue
            ixs = d.series.get(INDEX_KEY[p[0]])
            if ixs is None or (i + 1) not in ixs.by or abs(ixs.by[i + 1]["O"] - p[1]) / STEPS[p[0]] > 2.5:
                continue
            c = check(d, s, i)
            bad = [x["label"] for x in c["items"] if not x["ok"]]
            allok = c["signal_ok"] and c["sig"] and all(x["ok"] for x in c["filters"])
            lines.append("%-18s %s" % (s.split(":")[-1], "SIGNAL + all filters pass" if allok else (
                "pattern ok, blocked: " + "; ".join(x["label"] for x in c["filters"] if not x["ok"]) if c["signal_ok"] and c["sig"]
                else "first failure: " + (bad[0] if bad else "?"))))
        return "\n".join(lines)
    if query:       # every candle where the pattern matched for that option/index
        syms = d.match(query) if re.search(r"\d{4,}", query) else [s for s in d.symbols if parse_option(s) and query.upper() in s.upper()]
        out, hidden = [], 0
        for s in syms:
            for i in range(3, 68):
                c = check(d, s, i)
                if c["signal_ok"] and c["sig"]:
                    allok = all(x["ok"] for x in c["filters"])
                    blocked = "; ".join(x["label"] for x in c["filters"] if not x["ok"])
                    o = outcome(d, c)
                    if not allok and not verbose:
                        hidden += 1
                        continue
                    out.append("%s %-18s pattern matched - %s%s" % (R.tstr(i), s.split(":")[-1],
                               "all filters pass" if allok else "blocked: " + blocked,
                               "" if not o else " (would have ended %+.1fR)" % o[0]))
        if hidden:
            out.append("(%d more pattern matches were blocked by a filter - add the word 'all' to list them)" % hidden)
        return "\n".join(out) if out else "No pattern match for '%s' on %s." % (query, day)
    return "usage: /analyze <date> <HH:MM> [option]   e.g.  /analyze 2026-11-18 09:35 NIFTY25300PE"
