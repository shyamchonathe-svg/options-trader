"""Lab only: export the real research days (bars + seed closes) to tests/fixtures/replay_days.json
so the engine can be replay-tested without the research tools. Run: python3 tests/lab_export_days.py"""
import sys, re, json, importlib
sys.path.insert(0, '/home/schonat/deep/tools'); sys.path.insert(0, '/home/schonat/deep/live')
import zoom_run as zr, strategy_v2 as s2

FIXES = [None, ("_pending_regime/2026-10-28_", "vix_gt15/trade_days/2026-10-28_"),
         ("_pending_regime/2026-10-29_", "vix_gt15/trade_days/2026-10-29_"),
         ("vix_gt15/trade_days/2026-10-29_", "_pending_regime/2026-10-29_")]
DAYS = ["20261027", "20261028", "20261029", "20261030", "20261102", "20261103", "20261106", "20261109", "20261113"]

def series(R, name):
    bars, info = R[name]
    pre = [round(b["C"], 4) for b in bars if b["idx"] < 0 and b["O"] is not None]
    today = {b["idx"]: [b["O"], b["H"], b["L"], b["C"]] for b in bars if 0 <= b["idx"] < info["nslots"] and b["O"] is not None}
    n = info["nslots"]
    return {"seed": pre, "n": n, "bars": {str(k): [round(x, 4) for x in v] for k, v in today.items()}}

out = {}
prev = {}
for d in DAYS:
    cfg = "zoom_config_" + d
    for ixn, step in (("SENSEX_index", 100), ("NIFTY_index", 50)):
        pre = ixn.split("_")[0]
        for fx in FIXES:
            try:
                c = importlib.import_module(cfg)
                if fx: c.SPEC = {k: (v[0].replace(*fx),) + tuple(v[1:]) for k, v in c.SPEC.items()}
                if ixn not in c.SPEC: break
                names = sorted({k for k in c.SPEC if k.startswith(pre + "_") and k[-2:] in ("CE", "PE") and re.search(r"\d{4,}", k)})
                if not names: break
                R = zr.run_all(c, verbose=False)
                ixby, e10, e20 = s2.feats(R, ixn)
                last_i = max(k for k in ixby if k <= 74)
                pc = None if d == "20261106" else prev.get(pre)
                if d == "20261113": pc = {"NIFTY": 25299.35, "SENSEX": 81911.01}[pre]
                prev[pre] = ixby[last_i]["C"]
                out["%s/%s" % (d, pre)] = {"day": d[:4] + "-" + d[4:6] + "-" + d[6:], "index": pre, "step": step, "prev_close": pc,
                                            "idx": series(R, ixn), "opts": {n: series(R, n) for n in names}}
                break
            except FileNotFoundError: continue
json.dump(out, open("/home/schonat/deep/live/tests/fixtures/replay_days.json", "w"), separators=(",", ":"))
print(len(out), "day/index sets")
for k, v in out.items():
    holes = {n: [i for i in range(o["n"]) if str(i) not in o["bars"]] for n, o in list(v["opts"].items()) + [("IDX", v["idx"])]}
    h = {n: x for n, x in holes.items() if x}
    print(k, "opts", len(v["opts"]), "n", v["idx"]["n"], "holes", h if h else "-")
