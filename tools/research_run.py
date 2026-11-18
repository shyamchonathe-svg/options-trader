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


def stats(x):
    if not x: return (0, 0.0, 0.0, 0.0)
    w = sum(1 for r in x if r["why"] == "target"); t = sum(r["R"] for r in x)
    return (len(x), 100.0 * w / len(x), t / len(x), t)


def ranking(rows, title, minn=8, top=15):
    """Rank every grid setup on the RESEARCH days (screenshot data), then show how the same setup did on LIVE days."""
    by = {}
    for r in rows: by.setdefault(r["setup"], []).append(r)
    cand = []
    for name, x in by.items():
        rs = [r for r in x if r["src"] == "research"]; lv = [r for r in x if r["src"] == "live"]
        sr, sl = stats(rs), stats(lv)
        if sr[0] >= minn: cand.append((sr[2], name, sr, sl))
    cand.sort(reverse=True)
    out = [title, "(ranked on research days, n>=%d; the LIVE columns are the real test - a setup counts only if it also holds there)" % minn,
           "%-52s | %4s %5s %6s | %4s %5s %6s" % ("setup", "n", "win%", "avgR", "n", "win%", "avgR")]
    for _, name, sr, sl in cand[:top]:
        out.append("%-52s | %4d %4.0f%% %6.2f | %4d %4.0f%% %6.2f" % (name, sr[0], sr[1], sr[2], sl[0], sl[1], sl[2]))
    out.append("(%d of %d setups had enough signals; with this many formulas a few will look good by luck)" % (len(cand), len(by)))
    return "\n".join(out)


def main(argv):
    args = list(argv); out_dir = "."; grid = False; dbs = []
    while args:
        a = args.pop(0)
        if a == "--out": out_dir = args.pop(0)
        elif a == "--grid": grid = True
        else: dbs.append(a)
    hammers, insides = dict(RS.HAMMERS), dict(RS.INSIDE)
    if grid:
        hammers.update(RS.hammer_grid()); insides.update(RS.inside_grid())
    rows = []
    for c in fixture_cases():
        for r in RS.run_case(c, hammers=hammers, insides=insides): r["src"] = "research"; rows.append(r)
    for p in dbs:
        for c in db_cases(p):
            for r in RS.run_case(c, hammers=hammers, insides=insides): r["src"] = "live"; rows.append(r)
    named = [r for r in rows if not r["setup"].startswith("g-")]
    ndays = len(set(r["day"] for r in rows if r["src"] == "live"))
    L = []
    L.append("SHADOW RESEARCH - nothing here was traded. Same 3R / 12-candle exit for every setup, ATM + gap filters applied,")
    L.append("every signal counted per option (no one-trade-per-day cap), so n is bigger than the real trade count.")
    L.append("Signals inside the 10:35-13:00 window ARE included here (v3 skips them); see the 'midday' split.")
    L.append("Data: research days (screenshot-derived, for discovery) + %d live day(s) (exact candles, for verification).\n" % ndays)
    L.append(RS.summarize(named, "ALL SIGNALS (both data sets)"))
    for src in ("research", "live"):
        if any(r["src"] == src for r in named):
            L.append("\n" + RS.summarize(named, "ONLY %s DAYS" % src.upper(), lambda r, s=src: r["src"] == s))
    L.append("\n" + RS.summarize(named, "OUTSIDE 10:35-13:00 (what v3 could actually take)", lambda r: not r["midday"]))
    L.append("\n" + RS.summarize(named, "INSIDE 10:35-13:00 (blocked in v3)", lambda r: r["midday"]))
    L.append("\n" + RS.summarize(named, "INDEX HAS MOVED LITTLE (<0.20% since the trend began) - early/first leg", lambda r: r["idx_move"] < 0.20))
    L.append("\n" + RS.summarize(named, "INDEX HAS MOVED A LOT (>=0.20%) - later legs", lambda r: r["idx_move"] >= 0.20))
    L.append("\n" + RS.summarize(named, "OPTION ALREADY UP >=50% since its trend began", lambda r: r["opt_move"] >= 50))
    L.append("\n" + RS.summarize(named, "OPTION UP <50%", lambda r: r["opt_move"] < 50))
    if grid:
        gh = [r for r in rows if r["setup"].startswith("g-ham")]; gi = [r for r in rows if r["setup"].startswith("g-ins")]
        L.append("\n" + ranking(gh, "GRID - HAMMER FORMULAS (top 15)"))
        L.append("\n" + ranking(gi, "GRID - INSIDE-CANDLE SETUPS (top 15)", minn=4))
    text = "\n".join(L)
    print(text)
    if not os.path.isdir(out_dir): os.makedirs(out_dir)
    json.dump(rows, open(os.path.join(out_dir, "research_rows.json"), "w"))


if __name__ == "__main__":
    main(sys.argv[1:])
