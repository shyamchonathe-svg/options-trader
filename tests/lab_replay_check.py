"""Golden test: new rules_v3 must reproduce the saved v3 trades (exit_v3.txt + exit_v3_1113.txt) exactly."""
import sys, re, importlib
sys.path.insert(0, '/home/schonat/deep/tools'); sys.path.insert(0, '/home/schonat/deep/live')
import zoom_run as zr, strategy_v2 as s2
from trader import rules_v3 as r3

FIXES = [None, ("_pending_regime/2026-10-28_", "vix_gt15/trade_days/2026-10-28_"),
         ("_pending_regime/2026-10-29_", "vix_gt15/trade_days/2026-10-29_"),
         ("vix_gt15/trade_days/2026-10-29_", "_pending_regime/2026-10-29_")]
_cache = {}
def run_all(c):
    if c.__name__ not in _cache: _cache[c.__name__] = zr.run_all(c, verbose=False)
    return _cache[c.__name__]

def replay(days, prev_close):
    out = []
    for d in days:
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
                    R = run_all(c)
                    ixby, e10, e20 = s2.feats(R, ixn)
                    last_i = max(k for k in ixby if k <= 74)
                    pc = None if d == "20261106" else prev_close.get(pre)
                    prev_close[pre] = ixby[last_i]["C"]
                    opts = {}
                    for n in names:
                        by, a, b = s2.feats(R, n); opts[n] = (by, a, b)
                    trades, rej = r3.select_day_trades(ixby, e10, e20, opts, step, pc)
                    for t in trades: out.append((d, t["name"], t["t"], round(t["entry"], 1), round(t["stop"], 1), round(t["R_mult"], 2)))
                    break
                except FileNotFoundError: continue
    return out

def parse(path):
    res = []
    for ln in open(path):
        m = re.match(r"\s*(\d{8}) (\S+)\s+(\d\d:\d\d) gap\S+ dist=\S+ entry ([\d.]+) stop ([\d.]+) \|.* 3R ([+-][\d.]+)", ln)
        if m: res.append((m.group(1), m.group(2), m.group(3), float(m.group(4)), float(m.group(5)), float(m.group(6))))
    return res

new = replay(["20261027", "20261028", "20261029", "20261030", "20261102", "20261103", "20261106", "20261109"], {})
new += replay(["20261113"], {"NIFTY": 25299.35, "SENSEX": 81911.01})
old = parse('/home/schonat/deep/_scratch/exit_v3.txt') + parse('/home/schonat/deep/_scratch/exit_v3_1113.txt')
key = lambda x: (x[0], x[1])
new.sort(key=key); old.sort(key=key)
print("new:", len(new), " old:", len(old))
for x in new: print(" NEW", x)
ok = new == old
if not ok:
    for x in old: print(" OLD", x)
print("RESULT:", "PASS - identical" if ok else "MISMATCH")
sys.exit(0 if ok else 1)
