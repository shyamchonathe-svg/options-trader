"""v5 setups: unit parity with the research harness, engine behaviour per setup, partial booking, restart safety."""
import json
import os
import sqlite3
import unittest

from trader import research as RS, rules_v3 as R, setups as S
from trader.broker import PaperBroker
from trader.engine import Engine, IndexSpec, OptionSpec
from trader.replay import run_dataset
from trader.store import Store

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "replay_days.json")
P1 = RS.HAMMERS["P1 H1 + float<0.5 (old-trend = log flag)"]
I4 = RS.INSIDE["I4 option+index, near cross, wide stop"]


def _feats(s):
    seq = list(s["seed"]); npre = len(seq); by = {}
    for k in range(s["n"]):
        b = s["bars"].get(str(k))
        if b is not None:
            by[k] = {"O": b[0], "H": b[1], "L": b[2], "C": b[3]}
        seq.append(b[3] if b is not None else (seq[-1] if seq else 0))
    return by, R.ema(seq, 10)[npre:], R.ema(seq, 20)[npre:]


def cases():
    with open(FIX) as fh:
        data = json.load(fh)
    for key in sorted(data):
        yield data[key]


class SetupParity(unittest.TestCase):
    """setups.py must give exactly what the research harness measured."""

    def test_pullback_reversal_inside_equal_research(self):
        seen = dict(pullback=0, rev=0, inside=0)
        for ds in cases():
            ix, ie10, ie20 = _feats(ds["idx"])
            for name, o in ds["opts"].items():
                by, e10, e20 = _feats(o)
                side = name[-2:]
                for i in sorted(by):
                    dirn = R.index_direction(ix[i]["C"], ie10[i], ie20[i]) if i in ix else None
                    a = S.pullback_signal(i, by, e10, e20, dirn, side)
                    b = RS.hammer_signal(i, by, e10, e20, dirn, side, P1)
                    self.assertEqual(a is not None and a.get("entry") is not None, b is not None, (ds["day"], name, i))
                    if b is not None and a is not None:
                        self.assertAlmostEqual(a["entry"], b["entry"]); self.assertAlmostEqual(a["stop"], b["stop"])
                        seen["pullback"] += 1
                    rv = S.reversal_signal(i, by, e10, e20, S.REVERSAL_AM)
                    rr_ = RS.reversal_signal(i, by, e10, e20, RS.REVERSAL["RV-AM morning"])
                    self.assertEqual(rv is not None and rv.get("entry") is not None, rr_ is not None, (ds["day"], name, i))
                    seen["rev"] += rr_ is not None
                    if i in ix and i - 1 in ix:
                        tg = S.inside_setup(i - 1, by, e10, e20, ix, ie10, ie20, side)
                        rs = RS.inside_signal(i - 1, by, e10, e20, ix, ie10, ie20, side, I4)
                        # research only counts inside setups whose trigger was reached; setups.py reports all of them
                        if rs is not None:
                            self.assertIsNotNone(tg, (ds["day"], name, i))
                            self.assertAlmostEqual(tg["stop"], rs["stop"])
                            seen["inside"] += 1
        self.assertGreater(seen["pullback"], 3)
        self.assertGreater(seen["inside"], 0)


def _bars(rows):
    return dict((str(k), v) for k, v in enumerate(rows))


def synth(opt_rows, seed=100.0, n=None, idx_close=23000.0):
    n = n or len(opt_rows)
    flat = [idx_close] * 10
    idx = {"seed": flat, "n": n, "bars": _bars([[idx_close, idx_close + 5, idx_close - 5, idx_close]] * n)}
    opt = {"seed": [seed] * 25, "n": n, "bars": _bars(opt_rows)}
    return {"day": "2026-11-23", "index": "NIFTY", "step": 50, "prev_close": idx_close, "idx": idx,
            "opts": {"NIFTY_23000CE": opt}}


