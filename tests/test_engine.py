import unittest
from unittest import mock

from trader import rules_v3 as R
from trader.broker import PaperBroker
from trader.engine import Engine, IndexSpec, OptionSpec, Series
from trader.store import Store

DAY = "2026-11-17"
CE, PE = "TST_100CE", "TST_100PE"


def flat(p, w=1.0):
    return (p, p + w, p - w, p)


def spec(strike=100.0, qty=75, extra=()):
    return IndexSpec("TST", "TST_index", 100,
                     [OptionSpec(CE, strike, "CE", qty), OptionSpec(PE, strike, "PE", qty)] + list(extra))


def make(prev_close=100.0, **kw):
    st, br = Store(), PaperBroker()
    eng = Engine(st, br, DAY)
    eng.add_index(spec(**kw), prev_close)
    return eng, st, br


def drive(eng, n, ix=None, ce=None, pe=None, extra=()):
    fns = [("TST_index", ix or (lambda s: flat(100.0))), (CE, ce or (lambda s: flat(100.0))),
           (PE, pe or (lambda s: flat(100.0)))] + [(x, (lambda s: flat(100.0))) for x in extra]
    for s in range(n):
        for sym, f in fns:
            b = f(s)
            if b is not None:
                eng.on_open(sym, s, b[0])
        for sym, f in fns:
            b = f(s)
            if b is None:
                eng.on_missing(sym, s)
            else:
                eng.on_bar(sym, s, *b)
    eng.end_of_day()


def fake_signal(hits, midday=False):
    """hits: {(slot, side): stop}. Mimics rules_v3.signal_at's two-phase contract."""
    def f(i, by, e10, e20, dirn, side, rr=3.0):
        if (i, side) not in hits:
            return None
        sig = {"i": i, "hammer": i, "midday": midday, "t": R.tstr(i)}
        if i + 1 not in by:
            sig["entry"] = None
            return sig
        entry, stop = by[i + 1]["O"], hits[(i, side)]
        risk = entry - stop
        if risk <= 0:
            sig["entry"] = None
            return sig
        sig.update(entry=entry, stop=stop, R=risk, target=entry + rr * risk, note="fake")
        return sig
    return f


def patched(hits, **kw):
    return mock.patch.object(R, "signal_at", fake_signal(hits, **kw))


class Exits(unittest.TestCase):
    def test_stop(self):
        eng, st, br = make()
        ce = lambda s: (100, 101, 94, 96) if s == 7 else flat(100.0)
        with patched({(5, "CE"): 95.0}):
            drive(eng, 30, ce=ce)
        (t,) = st.trades_for_day(DAY)
        self.assertEqual((t["exit_reason"], t["r_mult"], t["exit_px"], t["entry_t"], t["exit_t"]),
                         ("stop", -1.0, 95.0, "09:45", "09:50"))
        self.assertAlmostEqual(t["pnl"], -5.0 * 75)

    def test_target(self):
        eng, st, br = make()
        ce = lambda s: (100, 116, 99, 110) if s == 9 else flat(100.0)
        with patched({(5, "CE"): 95.0}):
            drive(eng, 30, ce=ce)
        (t,) = st.trades_for_day(DAY)
        self.assertEqual((t["exit_reason"], t["r_mult"], t["exit_px"]), ("target", 3.0, 115.0))

    def test_stop_checked_before_target_on_same_bar(self):
        eng, st, br = make()
        ce = lambda s: (100, 120, 90, 100) if s == 6 else flat(100.0)
        with patched({(5, "CE"): 95.0}):
            drive(eng, 30, ce=ce)
        self.assertEqual(st.trades_for_day(DAY)[0]["exit_reason"], "stop")

    def test_time_exit_after_12_bars_at_close(self):
        eng, st, br = make()
        ce = lambda s: (100, 102, 99, 103) if s == 17 else flat(100.0)
        with patched({(5, "CE"): 95.0}):
            drive(eng, 30, ce=ce)
        (t,) = st.trades_for_day(DAY)
        self.assertEqual((t["exit_reason"], t["exit_t"], t["exit_px"]), ("time", R.tstr(17), 103))
        self.assertAlmostEqual(t["r_mult"], 0.6)

    def test_end_of_day_closes_open_position(self):
        eng, st, br = make()
        with patched({(5, "CE"): 95.0}):
            drive(eng, 10)
        (t,) = st.trades_for_day(DAY)
        self.assertEqual(t["exit_reason"], "time")
        self.assertEqual(st.open_trades(), [])


