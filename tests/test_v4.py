import unittest

from trader import rules_v4 as V4
from tests.test_engine import make, drive, patched, DAY


def vix(st, vals):
    for slot, v in vals.items():
        st.put_bar(DAY, "INDIA VIX", slot, v, v, v, v, 0, "vix")


class Regime(unittest.TestCase):
    def test_bands(self):
        self.assertFalse(V4.regime(11.99)["trade"])
        m = V4.regime(12.0)
        self.assertEqual((m["rr"], m["hold"], m["max_trades"]), (4.0, 12, 2))
        self.assertEqual(V4.regime(15.0)["name"], "mid")
        h = V4.regime(15.01)
        self.assertEqual((h["rr"], h["hold"], h["max_trades"]), (2.0, 6, 2))
        u = V4.regime(None)
        self.assertEqual((u["rr"], u["hold"], u["max_trades"], u["version"]), (3.0, 12, 1, "v3.0"))

    def test_fall(self):
        self.assertTrue(V4.vix_fell(16.0, 15.1))
        self.assertFalse(V4.vix_fell(16.0, 15.3))
        self.assertFalse(V4.vix_fell(None, 15.0))


class EngineV4(unittest.TestCase):
    def test_low_vix_no_trades(self):
        eng, st, br = make()
        vix(st, {0: 11.0, 3: 11.0})
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
        self.assertEqual(st.trades_for_day(DAY), [])
        (s,) = st.signals_for_day(DAY)
        self.assertEqual((s["status"], s["reasons"]), ("skipped", "vix-below-12"))

    def test_vix_fall_skips_day(self):
        eng, st, br = make()
        vix(st, {0: 16.0, 2: 15.0, 3: 15.0})
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
        self.assertEqual(st.trades_for_day(DAY), [])
        self.assertEqual(st.signals_for_day(DAY)[0]["reasons"], "vix-fell-5pct")

    def test_high_vix_two_trades_sequential(self):
        eng, st, br = make()
        vix(st, {0: 17.0, 3: 17.0})
        with patched({(5, "CE"): 95.0, (25, "CE"): 95.0, (40, "CE"): 95.0}):
            drive(eng, 50)
        self.assertEqual((eng.rr, eng.max_hold, eng.rules_version), (2.0, 6, "v4.0"))
        trs = st.trades_for_day(DAY)
        self.assertEqual(len(trs), 2)                     # third refused: 2 per day
        sig = dict((s["slot"], s) for s in st.signals_for_day(DAY))
        self.assertEqual(sig[40]["reasons"], "already-traded-today")

    def test_high_vix_no_overlap(self):
        eng, st, br = make()
        vix(st, {0: 17.0, 3: 17.0})
        with patched({(5, "CE"): 95.0, (8, "CE"): 95.0}):
            drive(eng, 30)
        sig = dict((s["slot"], s) for s in st.signals_for_day(DAY))
        self.assertEqual(sig[8]["reasons"], "position-open")
        self.assertEqual(len(st.trades_for_day(DAY)), 1)

    def test_mid_vix_two_trades_4r(self):
        eng, st, br = make()
        vix(st, {0: 13.0, 3: 13.0})
        with patched({(5, "CE"): 95.0, (25, "CE"): 95.0}):
            drive(eng, 45)
        self.assertEqual((eng.rr, eng.max_hold, eng.max_trades), (4.0, 12, 2))
        self.assertEqual(len(st.trades_for_day(DAY)), 2)

    def test_no_vix_falls_back_to_v3(self):
        eng, st, br = make()
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
        self.assertEqual((eng.rr, eng.max_hold, eng.rules_version), (3.0, 12, "v3.0"))
        self.assertEqual(len(st.trades_for_day(DAY)), 1)

    def test_v4_requires_nearest_strike(self):
        # index 100, strike 100 -> ATM; a strike 1 step (index step 100 in the test spec) away is rejected in v4 but allowed in v3
        eng, st, br = make(strike=160.0)
        vix(st, {0: 17.0, 3: 17.0})
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
        sig = st.signals_for_day(DAY)
        self.assertTrue(sig and all(s["reasons"] == "not-ATM" for s in sig if s["status"] == "rejected"))
        eng2, st2, br2 = make(strike=160.0)
        with patched({(5, "CE"): 95.0}):
            drive(eng2, 20)
        self.assertEqual(len(st2.trades_for_day(DAY)), 1)                     # no VIX = v3: 0.6 step is allowed

    def test_restart_decides_the_same(self):
        eng, st, br = make()
        vix(st, {0: 17.0, 3: 17.0})
        with patched({(5, "CE"): 95.0}):
            drive(eng, 12)
        self.assertEqual(st.kv_get("regime-%s" % DAY).split("|")[0], "high")


class GapRecovery(unittest.TestCase):
    def test_pure(self):
        bars = {0: {"H": 100.0, "L": 98.0}, 1: {"H": 100.5, "L": 99.0}, 2: {"H": 101.5, "L": 100.0}}
        self.assertFalse(V4.gap_lifted("PE", 101.0, bars, 1))       # not back to the previous close yet
        self.assertTrue(V4.gap_lifted("PE", 101.0, bars, 2))        # recovered on candle 2, signal on candle 2
        self.assertFalse(V4.gap_lifted(None, 101.0, bars, 2))
        self.assertTrue(V4.gap_lifted("CE", 99.5, bars, 1))         # gap-up recovered when the low reaches the previous close
        late = dict(bars)
        late[12] = {"H": 200.0, "L": 0.0}
        self.assertFalse(V4.gap_lifted("PE", 150.0, late, 13))      # recovery after 10:15 does not count

    def _run(self, ix):
        eng, st, br = make(prev_close=101.0)                          # open 100: gap-down 0.99% -> PE only
        vix(st, {0: 17.0, 3: 17.0})
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20, ix=ix)
        return st

    def test_recovered_within_hour_allows_ce(self):
        st = self._run(lambda s: (100, 101.5, 99.5, 100) if s >= 3 else (100, 100.5, 99.5, 100))
        self.assertEqual(len(st.trades_for_day(DAY)), 1)

    def test_not_recovered_stays_blocked(self):
        st = self._run(lambda s: (100, 100.5, 99.5, 100))
        self.assertEqual(st.trades_for_day(DAY), [])
        self.assertEqual(st.signals_for_day(DAY)[0]["reasons"], "gap-dir")

    def test_v3_days_keep_the_old_rule(self):
        eng, st, br = make(prev_close=101.0)                          # no VIX -> v3 settings: no recovery exception
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20, ix=lambda s: (100, 101.5, 99.5, 100))
        self.assertEqual(st.trades_for_day(DAY), [])


if __name__ == "__main__":
    unittest.main()
