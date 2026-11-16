import datetime
import os
import tempfile
import unittest

from trader import instruments as I

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "instruments_bfo_20250904.csv")
D = datetime.date


def _row(name, ex, sym, tok, exp, strike, opt, lot="75"):
    return {"instrument_token": str(tok), "exchange_token": "1", "tradingsymbol": sym, "name": name,
            "last_price": "0", "expiry": exp, "strike": str(strike), "tick_size": "0.05",
            "lot_size": lot, "instrument_type": opt, "segment": ex + "-OPT", "exchange": ex}


def _nifty_rows():
    rows = []
    t = 1000
    for exp in ("2025-09-09", "2025-09-16"):
        for k in range(24400, 24800, 50):
            for opt in ("CE", "PE"):
                t += 1
                rows.append(_row("NIFTY", "NFO", "NIFTY%s%d%s" % (exp[5:7] + exp[8:], k, opt), t, exp, k, opt))
    rows.append(_row("NIFTYNXT50", "NFO", "NIFTYNXT50X", 5, "2025-09-05", 70000, "CE"))
    return rows


class SensexFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = I.load_rows(FIX)

    def test_nearest_expiry_and_atm(self):
        exp, atm, sel = I.plan(self.rows, "SENSEX", D(2025, 9, 4), 80312.0)
        self.assertEqual(exp, D(2025, 9, 11))
        self.assertEqual(atm, 80300)
        self.assertEqual(len(sel), 6)
        self.assertEqual(sorted(set(c.strike for c in sel)), [80200.0, 80300.0, 80400.0])
        syms = [c.symbol for c in sel]
        self.assertIn("SENSEX2591180300CE", syms)
        self.assertTrue(all(c.exchange == "BFO" and c.lot_size == 20 for c in sel))

    def test_expiry_day_still_counts(self):
        exp, _, _ = I.plan(self.rows, "SENSEX", D(2025, 9, 11), 80300.0)
        self.assertEqual(exp, D(2025, 9, 11))
        exp, _, _ = I.plan(self.rows, "SENSEX", D(2025, 9, 12), 80300.0)
        self.assertEqual(exp, D(2025, 9, 18))

    def test_key_is_exchange_symbol(self):
        _, _, sel = I.plan(self.rows, "SENSEX", D(2025, 9, 4), 80300.0)
        c = [c for c in sel if c.symbol == "SENSEX2591180300CE"][0]
        self.assertEqual(c.key, "BFO:SENSEX2591180300CE")


class NiftySynthetic(unittest.TestCase):
    def test_nifty_plan_ignores_other_names(self):
        exp, atm, sel = I.plan(_nifty_rows(), "NIFTY", D(2025, 9, 8), 24574.0)
        self.assertEqual(exp, D(2025, 9, 9))
        self.assertEqual(atm, 24550)
        self.assertEqual(sorted(set(c.strike for c in sel)), [24500.0, 24550.0, 24600.0])
        self.assertTrue(all(c.name == "NIFTY" for c in sel))

    def test_rounding_halfway_is_stable(self):
        self.assertEqual(I.atm_strike(24575.0, 50), 24600)
        self.assertEqual(I.atm_strike(24574.9, 50), 24550)

    def test_missing_strike_raises(self):
        rows = [r for r in _nifty_rows() if not (r["strike"] == "24600" and r["instrument_type"] == "PE")]
        with self.assertRaises(I.InstrumentError):
            I.plan(rows, "NIFTY", D(2025, 9, 8), 24550.0)

    def test_no_future_expiry_raises(self):
        with self.assertRaises(I.InstrumentError):
            I.plan(_nifty_rows(), "NIFTY", D(2025, 12, 1), 24550.0)


class Cache(unittest.TestCase):
    def test_cache_dump_filters_and_dates(self):
        rows = _nifty_rows() + [_row("BANKNIFTY", "NFO", "BN1", 9, "2025-09-30", 50000, "CE")]
        d = tempfile.mkdtemp()
        p = I.cache_dump(rows, d, D(2025, 9, 8))
        self.assertTrue(p.endswith("2025-09-08_NFO.csv"))
        back = I.load_rows(p)
        self.assertTrue(all(r["name"] == "NIFTY" for r in back))
        self.assertEqual(len(back), 2 * 8 * 2)
        self.assertFalse(os.path.exists(p + ".tmp"))

    def test_cache_refuses_empty(self):
        with self.assertRaises(I.InstrumentError):
            I.cache_dump([_row("BANKNIFTY", "NFO", "BN1", 9, "2025-09-30", 50000, "CE")], tempfile.mkdtemp(), D(2025, 9, 8))


if __name__ == "__main__":
    unittest.main()