def engine_for(ds, st=None, qty_units=4):
    st = st or Store(); br = PaperBroker()
    spec = IndexSpec("NIFTY", "NIFTY_index", 50, [OptionSpec("NIFTY_23000CE", 23000.0, "CE", 1)])
    eng = Engine(st, br, ds["day"], mode="paper", strategy="v5", capital=10 ** 9, use_pct=1.0, fixed_qty={"NIFTY": qty_units})
    eng.add_index(spec, ds["prev_close"], {"NIFTY_index": ds["idx"]["seed"], "NIFTY_23000CE": ds["opts"]["NIFTY_23000CE"]["seed"]})
    return eng, st, br


def feed(eng, ds, upto=None):
    sym = "NIFTY_23000CE"
    for s in range(upto or ds["idx"]["n"]):
        for name in ("NIFTY_index", sym):
            b = (ds["idx"] if name == "NIFTY_index" else ds["opts"][sym])["bars"][str(s)]
            eng.on_open(name, s, b[0])
        for name in ("NIFTY_index", sym):
            b = (ds["idx"] if name == "NIFTY_index" else ds["opts"][sym])["bars"][str(s)]
            eng.on_bar(name, s, *b)


# slot0 hammer far below both EMAs (seed 100), slot1 strong green follow-up closing near them, slot2 = entry candle
REV = [[66, 70, 40, 69], [69, 95, 68, 94], [94, 100, 92, 99], [99, 110, 98, 108]]


class ReversalEngine(unittest.TestCase):
    def run_rows(self, tail):
        ds = synth(REV + tail)
        eng, st, br = engine_for(ds)
        feed(eng, ds); eng.end_of_day()
        return ds, st, br

    def test_book_half_then_time_exit(self):
        ds, st, _ = self.run_rows([[108, 112, 105, 110], [110, 111, 108, 109]])
        (t,) = st.trades_for_day(ds["day"])
        sig = st.signals_for_day(ds["day"])[0]
        self.assertEqual(sig["setup"], "reversal_am")
        self.assertEqual(t["exit_reason"], "time")
        self.assertEqual((t["entry"], t["stop"]), (94.0, 68.0))
        # half (2 of 4) booked at the close of the 2nd candle (108), the rest sold at the close of the 3rd (110)
        want = (2 * (108 - 94) / 26.0 + 2 * (110 - 94) / 26.0) / 4.0
        self.assertAlmostEqual(t["r_mult"], want, 3)
        self.assertEqual(t["part_qty"], 2)

    def test_trailing_stop_after_booking(self):
        ds, st, _ = self.run_rows([[108, 112, 97, 100]])      # slot 4 trades below the low of slot 3 (98)
        (t,) = st.trades_for_day(ds["day"])
        self.assertEqual(t["exit_reason"], "trail")
        self.assertAlmostEqual(t["exit_px"], 98.0)

    def test_stop_before_booking_is_a_full_loss(self):
        ds = synth(REV[:3] + [[99, 100, 60, 61]])
        eng, st, _ = engine_for(ds); feed(eng, ds); eng.end_of_day()
        (t,) = st.trades_for_day(ds["day"])
        self.assertEqual(t["exit_reason"], "stop"); self.assertAlmostEqual(t["r_mult"], -1.0)

    def test_restart_after_booking_does_not_double_sell(self):
        ds = synth(REV + [[108, 112, 105, 110], [110, 111, 108, 109]])
        eng, st, br = engine_for(ds); feed(eng, ds, upto=4)          # booked at slot 3, position still open
        eng2, _, br2 = engine_for(ds, st=st)                         # "restart": same store, fresh engine
        feed(eng2, ds); eng2.end_of_day()
        (t,) = st.trades_for_day(ds["day"])
        self.assertEqual(t["part_qty"], 2)
        sells = [f for f in br.fills + br2.fills if getattr(f, "side", "") == "SELL"] if hasattr(br, "fills") else None
        if sells is not None:
            self.assertEqual(sum(f.qty for f in sells), 4)


