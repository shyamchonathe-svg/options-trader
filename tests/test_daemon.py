import datetime, json, os, tempfile, unittest
from trader.broker import PaperBroker
from trader.config import Config, load_env, write_env
from trader.daemon import Daemon
from trader.engine import IndexSpec, OptionSpec
from trader.export import make_export
from trader.feed import Tick
from trader.main import run
from trader.notify import Notifier
from trader.recon import reconcile
from trader.replay import run_dataset
from trader.state import RuntimeState
from trader.store import Store
from trader.watchdog import decide
from trader import rules_v3 as R
from tests.fakes import FakeTransport
from tests.test_tick_path import fill_holes, FIX

D = datetime.datetime
DAY = D(2026, 11, 17, 0, 0)          # Tuesday


def at(h, m, s=0, day=DAY):
    return day.replace(hour=h, minute=m, second=s)


class Prov(object):
    def __init__(self, plan=None, token=True, fail=0, hist=None):
        self.plan, self.token, self.fail, self.hist = plan, token, fail, hist or {}
        self.calls = 0

    def token_ok(self): return self.token

    def morning(self, day):
        self.calls += 1
        if self.calls <= self.fail:
            raise RuntimeError("dump not ready")
        return self.plan

    def history(self, day, syms): return self.hist


def tiny_plan(backfill=None):
    spec = IndexSpec("NIFTY", "NIFTY_index", 50, [OptionSpec("NIFTY_22500CE", 22500.0, "CE", 1)])
    seeds = {"NIFTY_index": [22500.0] * 25, "NIFTY_22500CE": [100.0] * 25}
    return {"indexes": [(spec, 22500.0, seeds)], "backfill": backfill or [], "feed": None}


def make(prov, tmp=None):
    tmp = tmp or tempfile.mkdtemp()
    cfg = Config(home=tmp); cfg.ensure_dirs()
    st = Store(cfg.db); state = RuntimeState(st, version="t")
    tr = FakeTransport(); n = Notifier(tr, "1", st)
    d = Daemon(st, state, n, prov, PaperBroker(), cfg=cfg, sender=n)
    return st, state, tr, d, cfg


def texts(tr): return [t for _, t in tr.sent]


