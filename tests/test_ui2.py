"""UI 2.0: plain-English text, fixed-capital sizing, exact-candle correction (live open fix)."""
import datetime
import unittest

from tests.test_engine import make, drive, patched, DAY, CE
from trader import present as P
from trader.notify import format_event
from trader.pipeline import Pipeline, FIX_WAIT_S
from trader.store import Store


class Present(unittest.TestCase):
    def test_pretty_symbol(self):
        self.assertEqual(P.pretty_symbol("NFO:NIFTY26NOV25300PE"), "Nifty 25300 PE")
        self.assertEqual(P.pretty_symbol("BFO:SENSEX26N1982100PE"), "Sensex 82100 PE")
        self.assertEqual(P.pretty_symbol("NFO:NIFTY26N1725250CE"), "Nifty 25250 CE")
        self.assertEqual(P.pretty_symbol("TST_100CE"), "TST_100CE")

    def test_inr(self):
        self.assertEqual(P.inr(100000), "\u20b91,00,000")
        self.assertEqual(P.inr(-1234.4, sign=True), "-\u20b91,234")
        self.assertEqual(P.inr(406, sign=True), "+\u20b9406")

    def test_trade_texts_carry_only_trade_facts(self):
        e = format_event("entry", {"symbol": "NFO:NIFTY26NOV25300PE", "t": "09:40", "price": 31.35, "stop": 20, "target": 60,
                                   "qty": 65, "index": "Nifty", "index_px": 25318.4})
        for want in ("Nifty 25300 PE", "09:40", "31.35", "25,318.40", "65"):
            self.assertIn(want, e)
        self.assertNotIn("stop", e.lower())
        x = format_event("exit", {"symbol": "NFO:NIFTY26NOV25300PE", "t": "09:55", "price": 25.1, "reason": "stop", "r": -1, "pnl": -406.25,
                                  "qty": 65, "entry_px": 31.35, "entry_t": "09:40", "index": "Nifty", "entry_index_px": 25318.4, "index_px": 25290.0})
        for want in ("09:55", "25.10", "stop-loss hit", "-\u20b9406", "25,290.00"):
            self.assertIn(want, x)

    def test_signals_are_never_sent(self):
        for st in ("traded", "rejected", "skipped", "missed", "dropped"):
            self.assertIsNone(format_event("signal", {"symbol": "X", "t": "09:40", "status": st, "reasons": "gap-dir"}))


class Sizing(unittest.TestCase):
    def run_day(self, price, capital, qty_lot=75):
        eng, st, br = make(qty=qty_lot)
        eng.capital, eng.use_pct = capital, 0.9
        got = []
        eng.notify = lambda k, p: got.append((k, p))
        with patched({(5, "CE"): price - 5}):
            from tests.test_engine import flat
            drive(eng, 12, ce=lambda s: flat(price) if s != 3 else flat(price))
        return st, got

    def test_whole_lots_within_90_percent(self):
        eng, st, br = make(qty=75)
        eng.capital, eng.use_pct = 100000, 0.9
        self.assertEqual(eng._qty(eng._ix["TST"].opts[CE], 100.0), 75 * 12)    # 90000 / 7500 = 12 lots
        self.assertEqual(eng._qty(eng._ix["TST"].opts[CE], 118.0), 75 * 10)    # 90000 / 8850 = 10.17 -> 10
        self.assertEqual(eng._qty(eng._ix["TST"].opts[CE], 1300.0), 0)         # one lot (97,500) is over 90,000
        eng.capital = None
        self.assertEqual(eng._qty(eng._ix["TST"].opts[CE], 100.0), 75)         # legacy: one lot

    def test_trade_uses_sized_qty_and_reports_index_value(self):
        eng, st, br = make(qty=75)
        eng.capital, eng.use_pct = 100000, 0.9
        got = []
        eng.notify = lambda k, p: got.append((k, p))
        with patched({(5, "CE"): 95.0}):
            drive(eng, 12)
        (t,) = st.trades_for_day(DAY)
        self.assertEqual(t["qty"], 75 * 12)
        kinds = [k for k, _ in got]
        self.assertEqual(kinds, ["entry", "exit"])                              # no signal messages at all
        self.assertEqual(got[0][1]["index_px"], 100.0)
        self.assertEqual(got[0][1]["index"], "Tst")
        self.assertIn("entry_px", got[1][1])

    def test_unaffordable_is_rejected_not_traded(self):
        eng, st, br = make(qty=75)
        eng.capital, eng.use_pct = 5000, 0.9
        with patched({(5, "CE"): 95.0}):
            drive(eng, 12)
        self.assertEqual(st.trades_for_day(DAY), [])
        s = [x for x in st.signals_for_day(DAY) if x["slot"] == 5][0]
        self.assertEqual((s["status"], s["reasons"]), ("rejected", "capital"))


