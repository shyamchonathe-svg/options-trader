"""Acceptance (T1): the Engine, fed day by day, produces EXACTLY the trades of rules_v3.select_day_trades
on the real research days. Needs tests/fixtures/replay_days.json (lab only; skipped on the VM)."""
import json
import os
import unittest

from trader import rules_v3 as R
from trader.broker import PaperBroker
from trader.replay import run_dataset
from trader.store import Store

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "replay_days.json")

# the 11 known v3 trades through 13 Nov: (day, option, signal time, entry, stop, R at 3R)
KNOWN = None


def batch(ds):
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
    trades, _ = R.select_day_trades(ixby, e10, e20, opts, ds["step"], ds["prev_close"])
    return trades


@unittest.skipUnless(os.path.exists(FIX), "replay fixture not shipped to VM")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.load(open(FIX))

    def test_engine_equals_batch_every_day(self):
        total = 0
        for key in sorted(self.data):
            ds = self.data[key]
            st, br = Store(), PaperBroker()
            run_dataset(st, br, ds)
            got = [(t["symbol"], t["slot"], round(t["entry"], 6), round(t["stop"], 6), t["exit_reason"], round(t["r_mult"], 6),
                    t["exit_t"]) for t in st.trades_for_day(ds["day"])]
            exp = [(t["name"], t["i"], round(t["entry"], 6), round(t["stop"], 6), t["exit_reason"], round(t["R_mult"], 6),
                    R.tstr(t["exit_idx"])) for t in batch(ds)]
            self.assertEqual(got, exp, key)
            total += len(got)
            # every trade has exactly one buy and one sell
            self.assertEqual(len(br.fills), 2 * len(got), key)
            self.assertEqual(st.open_trades(), [], key)
        self.assertEqual(total, 11)

    def test_replay_twice_is_idempotent(self):
        for key in sorted(self.data):
            ds = self.data[key]
            st, br = Store(), PaperBroker()
            run_dataset(st, br, ds)
            n_sig = len(st.signals_for_day(ds["day"]))
            n_tr = len(st.trades_for_day(ds["day"]))
            n_fill = len(br.fills)
            run_dataset(st, br, ds)               # same store + broker: a "restart and re-feed"
            self.assertEqual(len(st.signals_for_day(ds["day"])), n_sig, key)
            self.assertEqual(len(st.trades_for_day(ds["day"])), n_tr, key)
            self.assertEqual(len(br.fills), n_fill, key)


if __name__ == "__main__":
    unittest.main()
