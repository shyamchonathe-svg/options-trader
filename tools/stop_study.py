#!/usr/bin/env python3
"""Stop-loss study: replay every research day + stored live days with different stop rules, same entries and filters
as rules_v3.select_day_trades. Read-only. Usage: python3 tools/stop_study.py [path/to/trader_day.db ...]"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from trader import rules_v3 as R  # noqa: E402

LOT = {"NIFTY": 65, "SENSEX": 20}


def stops(sig, by):
    i, hk = sig["i"], sig["hammer"]
    entry = sig["entry"]
    return {
        "A v3 (signal open)": sig["stop"],
        "B signal-candle low": by[i]["L"],
        "C hammer-candle low": by[hk]["L"],
        "D lower of open/low-5pct": min(sig["stop"], by[i]["L"]),
    }


def candidates(ix_by, e10x, e20x, options, step, prev_close):
    first = min(k for k in ix_by if k >= 0)
    gap, gside = R.gap_side(ix_by[first]["O"], prev_close)
    cands = []
    for name, (by, e10, e20) in options.items():
        strike, side = R.parse_strike(name)
        busy = -1
        for i in range(3, 68):
            if i <= busy or i not in by or i - 1 not in by or i not in ix_by:
                continue
            dirn = R.index_direction(ix_by[i]["C"], e10x[i], e20x[i])
            sig = R.signal_at(i, by, e10, e20, dirn, side, 3.0)
            if sig is None or sig["midday"] or sig.get("entry") is None:
                continue
            busy = i + 1
            ip = ix_by.get(i + 1, ix_by.get(i))["O"]
            dist = abs(ip - strike) / step
            why = []
            if gside and side != gside:
                why.append("gap")
            if dist > R.MAX_DIST_STEPS:
                why.append("atm")
            sig.update(name=name, side=side, why=why)
            cands.append((sig, by))
    cands.sort(key=lambda c: (c[0]["i"], c[0]["name"]))
    return [c for c in cands if not c[0]["why"]][:1]       # one position per index per day


def run_variants(label, index, ix_by, e10x, e20x, options, step, prev_close, rows):
    for sig, by in candidates(ix_by, e10x, e20x, options, step, prev_close):
        for vname, stop in stops(sig, by).items():
            entry = sig["entry"]
            Rr = entry - stop
            if Rr <= 0:
                continue
            tgt = entry + 3.0 * Rr
            res = "time"
            last, r = None, None
            for j in range(sig["i"] + 1, min(sig["i"] + 13, R.MAX_SLOT)):
                if j not in by:
                    continue
                b = by[j]
                last = j
                if b["L"] <= stop:
                    r, res = -1.0, "stop"
                    break
                if b["H"] >= tgt:
                    r, res = 3.0, "target"
                    break
            if r is None:
                r = (by[last]["C"] - entry) / Rr if last is not None else 0.0
            lot = LOT[index]
            qty = int(90000 // (entry * lot)) * lot
            pnl = qty * r * Rr
            rows.append({"day": label, "index": index, "opt": sig["name"], "t": sig["t"], "entry": entry, "stop": stop,
                         "risk": Rr, "variant": vname, "res": res, "r": r, "qty": qty, "pnl": pnl})


def main(dbs):
    rows = []
    fx = os.path.join(HERE, "..", "tests", "fixtures", "replay_days.json")
    if os.path.exists(fx):
        data = json.load(open(fx))
        for key in sorted(data):
            ds = data[key]

            def feats(s):
                seq = list(s["seed"])
                npre = len(seq)
                by = {}
                for k in range(s["n"]):
                    b = s["bars"].get(str(k))
                    if b is not None:
                        by[k] = {"O": b[0], "H": b[1], "L": b[2], "C": b[3]}
                    seq.append(b[3] if b is not None else (seq[-1] if seq else 0))
                return by, R.ema(seq, 10)[npre:], R.ema(seq, 20)[npre:]
            ixby, e10, e20 = feats(ds["idx"])
            opts = dict((n, feats(o)) for n, o in ds["opts"].items())
            run_variants(ds["day"], ds["index"], ixby, e10, e20, opts, ds["step"], ds["prev_close"], rows)
    from trader.store import Store
    from trader.analyze import Day, INDEX_KEY, parse_option, STEPS
    for p in dbs:
        st = Store(p)
        days = [r[0] for r in st.db.execute("SELECT DISTINCT day FROM bars WHERE src='hist' ORDER BY day")]
        for day in days:
            d = Day(st, day, "hist")
            for name in ("NIFTY", "SENSEX"):
                ix = d.series.get(INDEX_KEY[name])
                if ix is None:
                    continue
                opts = {}
                for s in d.symbols:
                    po = parse_option(s)
                    if po and po[0] == name:
                        sr = d.series[s]
                        opts["%s_%d%s" % (name, po[1], po[2])] = (sr.by, sr.e10, sr.e20)
                run_variants(day, name, ix.by, ix.e10, ix.e20, opts, STEPS[name], d.prev_close.get(INDEX_KEY[name]), rows)
    return rows


if __name__ == "__main__":
    rows = main(sys.argv[1:])
    print("%-10s %-6s %-16s %-5s %-8s %-8s %-7s %-26s %-6s %6s %5s %9s" % (
        "day", "index", "option", "time", "entry", "stop", "risk", "stop rule", "result", "R", "qty", "P&L Rs"))
    for r in rows:
        print("%-10s %-6s %-16s %-5s %-8.2f %-8.2f %-7.2f %-26s %-6s %6.2f %5d %9.0f" % (
            r["day"], r["index"], r["opt"], r["t"], r["entry"], r["stop"], r["risk"], r["variant"], r["res"], r["r"], r["qty"], r["pnl"]))
    print()
    print("%-26s %6s %6s %7s %8s %10s %12s" % ("stop rule", "trades", "wins", "stops", "total R", "avg R", "total P&L Rs"))
    for v in sorted(set(r["variant"] for r in rows)):
        rs = [r for r in rows if r["variant"] == v]
        print("%-26s %6d %6d %7d %8.2f %10.2f %12.0f" % (v, len(rs), len([r for r in rs if r["r"] > 0]),
              len([r for r in rs if r["res"] == "stop"]), sum(r["r"] for r in rs), sum(r["r"] for r in rs) / len(rs), sum(r["pnl"] for r in rs)))