class FakeEngine(object):
    def __init__(self):
        self.bars = []

    def on_bar(self, sym, slot, o, h, l, c):
        self.bars.append((sym, slot, o, h, l, c))

    def on_open(self, *a):
        pass


def live(slot, o, h, l, c, n=5, src="live"):
    return {"day": DAY, "slot": slot, "O": o, "H": h, "L": l, "C": c, "n": n, "src": src}


class ExactCandle(unittest.TestCase):
    def setUp(self):
        self.st, self.eng = Store(), FakeEngine()
        self.t0 = datetime.datetime(2026, 11, 17, 9, 20, 1)       # 1 s after slot 0 closed
        self.exact = {}
        self.calls = []

        def fixer(sym, slot):
            self.calls.append((sym, slot))
            return self.exact.get((sym, slot))
        near = {"OPT_NEAR": ("IDX", 100.0, 50.0), "OPT_FAR": ("IDX", 300.0, 50.0)}
        self.p = Pipeline(self.st, self.eng, ["IDX", "OPT_NEAR", "OPT_FAR"], fixer=fixer, near=near)
        self.p.last_price["IDX"] = 100.0

    def at(self, s):
        return self.t0 + datetime.timedelta(seconds=s)

    def test_only_tradable_symbols_wait_and_get_corrected(self):
        self.exact[("OPT_NEAR", 0)] = (11.0, 15.0, 9.0, 12.0)
        self.exact[("IDX", 0)] = (100.0, 101.0, 99.0, 100.5)
        for sym in ("IDX", "OPT_NEAR", "OPT_FAR"):
            self.p._bars(sym, [live(0, 10.0, 15.0, 9.0, 12.0)])
        self.assertEqual([b[0] for b in self.eng.bars], ["OPT_FAR"])         # far strike: live bar straight away
        self.p.service(self.at(0))                                           # before the settle time: no request yet
        self.assertEqual(self.calls, [])
        self.p.service(self.at(8)); self.p.service(self.at(9))
        got = dict((b[0], b[2:]) for b in self.eng.bars)
        self.assertEqual(got["OPT_NEAR"], (11.0, 15.0, 9.0, 12.0))           # the exchange open replaced the live open
        self.assertEqual(self.p.stats["fixed"], 2)
        self.assertEqual(len(self.st.get_bars(DAY, "OPT_NEAR", "exact")), 1)
        self.assertEqual(self.st.get_bars(DAY, "OPT_NEAR", "live")[0]["o"], 10.0)    # the live bar stays on record

    def test_not_published_retries_then_falls_back_to_live(self):
        self.p._bars("OPT_NEAR", [live(0, 10.0, 15.0, 9.0, 12.0)])
        self.p.service(self.at(8))
        self.assertEqual(self.eng.bars, [])
        n = len(self.calls)
        self.p.service(self.at(9)); self.assertEqual(len(self.calls), n)     # retry pause
        self.p.service(self.at(8 + FIX_WAIT_S + 1))
        self.assertEqual(self.eng.bars, [("OPT_NEAR", 0, 10.0, 15.0, 9.0, 12.0)])
        self.assertEqual(self.p.stats["fallback"], 1)

    def test_error_in_fixer_never_blocks(self):
        def boom(sym, slot):
            raise RuntimeError("api down")
        self.p.fixer = boom
        self.p._bars("IDX", [live(0, 100, 101, 99, 100)])
        self.p.service(self.at(8)); self.p.service(self.at(8 + FIX_WAIT_S + 1))
        self.assertEqual(len(self.eng.bars), 1)

    def test_order_within_a_symbol_is_kept(self):
        self.p._bars("IDX", [live(0, 100, 101, 99, 100)])
        self.p._bars("IDX", [live(1, 100, 101, 99, 100, n=0, src="flat")])   # filler queued behind the held bar
        self.assertEqual(self.eng.bars, [])
        self.exact[("IDX", 0)] = (100, 101, 99, 100)
        self.p.service(self.at(8)); self.p.service(self.at(9))
        self.assertEqual([b[1] for b in self.eng.bars], [0, 1])

    def test_rate_limit_and_drain(self):
        for i in range(5):
            self.p.near["O%d" % i] = ("IDX", 100.0, 50.0)
            self.p._bars("O%d" % i, [live(0, 100, 101, 99, 100)])
        self.p.service(self.at(8))
        self.assertEqual(len(self.calls), 2)                                 # at most 2 requests per step
        self.p.drain_holds()
        self.assertEqual(len(self.eng.bars), 5)


if __name__ == "__main__":
    unittest.main()
