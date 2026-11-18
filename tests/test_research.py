"""The research harness must agree with the frozen v3 rules where it claims to (H0), and detect the inside-candle shape."""
import json
import os
import unittest

from trader import research as RS
from trader import rules_v3 as R

HERE = os.path.dirname(os.path.abspath(__file__))


def _feats(s):
    seq = list(s["seed"]); npre = len(seq); by = {}
    for k in range(s["n"]):
        b = s["bars"].get(str(k))
        if b is not None: by[k] = {"O": b[0], "H": b[1], "L": b[2], "C": b[3]}
        seq.append(b[3] if b is not None else (seq[-1] if seq else 0))
    return by, R.ema(seq, 10)[npre:], R.ema(seq, 20)[npre:]


class ResearchTests(unittest.TestCase):
    def test_h0_is_exactly_v3_hammer(self):
        days = json.load(open(os.path.join(HERE, "fixtures", "replay_days.json")))
        p = RS.HAMMERS["H0 v3 (current)"]; n = 0
        for key in days:
            for o in days[key]["opts"].values():
                by, e10, e20 = _feats(o)
                for k in range(3, 72):
                    self.assertEqual(RS.hammer_ok(by, e10, k, p), R.is_hammer(by, e10, k), "%s %s" % (key, k))
                    n += 1
        self.assertGreater(n, 1000)

    def test_h0_signals_match_v3_signals(self):
        days = json.load(open(os.path.join(HERE, "fixtures", "replay_days.json")))
        p = RS.HAMMERS["H0 v3 (current)"]; seen = 0
        for key in days:
            ds = days[key]; ix, i10, i20 = _feats(ds["idx"])
            for n, o in ds["opts"].items():
                by, e10, e20 = _feats(o); side = n[-2:]
                for i in range(3, 68):
                    if i not in by or i not in ix: continue
                    d = R.index_direction(ix[i]["C"], i10[i], i20[i])
                    a = R.signal_at(i, by, e10, e20, d, side)
                    b = RS.hammer_signal(i, by, e10, e20, d, side, p)
                    if a is not None and a.get("entry") is not None:
                        seen += 1
                        self.assertIsNotNone(b, "%s %s %s" % (key, n, i))
                        self.assertAlmostEqual(a["entry"], b["entry"]); self.assertAlmostEqual(a["stop"], b["stop"])
                    elif a is None:
                        self.assertIsNone(b)
        self.assertGreater(seen, 10)

    def test_inside_candle_shape(self):
        by = {j: {"O": 100, "H": 102, "L": 98, "C": 101} for j in range(0, 12)}
        by[10] = {"O": 100, "H": 120, "L": 99, "C": 118}        # big green candle
        by[11] = {"O": 112, "H": 116, "L": 110, "C": 115}       # small candle fully inside it
        self.assertTrue(RS._inside(by, 10, 1.5, True))
        by[11] = {"O": 112, "H": 130, "L": 110, "C": 125}       # pokes far above -> not inside
        self.assertFalse(RS._inside(by, 10, 1.5, True))
        by[11] = {"O": 112, "H": 116, "L": 110, "C": 115}
        by[10] = {"O": 118, "H": 120, "L": 99, "C": 100}        # big RED candle is not a bullish setup
        self.assertFalse(RS._inside(by, 10, 1.5, True))

    def test_grids_are_well_formed(self):
        self.assertGreater(len(RS.hammer_grid()), 50)
        self.assertGreater(len(RS.inside_grid()), 50)
        for p in RS.hammer_grid().values(): self.assertEqual(set(p), set(RS.HAMMERS["H0 v3 (current)"]))


if __name__ == "__main__":
    unittest.main()