class Filters(unittest.TestCase):
    def test_one_position_per_day(self):
        eng, st, br = make()
        with patched({(5, "CE"): 95.0, (25, "CE"): 95.0}):
            drive(eng, 40)
        sig = dict((s["slot"], s) for s in st.signals_for_day(DAY))
        self.assertEqual(sig[5]["status"], "traded")
        self.assertEqual((sig[25]["status"], sig[25]["reasons"]), ("rejected", "one-position"))
        self.assertEqual(len(st.trades_for_day(DAY)), 1)

    def test_gap_direction_rejects_wrong_side(self):
        eng, st, br = make(prev_close=99.0)          # +1.01% gap up -> only CE allowed
        with patched({(5, "PE"): 95.0}):
            drive(eng, 20)
        (s,) = st.signals_for_day(DAY)
        self.assertEqual((s["status"], s["reasons"]), ("rejected", "gap-dir"))
        self.assertEqual(st.trades_for_day(DAY), [])

    def test_strike_distance(self):
        eng, st, br = make(strike=200.0)             # 1.0 step away: allowed
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
        self.assertEqual(st.signals_for_day(DAY)[0]["status"], "traded")
        eng, st, br = make(strike=300.0)             # 2.0 steps away: rejected
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
        (s,) = st.signals_for_day(DAY)
        self.assertEqual((s["status"], s["reasons"]), ("rejected", "not-ATM"))

    def test_midday_is_skipped_not_traded(self):
        eng, st, br = make()
        with patched({(5, "CE"): 95.0}, midday=True):
            drive(eng, 20)
        (s,) = st.signals_for_day(DAY)
        self.assertEqual((s["status"], s["reasons"]), ("skipped", "midday"))
        self.assertEqual(br.fills, [])

    def test_bad_risk_is_dropped(self):
        eng, st, br = make()
        with patched({(5, "CE"): 100.0}):            # stop == entry -> R<=0
            drive(eng, 20)
        (s,) = st.signals_for_day(DAY)
        self.assertEqual((s["status"], s["reasons"]), ("dropped", "R<=0"))
        self.assertEqual(br.fills, [])

    def test_two_strikes_same_slot_first_by_name_wins(self):
        st, br = Store(), PaperBroker()
        eng = Engine(st, br, DAY)
        eng.add_index(IndexSpec("TST", "TST_index", 100,
                                [OptionSpec("B_CE", 100.0, "CE", 1), OptionSpec("A_CE", 100.0, "CE", 1)]), 100.0)
        syms = ("TST_index", "A_CE", "B_CE")
        with patched({(5, "CE"): 95.0}):
            for s in range(20):
                for sym in syms:
                    eng.on_open(sym, s, 100.0)
                for sym in syms:
                    eng.on_bar(sym, s, 100.0, 101.0, 99.0, 100.0)
            eng.end_of_day()
        got = dict((x["symbol"], x["status"]) for x in st.signals_for_day(DAY))
        self.assertEqual(got, {"A_CE": "traded", "B_CE": "rejected"})


class Timing(unittest.TestCase):
    def test_entry_is_placed_at_the_open_before_the_entry_bar_closes(self):
        eng, st, br = make()
        with patched({(5, "CE"): 95.0}):
            for s in range(6):
                for sym in ("TST_index", CE, PE):
                    eng.on_open(sym, s, 100.0)
                for sym in ("TST_index", CE, PE):
                    eng.on_bar(sym, s, 100.0, 101.0, 99.0, 100.0)
            self.assertEqual(br.fills, [])             # signal pending: entry bar not started
            eng.on_open("TST_index", 6, 100.0)
            self.assertEqual(br.fills, [])             # option open still unknown
            eng.on_open(CE, 6, 101.5)
            self.assertEqual(len(br.fills), 1)         # bar 6 is still open
            self.assertEqual(br.fills[0].ref_price, 101.5)
            self.assertEqual(st.open_trades()[0]["entry_px"], 101.5)


class Idempotent(unittest.TestCase):
    def test_refeeding_same_day_changes_nothing(self):
        eng, st, br = make()
        ce = lambda s: (100, 101, 94, 96) if s == 7 else flat(100.0)
        with patched({(5, "CE"): 95.0}):
            drive(eng, 30, ce=ce)
            n = (len(st.signals_for_day(DAY)), len(st.trades_for_day(DAY)), len(br.fills))
            eng2 = Engine(st, br, DAY)                  # "restart": new engine, same store and broker
            eng2.add_index(spec(), 100.0)
            drive(eng2, 30, ce=ce)
        self.assertEqual((len(st.signals_for_day(DAY)), len(st.trades_for_day(DAY)), len(br.fills)), n)

    def test_late_and_duplicate_bars_are_ignored(self):
        eng, st, br = make()
        with patched({(5, "CE"): 95.0}):
            drive(eng, 20)
            eng.on_bar(CE, 3, 1, 2, 0.5, 1.5)
            eng.on_bar(CE, 19, 1, 2, 0.5, 1.5)
        self.assertEqual(len(br.fills), 2)
        self.assertEqual(len(st.trades_for_day(DAY)), 1)


class SeriesEma(unittest.TestCase):
    def test_matches_batch_ema_with_seed_and_holes(self):
        seed = [100.0, 101.5, 99.0, 103.0]
        today = [104.0, None, 105.5, None, None, 102.0, 101.0]
        s = Series(seed)
        seq = list(seed)
        for k, c in enumerate(today):
            if c is None:
                s.missing(k)
                seq.append(seq[-1])
            else:
                s.add(k, {"O": c, "H": c, "L": c, "C": c})
                seq.append(c)
        n = len(seed)
        self.assertEqual([s.e10[k] for k in range(len(today))], R.ema(seq, 10)[n:])
        self.assertEqual([s.e20[k] for k in range(len(today))], R.ema(seq, 20)[n:])

    def test_skipped_slots_are_filled_as_missing(self):
        s = Series([10.0])
        s.add(3, {"O": 12, "H": 12, "L": 12, "C": 12})
        self.assertEqual(s.next, 4)
        self.assertNotIn(1, s.by)
        self.assertIn(1, s.e10)


if __name__ == "__main__":
    unittest.main()