class Life(unittest.TestCase):
    def test_no_provider_day(self):
        st, state, tr, d, cfg = make(None)
        for t in (at(8, 0), at(9, 11), at(15, 32), at(16, 1)):
            d.step(t)
        self.assertTrue(any("no market-data source" in x for x in texts(tr)))
        self.assertEqual(len(tr.docs), 0)          # the nightly export is saved on the VM, not sent to Telegram
        n = len(tr.sent)
        d2 = Daemon(st, state, Notifier(tr, "1", st), None, PaperBroker(), cfg=cfg)
        d2.step(at(16, 2))                       # restart later same day: nothing repeated
        self.assertEqual(len(tr.sent), n); self.assertEqual(len(tr.docs), 0)
        self.assertTrue(os.path.exists(os.path.join(cfg.exports, "trader_2026-11-17.db.gz")))

    def test_weekend_silent(self):
        st, state, tr, d, cfg = make(None)
        sat = D(2026, 11, 21)
        d.step(at(9, 11, day=sat)); d.step(at(15, 46, day=sat))
        self.assertEqual(tr.sent, [])

    def test_token_missing_once(self):
        st, state, tr, d, cfg = make(Prov(tiny_plan(), token=False))
        for s in (0, 40, 80):
            d.step(at(9, 0, s % 60) + datetime.timedelta(seconds=s))
        self.assertEqual(len([x for x in texts(tr) if "token" in x.lower()]), 1)
        d.step(at(9, 11))
        self.assertIn("NOT READY", [x for x in texts(tr) if "READY" in x][0])

    def test_morning_retry(self):
        p = Prov(tiny_plan(), fail=2)
        st, state, tr, d, cfg = make(p)
        d.step(at(9, 0)); d.step(at(9, 0, 10)); d.step(at(9, 1)); d.step(at(9, 2))
        self.assertEqual(p.calls, 3)
        self.assertIsNotNone(d.engine)
        self.assertEqual(len([x for x in texts(tr) if "Morning setup failed" in x]), 1)
        d.step(at(9, 11))
        self.assertTrue(any(x.startswith("READY") for x in texts(tr)))

    def test_feed_stale_and_recover(self):
        class F(object):
            def set_handler(self, h): pass
            def subscribe(self, s): pass
            def start(self): pass
            def stop(self): self.stopped = True
        plan = tiny_plan(); plan["feed"] = F()
        st, state, tr, d, cfg = make(Prov(plan))
        d.step(at(9, 0)); d.step(at(9, 16))
        d.on_tick(Tick("NIFTY_index", at(9, 21, 30), 22500.0, None)); d.on_tick(Tick("NIFTY_index", at(9, 21, 40), 22501.0, None))
        d.step(at(9, 22))
        self.assertFalse(any("market data has stopped" in x for x in texts(tr)))
        d.step(at(9, 25)); d.step(at(9, 26))
        self.assertEqual(len([x for x in texts(tr) if "market data has stopped" in x]), 1)
        d.on_tick(Tick("NIFTY_index", at(9, 26, 30), 22500.0, None)); d.step(at(9, 26, 31))
        d.on_tick(Tick("NIFTY_index", at(9, 26, 40), 22501.0, None)); d.step(at(9, 26, 41))
        self.assertTrue(any("Market data is back" in x for x in texts(tr)))

    def test_backfill_records_missed_not_trades(self):
        # a clean uptrend where the option dips and re-rises would signal; here we only check the accepting flag path
        st, state, tr, d, cfg = make(Prov(tiny_plan(backfill=[("NIFTY_index", 0, 22500.0, 22510.0, 22495.0, 22505.0),
                                                             ("NIFTY_22500CE", 0, 100.0, 101.0, 99.0, 100.5)])))
        d.step(at(10, 0))
        self.assertTrue(d.engine.accepting)
        self.assertEqual(st.trades_for_day("2026-11-17"), [])
        self.assertEqual(len(st.get_bars("2026-11-17", "NIFTY_index", "backfill")), 1)

    def test_live_armed_without_broker_is_disarmed(self):
        st, state, tr, d, cfg = make(None)
        state.live_enabled = True; state.mode = "live"; state.armed = True
        d.step(at(10, 0))
        self.assertFalse(state.armed)
        self.assertTrue(any("no live broker" in x for x in texts(tr)))

    def test_flat_hook(self):
        st, state, tr, d, cfg = make(Prov(tiny_plan()))
        self.assertEqual(d.flat(), 0)
        d.step(at(10, 0))
        self.assertEqual(d.flat(), 0)

    def test_recon(self):
        st = Store()
        st.put_bar("2026-11-17", "X", 5, 1, 1, 1, 100.0, 3, "live")
        st.put_bar("2026-11-17", "X", 6, 1, 1, 1, 100.0, 3, "live")
        hist = {"X": [{"slot": 5, "O": 1, "H": 1, "L": 1, "C": 100.0}, {"slot": 6, "O": 1, "H": 1, "L": 1, "C": 101.0}]}
        self.assertEqual(reconcile(st, "2026-11-17", hist)[:2], (2, 1))
        self.assertEqual(len(st.get_bars("2026-11-17", "X", "hist")), 2)


