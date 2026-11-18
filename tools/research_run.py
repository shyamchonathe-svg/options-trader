#!/usr/bin/env python3
"""Shadow research: python3 tools/research_run.py [live.db ...] > research_report.txt
Always includes the research fixture days; any trader.db copies given are added (live data)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from trader import research as RS, analyze as A, rules_v3 as R  # noqa: E402
from trader.store import Store  # noqa: E402


def feats(s):
    seq = list(s["seed"]); npre = len(seq); by = {}
    for k in range(s["n"]):
        b = s["bars"].get(str(k))
        if b is not None: by[k] = {"O": b[0], "H": b[1], "L": b[2], "C": b[3]}
        seq.append(b[3] if b is not None else (seq[-1] if seq else 0))
    return by, R.ema(seq, 10)[npre:], R.ema(seq, 20)[npre:]


def fixture_cases():
    D = json.load(open(os.path.join(HERE, "..", "tests", "fixtures", "replay_days.json")))
    for key in sorted(D):
        ds = D[key]; opts = {}
        for n, o in ds["opts"].items():
            by, e10, e20 = feats(o)
            opts[n] = (by, e10, e20, int(n.split("_")[1][:-2]), n[-2:])
        yield dict(day=ds["day"], index=ds["index"], step=ds["step"], prev_close=ds["prev_close"], ix=feats(ds["idx"]),
                   opts=opts, src="research")


def db_cases(path):
    st = Store(path)
    for (day,) in st.db.execute("SELECT DISTINCT day FROM bars ORDER BY day").fetchall():
        d = A.Day(st, day, "hist")
        for name, key in A.INDEX_KEY.items():
            if key not in d.series or not d.series[key].by: continue
            s = d.series[key]; opts = {}
            for sym in d.symbols:
                po = A.parse_option(sym)
                if po and po[0] == name and d.series[sym].by:
                    o = d.series[sym]; opts[sym] = (o.by, o.e10, o.e20, po[1], po[2])
            if opts:
                yield dict(day=day, index=name, step=A.STEPS[name], prev_close=d.prev_close.get(key),
                           ix=(s.by, s.e10, s.e20), opts=opts, src="live")


def main(dbs):
    rows = []
    for c in fixture_cases():
        for r in RS.run_case(c): r["src"] = "research"; rows.append(r)
    for p in dbs:
        for c in db_cases(p):
            for r in RS.run_case(c): r["src"] = "live"; rows.append(r)
    print("SHADOW RESEARCH - nothing here was traded. Same 3R / 12-candle exit for every setup, ATM + gap filters applied,")
    print("every signal counted per option (no one-trade-per-day cap), so n is bigger than the real trade count.")
    print("Signals inside the 10:35-13:00 window ARE included here (v3 skips them); see the 'midday' split.\n")
    print(RS.summarize(rows, "ALL SIGNALS"))
    print("\n" + RS.summarize(rows, "OUTSIDE 10:35-13:00 (what v3 could actually take)", lambda r: not r["midday"]))
    print("\n" + RS.summarize(rows, "INSIDE 10:35-13:00 (blocked in v3)", lambda r: r["midday"]))
    print("\n" + RS.summarize(rows, "INDEX HAS MOVED LITTLE (<0.20% since the trend began) - early/first leg", lambda r: r["idx_move"] < 0.20))
    print("\n" + RS.summarize(rows, "INDEX HAS MOVED A LOT (>=0.20%) - later legs", lambda r: r["idx_move"] >= 0.20))
    print("\n" + RS.summarize(rows, "OPTION ALREADY UP >=50% since its trend began", lambda r: r["opt_move"] >= 50))
    print("\n" + RS.summarize(rows, "OPTION UP <50%", lambda r: r["opt_move"] < 50))
    json.dump(rows, open(os.path.join(HERE, "..", "..", "research_rows.json"), "w"))


if __name__ == "__main__":
    main(sys.argv[1:])
