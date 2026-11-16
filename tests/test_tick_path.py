"""Integration: ticks -> BarBuilder -> Engine gives the same trades as feeding finished bars (T2).
Uses a real research day with data holes filled as flat bars (what BarBuilder does live). Lab only (needs fixture)."""
import datetime
import json
import os
import unittest

from trader.broker import PaperBroker
from trader.candles import BarBuilder
from trader.engine import Engine, IndexSpec, OptionSpec
from trader.replay import run_dataset
from trader import rules_v3 as R
from trader.store import Store

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "replay_days.json")


def fill_holes(ds):
    for s in [ds["idx"]] + list(ds["opts"].values()):
        last = s["seed"][-1] if s["seed"] else None
        for k in range(s["n"]):
            b = s["bars"].get(str(k))
            if b is None:
                if last is None:
                    continue
                s["bars"][str(k)] = [last, last, last, last]
            else:
                last = b[3]
    return ds


def run_ticks(store, broker, ds):
    ixn = ds["index"]
    ix_sym = ixn + "_index"
    opts = [OptionSpec(n, float(R.parse_strike(n)[0]), R.parse_strike(n)[1], 1) for n in sorted(ds["opts"])]
    eng = Engine(store, broker, ds["day"])
    series = {ix_sym: ds["idx"]}
    series.update(ds["opts"])
    eng.add_index(IndexSpec(ixn, ix_sym, ds["step"], opts), ds["prev_close"], dict((k, v["seed"]) for k, v in series.items()))
    bb = dict((s, BarBuilder(s)) for s in series)
    y, m, d = [int(x) for x in ds["day"].split("-")]
    base = datetime.datetime(y, m, d, 9, 15)
    for s in range(ds["idx"]["n"]):
        for sym in [ix_sym] + sorted(ds["opts"]):
            b = series[sym]["bars"].get(str(s))
            if b is None:
                continue
            t0 = base + datetime.timedelta(minutes=5 * s)
            for sec, px in ((5, b[0]), (20, b[1]), (35, b[2]), (50, b[3])):
                closed = bb[sym].on_tick(t0 + datetime.timedelta(seconds=sec), px)
                if sec == 5:
                    eng.on_open(sym, s, px)
                for c in closed:
                    eng.on_bar(sym, c["slot"], c["O"], c["H"], c["L"], c["C"])
    n = ds["idx"]["n"]
    end = base + datetime.timedelta(minutes=5 * n, seconds=3)
    for sym in series:
        for c in bb[sym].close_due(end):
            eng.on_bar(sym, c["slot"], c["O"], c["H"], c["L"], c["C"])
    eng.end_of_day()


@unittest.skipUnless(os.path.exists(FIX), "replay fixture not shipped to VM")
class TickPath(unittest.TestCase):
    def test_tick_path_equals_bar_path(self):
        data = json.load(open(FIX))
        checked = 0
        for key in ("20261029/NIFTY", "20261102/NIFTY", "20261106/SENSEX", "20261030/NIFTY", "20261027/NIFTY"):
            ds = fill_holes(data[key])
            s1, b1, s2, b2 = Store(), PaperBroker(), Store(), PaperBroker()
            run_dataset(s1, b1, ds)
            run_ticks(s2, b2, ds)
            f = lambda st: [(t["symbol"], t["slot"], t["entry"], t["stop"], t["exit_reason"], t["r_mult"], t["exit_t"])
                            for t in st.trades_for_day(ds["day"])]
            self.assertEqual(f(s2), f(s1), key)
            self.assertEqual(len(b1.fills), len(b2.fills), key)
            checked += len(f(s1))
        self.assertGreaterEqual(checked, 3)


if __name__ == "__main__":
    unittest.main()