class Misc(unittest.TestCase):
    def test_watchdog_decide(self):
        mon = D(2026, 11, 16)
        self.assertEqual(decide(at(10, 0, day=mon), 30, None), "ok")
        self.assertEqual(decide(at(10, 0, day=mon), 500, None), "restart")
        self.assertEqual(decide(at(10, 0, day=mon), 500, 60), "wait")
        self.assertEqual(decide(at(10, 0, day=mon), None, 5000), "restart")
        self.assertEqual(decide(at(18, 0, day=mon), 5000, None), "ok")
        self.assertEqual(decide(at(10, 0, day=D(2026, 11, 21)), 5000, None), "ok")

    def test_env_roundtrip_and_mode(self):
        p = os.path.join(tempfile.mkdtemp(), "s", "trader.env")
        write_env(p, {"TG_TOKEN": "abc:def", "TG_CHAT_ID": "7"})
        write_env(p, {"LIVE_ENABLED": "0"})
        self.assertEqual(load_env(p), {"TG_TOKEN": "abc:def", "TG_CHAT_ID": "7", "LIVE_ENABLED": "0"})
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")

    def test_export(self):
        d = tempfile.mkdtemp(); st = Store(os.path.join(d, "t.db"))
        st.event("INFO", "x", "y")
        out = make_export(st, os.path.join(d, "ex"), "2026-11-17")
        import gzip
        self.assertTrue(len(gzip.open(out).read()) > 100)

    def test_main_loop_restart_and_commands(self):
        home = tempfile.mkdtemp()
        write_env(os.path.join(home, "secrets", "trader.env"), {"TG_TOKEN": "t:t", "TG_CHAT_ID": "42"})
        cfg = Config(home=home)
        tr = FakeTransport()
        tr.updates = [{"update_id": 1, "message": {"chat": {"id": 42}, "text": "/status", "message_id": 1}},
                      {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/restart", "message_id": 2}},
                      {"update_id": 3, "message": {"chat": {"id": 42}, "text": "/yes 000000", "message_id": 3}}]
        # find the code by running one loop first
        r = run(cfg, tr, max_loops=1, sleep=lambda s: None, clock=lambda: at(10, 0))
        self.assertEqual(r, "loops")
        self.assertTrue(texts(tr)[0].startswith("Trader "))
        code = [t for t in texts(tr) if "Reply: /yes" in t][0].split("/yes ")[1].split()[0]
        tr.updates = [{"update_id": 4, "message": {"chat": {"id": 42}, "text": "/yes " + code, "message_id": 4}}]
        r = run(cfg, tr, max_loops=5, sleep=lambda s: None, clock=lambda: at(10, 0))
        self.assertEqual(r, "loops")        # new process: confirm codes are in memory only, so a stale code is refused
        self.assertTrue(any("No such confirmation" in t for t in texts(tr)))
        self.assertTrue(os.path.exists(cfg.heartbeat))


@unittest.skipUnless(os.path.exists(FIX), "replay fixture not shipped to VM")
class EndToEnd(unittest.TestCase):
    def test_full_day_through_daemon_equals_replay(self):
        data = json.load(open(FIX))
        total = 0
        for key in ("20261029/NIFTY", "20261106/SENSEX", "20261102/NIFTY"):
            ds = fill_holes(data[key])
            y, m, dd = [int(x) for x in ds["day"].split("-")]
            base = D(y, m, dd, 9, 15)
            ixn = ds["index"]; ix_sym = ixn + "_index"
            opts = [OptionSpec(n, float(R.parse_strike(n)[0]), R.parse_strike(n)[1], 1) for n in sorted(ds["opts"])]
            series = {ix_sym: ds["idx"]}; series.update(ds["opts"])
            plan = {"indexes": [(IndexSpec(ixn, ix_sym, ds["step"], opts), ds["prev_close"],
                                 dict((k, v["seed"]) for k, v in series.items()))], "backfill": [], "feed": None}
            st, state, tr, d, cfg = make(Prov(plan, hist={}))
            vol = dict((s, 0) for s in series)
            def send(sym, ts, px):
                v = None if sym == ix_sym else vol.__setitem__(sym, vol[sym] + 1) or vol[sym]
                d.on_tick(Tick(sym, ts, px, v))
            d.step(base.replace(hour=9, minute=0, second=1))
            for sym in series:
                send(sym, base - datetime.timedelta(minutes=1), series[sym]["bars"]["0"][0])
            for s in range(ds["idx"]["n"]):
                t0 = base + datetime.timedelta(minutes=5 * s)
                for sym in [ix_sym] + sorted(ds["opts"]):
                    b = series[sym]["bars"].get(str(s))
                    for sec, px in ((5, b[0]), (20, b[1]), (35, b[2]), (50, b[3])):
                        send(sym, t0 + datetime.timedelta(seconds=sec), px)
                d.step(t0 + datetime.timedelta(minutes=5, seconds=3))
            d.step(base.replace(hour=15, minute=32)); d.step(base.replace(hour=16, minute=1))
            s2, b2 = Store(), PaperBroker()
            run_dataset(s2, b2, ds)
            f = lambda s: [(t["symbol"], t["slot"], t["entry"], t["stop"], t["exit_reason"], t["r_mult"]) for t in s.trades_for_day(ds["day"])]
            self.assertEqual(f(st), f(s2), key)
            total += len(f(s2))
            self.assertTrue(any(x.startswith("Day report") for x in texts(tr)), key)
        self.assertGreaterEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