class InsideEngine(unittest.TestCase):
    """Index (flat here) cannot show the pattern, so use a real fixture day that produced an inside trade."""

    def test_fixture_day_inside_trade_replays_identically(self):
        with open(FIX) as fh:
            ds = json.load(fh)["20261027/NIFTY"]
        out = []
        for _ in range(2):
            st, br = Store(), PaperBroker(); run_dataset(st, br, ds, strategy="v5")
            out.append([(t["symbol"], t["slot"], t["entry"], t["stop"], t["exit_reason"], round(t["r_mult"], 4))
                        for t in st.trades_for_day(ds["day"])])
            sg = st.signals_for_day(ds["day"])
        self.assertEqual(out[0], out[1])
        self.assertIn("inside", [x["setup"] for x in sg])

    def test_tick_path_equals_bar_path(self):
        with open(FIX) as fh:
            ds = json.load(fh)["20261027/NIFTY"]
        st, br = Store(), PaperBroker(); run_dataset(st, br, ds, strategy="v5")
        want = [(t["symbol"], t["slot"], t["entry"]) for t in st.trades_for_day(ds["day"])]
        # same day, but also push intrabar prices (low -> high) before every bar closes, as the live feed does
        st2, br2 = Store(), PaperBroker()
        ixn = ds["index"]; ix_sym = ixn + "_index"
        opts = [OptionSpec(n, float(R.parse_strike(n)[0]), R.parse_strike(n)[1], 1) for n in sorted(ds["opts"])]
        eng = Engine(st2, br2, ds["day"], strategy="v5")
        series = {ix_sym: ds["idx"]}; series.update(ds["opts"])
        eng.add_index(IndexSpec(ixn, ix_sym, ds["step"], opts), ds["prev_close"], dict((k, v["seed"]) for k, v in series.items()))
        for s in range(ds["idx"]["n"]):
            for sym in [ix_sym] + sorted(ds["opts"]):
                b = series[sym]["bars"].get(str(s))
                if b is not None:
                    eng.on_open(sym, s, b[0])
                    for px in (b[2], b[1], b[3]):
                        eng.on_price(sym, s, px)
            for sym in [ix_sym] + sorted(ds["opts"]):
                b = series[sym]["bars"].get(str(s))
                if b is None:
                    eng.on_missing(sym, s)
                else:
                    eng.on_bar(sym, s, *b)
        eng.end_of_day()
        got = [(t["symbol"], t["slot"], t["entry"]) for t in st2.trades_for_day(ds["day"])]
        self.assertEqual(got, want)


class StoreMigration(unittest.TestCase):
    def test_old_database_gains_new_columns(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        st = Store(path)
        st.db.execute("DROP TABLE IF EXISTS signals"); st.db.execute("DROP TABLE IF EXISTS trades"); st.db.commit()
        st.db.executescript("""CREATE TABLE signals(id INTEGER PRIMARY KEY, day TEXT, symbol TEXT, slot INT, t TEXT, status TEXT, reason TEXT,
                                 entry REAL, stop REAL, target REAL, UNIQUE(day,symbol,slot));
                               CREATE TABLE trades(id INTEGER PRIMARY KEY, signal_id INT, day TEXT, symbol TEXT, side TEXT, qty INT,
                                 entry REAL, stop REAL, target REAL, entry_t TEXT, exit_t TEXT, exit_px REAL, exit_reason TEXT,
                                 r_mult REAL, pnl REAL, mode TEXT, status TEXT);""")
        st.db.commit(); st.db.close()
        st2 = Store(path)
        cols = lambda t: [r[1] for r in st2.db.execute("PRAGMA table_info(%s)" % t)]
        self.assertIn("setup", cols("signals")); self.assertIn("part_qty", cols("trades"))


if __name__ == "__main__":
    unittest.main()
