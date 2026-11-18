import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from trader import rules_v3 as R
def feats(s):
    seq = list(s["seed"]); npre = len(seq); by = {}
    for k in range(s["n"]):
        b = s["bars"].get(str(k))
        if b is not None: by[k] = {"O": b[0], "H": b[1], "L": b[2], "C": b[3]}
        seq.append(b[3] if b is not None else (seq[-1] if seq else 0))
    return by, R.ema(seq, 10)[npre:], R.ema(seq, 20)[npre:]
D = json.load(open(os.path.join(HERE, "..", "tests", "fixtures", "replay_days.json")))
print("%-16s %-4s %-26s %-22s %-22s %s" % ("day/index", "side", "trade(opt sig->entry R)", "index trend since", "option trend since", "delay"))
for key in sorted(D):
    ds = D[key]
    ix, ie10, ie20 = feats(ds["idx"])
    opts = {n: feats(o) for n, o in ds["opts"].items()}
    trades, _ = R.select_day_trades(ix, ie10, ie20, opts, ds["step"], ds["prev_close"])
    for t in trades:
        i = t["i"]; side = t["side"]
        # index: start of the unbroken run of 'side' direction ending at i
        j = i
        while j - 1 in ix and R.index_direction(ix[j-1]["C"], ie10[j-1], ie20[j-1]) == side: j -= 1
        by, e10, e20 = opts[t["name"]]
        k = i
        while k - 1 in by and e10[k-1] > e20[k-1] and by[k-1]["C"] > e20[k-1]: k -= 1
        print("%-16s %-4s %-26s %-22s %-22s idx %d / opt %d candles" % (
            key, side, "%s %s R=%.1f %s" % (t["name"][-9:], t["t"], t["R_mult"], t["exit_reason"]),
            ("%s%s" % (R.tstr(j), " (carried)" if j == 0 or j <= 0 else "")), R.tstr(k) + (" (carried)" if k <= 0 else ""), i - j, i - k))
