"""Replay a recorded day through the Engine, slot by slot (same call sequence a live feed will produce).
Dataset format (tests/fixtures/replay_days.json): {"day","index","step","prev_close","idx":S,"opts":{name:S}}
with S = {"seed":[closes of previous session], "n":slots, "bars":{"slot":[o,h,l,c]}} (a missing slot = data hole)."""
from trader import rules_v3 as R
from trader.engine import Engine, IndexSpec, OptionSpec


def _strike_side(name):
    return R.parse_strike(name)


def run_dataset(store, broker, ds, qty=1, rr=3.0, midday_filter=True, notify=None, mode="paper"):
    ixn = ds["index"]
    ix_sym = ixn + "_index"
    opts = [OptionSpec(n, float(_strike_side(n)[0]), _strike_side(n)[1], qty) for n in sorted(ds["opts"])]
    spec = IndexSpec(ixn, ix_sym, ds["step"], opts)
    eng = Engine(store, broker, ds["day"], mode=mode, rr=rr, midday_filter=midday_filter, notify=notify)
    series = {ix_sym: ds["idx"]}
    series.update(ds["opts"])
    eng.add_index(spec, ds["prev_close"], dict((k, v["seed"]) for k, v in series.items()))
    n = ds["idx"]["n"]
    order = [ix_sym] + sorted(ds["opts"])
    for s in range(n):
        for sym in order:
            b = series[sym]["bars"].get(str(s))
            if b is not None:
                eng.on_open(sym, s, b[0])
        for sym in order:
            b = series[sym]["bars"].get(str(s))
            if b is None:
                eng.on_missing(sym, s)
            else:
                eng.on_bar(sym, s, b[0], b[1], b[2], b[3])
    eng.end_of_day()
    return eng
