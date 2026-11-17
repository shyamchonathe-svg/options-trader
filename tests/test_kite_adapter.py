import datetime, json, os, tempfile, time, unittest
from trader.adapters import kite_adapter as K
from trader.config import Config
from trader.daemon import Daemon
from trader.broker import PaperBroker
from trader.main import build
from trader.notify import Notifier
from trader.state import RuntimeState
from trader.store import Store
from tests.fakes import FakeTransport

D = datetime.datetime
DAY = "2026-11-17"                       # Tuesday


def inst(exch, name, strike, opt, expiry, token, lot=75, step_sym=None):
    return {"instrument_token": token, "exchange_token": token // 256, "tradingsymbol": "%s%s%s" % (name, int(strike), opt),
            "name": name, "last_price": 0.0, "expiry": expiry, "strike": float(strike), "tick_size": 0.05,
            "lot_size": lot, "instrument_type": opt, "segment": exch + "-OPT", "exchange": exch}


def dump(exch, name, base, step, lot, exp):
    rows, tok = [], 1000 if exch == "NFO" else 5000
    for k in range(-12, 13):
        for opt in ("CE", "PE"):
            tok += 1
            rows.append(inst(exch, name, base + k * step, opt, exp, tok, lot))
    # a later expiry that must be ignored
    rows.append(inst(exch, name, base, "CE", datetime.date(2026, 12, 1), tok + 1, lot))
    return rows


class FakeKite(object):
    def __init__(self, nifty_open=25200.0, sensex_open=81800.0):
        self.access = None
        self.profile_calls = 0
        self.fail_profile = False
        self.sessions = []
        self.hist_calls = 0
        self.nifty_open, self.sensex_open = nifty_open, sensex_open

    def set_access_token(self, t): self.access = t
    def login_url(self): return "https://kite.zerodha.com/connect/login?v=3&api_key=KEY"

    def generate_session(self, rt, api_secret=None):
        if rt == "bad":
            raise ValueError("TokenException")
        self.sessions.append(rt)
        return {"access_token": "AT-" + rt, "user_id": "AB1234"}

    def profile(self):
        self.profile_calls += 1
        if self.fail_profile:
            raise RuntimeError("TokenException")
        return {"user_id": "AB1234"}

    def quote(self, keys):
        out = {}
        if "NSE:NIFTY 50" in keys:
            out["NSE:NIFTY 50"] = {"instrument_token": 256265, "last_price": self.nifty_open + 10,
                                   "ohlc": {"open": self.nifty_open, "high": 0, "low": 0, "close": 25144.3}}
        if "BSE:SENSEX" in keys:
            out["BSE:SENSEX"] = {"instrument_token": 265, "last_price": self.sensex_open + 10,
                                 "ohlc": {"open": self.sensex_open, "high": 0, "low": 0, "close": 81592.45}}
        return out

    def instruments(self, exch):
        if exch == "NFO":
            return dump("NFO", "NIFTY", 25200, 50, 75, datetime.date(2026, 11, 17))
        if exch == "BFO":
            return dump("BFO", "SENSEX", 81800, 100, 20, datetime.date(2026, 11, 19))
        raise ValueError(exch)

    def historical_data(self, token, frm, to, interval):
        """Previous session (16 Nov... here 13 Nov Friday) 75 bars + today's bars for slots 0..9 except slot 4 (hole)
        for option tokens (index tokens have every bar). Time zone aware like the real client."""
        self.hist_calls += 1
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        is_index = token in (256265, 265)
        rows = []
        for dd, nbars in ((datetime.date(2026, 11, 13), 75), (datetime.date(2026, 11, 17), 10)):
            for s in range(nbars):
                if dd.day == 17 and s == 4 and not is_index:
                    continue
                t = D.combine(dd, datetime.time(9, 15)) + datetime.timedelta(minutes=5 * s)
                base = 100.0 + (token % 7) + s
                rows.append({"date": t.replace(tzinfo=ist), "open": base, "high": base + 2, "low": base - 2,
                             "close": base + 1, "volume": 10})
        # a post-close CAS bar that must be ignored
        rows.append({"date": D(2026, 11, 17, 15, 30, tzinfo=ist), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})
        return [r for r in rows if frm <= r["date"].replace(tzinfo=None) <= to]


def make(tmp=None, now=D(2026, 11, 17, 9, 0, 30), **kw):
    tmp = tmp or tempfile.mkdtemp()
    cfg = Config(home=tmp); cfg.ensure_dirs()
    cfg.env = {"KITE_API_KEY": "KEY", "KITE_API_SECRET": "SECRET"}
    kite = FakeKite(**kw)
    clock = {"now": now}
    p = K.KiteProvider(cfg, kite=kite, clock=lambda: clock["now"], sleep=lambda s: None)
    return p, kite, cfg, clock


class TestHelpers(unittest.TestCase):
    def test_parse_request_token(self):
        self.assertEqual(K.parse_request_token("abc123"), "abc123")
        self.assertEqual(K.parse_request_token("https://127.0.0.1/?request_token=XyZ9&action=login&status=success"), "XyZ9")

    def test_to_ist_naive(self):
        utc = datetime.timezone.utc
        self.assertEqual(K.to_ist_naive(D(2026, 11, 17, 3, 45, tzinfo=utc)), D(2026, 11, 17, 9, 15))
        self.assertEqual(K.to_ist_naive(D(2026, 11, 17, 9, 15)), D(2026, 11, 17, 9, 15))

    def test_tick_time_is_inverse_of_fromtimestamp_in_any_tz(self):
        epoch = 1763340300          # 2025-11-17 00:... just an arbitrary instant
        for tz in ("UTC", "Asia/Kolkata", "America/New_York"):
            os.environ["TZ"] = tz; time.tzset()
            naive_local = D.fromtimestamp(epoch)             # what KiteTicker produces
            got = K.tick_time_to_ist(naive_local)
            want = D.utcfromtimestamp(epoch) + datetime.timedelta(hours=5, minutes=30)
            self.assertEqual(got, want, tz)
        os.environ.pop("TZ", None); time.tzset()

    def test_slot(self):
        self.assertEqual(K.slot_of_time(D(2026, 11, 17, 9, 15)), 0)
        self.assertEqual(K.slot_of_time(D(2026, 11, 17, 15, 25)), 74)
        self.assertIsNone(K.slot_of_time(D(2026, 11, 17, 15, 30)))
        self.assertIsNone(K.slot_of_time(D(2026, 11, 17, 9, 10)))


class TestToken(unittest.TestCase):
    def test_no_token_then_exchange_then_ok(self):
        p, kite, cfg, clock = make()
        self.assertFalse(p.token_ok())
        msg = p.exchange_token("https://127.0.0.1/?request_token=RT1&status=success")
        self.assertIn("AB1234", msg)
        self.assertEqual(kite.sessions, ["RT1"])
        self.assertEqual(oct(os.stat(p.token_path).st_mode & 0o777), "0o600")
        self.assertTrue(p.token_ok())

    def test_token_from_yesterday_is_rejected(self):
        p, kite, cfg, clock = make()
        p.exchange_token("RT1")
        clock["now"] = D(2026, 11, 18, 8, 55)
        self.assertFalse(p.token_ok())

    def test_api_rejects_token(self):
        p, kite, cfg, clock = make()
        p.exchange_token("RT1"); p.verified_day = None
        kite.fail_profile = True
        self.assertFalse(p.token_ok())

    def test_bad_request_token_message_has_no_secret(self):
        p, kite, cfg, clock = make()
        msg = p.exchange_token("bad")
        self.assertIn("failed", msg)
        self.assertNotIn("SECRET", msg)
        self.assertFalse(os.path.exists(p.token_path))

    def test_config_text_shows_login(self):
        p, _, _, _ = make()
        self.assertIn("connect/login", p.config_text())


class TestMorning(unittest.TestCase):
    def plan_at(self, now, **kw):
        p, kite, cfg, clock = make(now=now, **kw)
        p.exchange_token("RT1")
        return p, kite, cfg, p.morning(DAY)

    def test_plan_shape_before_open(self):
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 9, 0, 30))
        names = dict((s.name, (s, pc, seeds)) for s, pc, seeds in plan["indexes"])
        n, s = names["NIFTY"], names["SENSEX"]
        self.assertEqual(n[0].symbol, "NSE:NIFTY 50"); self.assertEqual(s[0].symbol, "BSE:SENSEX")
        self.assertEqual(n[1], 25144.3); self.assertEqual(s[1], 81592.45)
        self.assertEqual(n[0].step, 50); self.assertEqual(s[0].step, 100)
        self.assertEqual(len(n[0].options), 2 * 11)                       # ATM +/-5 strikes, CE and PE
        # nearest expiry only (the December contract is ignored), quantity is the lot size from the dump
        self.assertTrue(all(o.symbol.startswith("NFO:NIFTY") for o in n[0].options))
        self.assertEqual(set(o.qty for o in n[0].options), {75}); self.assertEqual(set(o.qty for o in s[0].options), {20})
        strikes = sorted(set(o.strike for o in n[0].options))
        self.assertEqual(strikes[0], 25200 - 250 + 0); self.assertEqual(strikes[-1], 25200 + 250)   # ATM of open 25200
        # seeds: previous session closes, 75 bars, slot-ordered, post-close CAS excluded
        for sp in (n, s):
            for sym, closes in sp[2].items():
                self.assertEqual(len(closes), 75)
        self.assertEqual(plan["backfill"], [])                               # nothing complete at 09:00
        self.assertTrue(plan["feed"].needs_restart)
        # tokens are fixed from the dump: index token comes from the quote
        self.assertEqual(p.tokens["NSE:NIFTY 50"], 256265); self.assertEqual(p.tokens["BSE:SENSEX"], 265)
        self.assertEqual(len(plan["feed"].token_to_key), len(p.tokens))

    def test_dump_cached_for_expired_lookups(self):
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 9, 0, 30))
        files = sorted(os.listdir(cfg.instruments))
        self.assertEqual(files, ["2026-11-17_BFO.csv", "2026-11-17_NFO.csv"])

    def test_atm_follows_the_open_not_stale_close(self):
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 9, 30, 10), nifty_open=25400.0)
        n = [s for s, _, _ in plan["indexes"] if s.name == "NIFTY"][0]
        strikes = sorted(set(o.strike for o in n.options))
        self.assertEqual((strikes[0] + strikes[-1]) / 2, 25400)

    def test_backfill_complete_bars_only_holes_flat_and_ordered(self):
        # 09:36 -> slots 0..3 complete (slot 3 ends 09:35); slot 4 still running
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 9, 36, 0))
        bf = plan["backfill"]
        self.assertTrue(bf)
        self.assertEqual(max(r[1] for r in bf), 3)
        slots = [r[1] for r in bf]
        self.assertEqual(slots, sorted(slots))
        nsym = len(p.tokens)
        self.assertEqual(len(bf), nsym * 4)

    def test_backfill_fills_a_hole_with_previous_close(self):
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 9, 50, 0))     # slots 0..5 complete, slot 4 missing for options
        opt = [s for s, _, _ in plan["indexes"] if s.name == "NIFTY"][0].options[0].symbol
        by = dict((r[1], r) for r in plan["backfill"] if r[0] == opt)
        self.assertEqual(sorted(by), [0, 1, 2, 3, 4, 5])
        prev_c = by[3][5]
        self.assertEqual(by[4][2:], (prev_c, prev_c, prev_c, prev_c))    # flat bar like the live builder
        self.assertNotEqual(by[5][2], prev_c)

    def test_cas_bar_ignored(self):
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 15, 40, 0))
        self.assertTrue(all(r[1] <= 74 for r in plan["backfill"]))

    def test_history_for_reconciliation(self):
        p, kite, cfg, plan = self.plan_at(D(2026, 11, 17, 9, 0, 30))
        h = p.history(DAY, ["NSE:NIFTY 50", "unknown"])
        self.assertEqual(list(h), ["NSE:NIFTY 50"])
        self.assertEqual([b["slot"] for b in h["NSE:NIFTY 50"]], list(range(10)))
        self.assertEqual(set(h["NSE:NIFTY 50"][0]), {"slot", "O", "H", "L", "C"})

    def test_missing_quote_raises_for_daemon_retry(self):
        p, kite, cfg, clock = make()
        p.exchange_token("RT1")
        kite.quote = lambda keys: {}
        with self.assertRaises(RuntimeError):
            p.morning(DAY)


class TestFeed(unittest.TestCase):
    def mk(self):
        got = []
        f = K.KiteFeed("KEY", "AT", {1: "NFO:X", 2: "NSE:NIFTY 50"}, [2])
        f.set_handler(got.append)
        return f, got

    def test_option_uses_last_trade_time_and_volume(self):
        f, got = self.mk()
        os.environ["TZ"] = "Asia/Kolkata"; time.tzset()
        lt = D(2026, 11, 17, 9, 31, 12)
        f.handle_ticks([{"instrument_token": 1, "last_price": 101.5, "volume_traded": 500,
                         "last_trade_time": lt, "exchange_timestamp": D(2026, 11, 17, 9, 31, 20)}])
        self.assertEqual(len(got), 1)
        t = got[0]
        self.assertEqual((t.symbol, t.price, t.volume, t.ts), ("NFO:X", 101.5, 500, lt))
        os.environ.pop("TZ", None); time.tzset()

    def test_index_has_no_volume_uses_exchange_timestamp(self):
        f, got = self.mk()
        os.environ["TZ"] = "Asia/Kolkata"; time.tzset()
        f.handle_ticks([{"instrument_token": 2, "last_price": 25200.5, "exchange_timestamp": D(2026, 11, 17, 9, 30, 1)}])
        self.assertEqual((got[0].symbol, got[0].volume, got[0].ts), ("NSE:NIFTY 50", None, D(2026, 11, 17, 9, 30, 1)))
        os.environ.pop("TZ", None); time.tzset()

    def test_unknown_token_and_missing_volume_ignored(self):
        f, got = self.mk()
        f.handle_ticks([{"instrument_token": 99, "last_price": 1.0},
                        {"instrument_token": 1, "last_price": 100.0, "last_trade_time": D(2026, 11, 17, 9, 31, 0)}])
        self.assertEqual(got, [])

    def test_start_subscribes_full_mode_on_connect(self):
        calls = []

        class T(object):
            MODE_FULL = "full"
            def connect(self, threaded=False): calls.append(("connect", threaded))
            def subscribe(self, t): calls.append(("sub", t))
            def set_mode(self, m, t): calls.append(("mode", m, t))
            def close(self): calls.append("close")
        holder = {}

        def factory(k, a):
            holder["t"] = T(); return holder["t"]
        f = K.KiteFeed("KEY", "AT", {1: "NFO:X", 2: "NSE:NIFTY 50"}, [2], ticker_factory=factory)
        f.start()
        t = holder["t"]
        self.assertEqual(calls, [("connect", True)])
        t.on_connect(t, None)
        self.assertEqual(calls[1:], [("sub", [1, 2]), ("mode", "full", [1, 2])])
        f.stop()
        self.assertEqual(calls[-1], "close")


class FakeProv(object):
    """Provider whose morning() returns a KiteFeed-like object with needs_restart."""
    def token_ok(self): return True
    def morning(self, day):
        class F(object):
            needs_restart = True
            def set_handler(s, h): pass
            def subscribe(s, x): pass
            def start(s): pass
            def stop(s): pass
        from trader.engine import IndexSpec, OptionSpec
        spec = IndexSpec("NIFTY", "NSE:NIFTY 50", 50, [OptionSpec("NFO:N1CE", 25200.0, "CE", 75)])
        return {"indexes": [(spec, 25100.0, {})], "backfill": [], "feed": F()}
    def history(self, day, syms): return {}


class TestDaemonIntegration(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.cfg = Config(home=tmp); self.cfg.ensure_dirs()
        self.st = Store(self.cfg.db); self.state = RuntimeState(self.st, version="t")
        self.tr = FakeTransport(); self.n = Notifier(self.tr, "1", self.st)

    def test_hooks_wired_and_token_command(self):
        p, kite, cfg, clock = make()
        store, state, notifier, daemon, bot = build(self.cfg, self.tr, p)
        ctl = bot.ctl if hasattr(bot, "ctl") else None
        self.assertIn("token", (ctl.hooks if ctl else {"token": 1}))
        self.assertIn("config", (ctl.hooks if ctl else {"config": 1}))

    def test_reminder_and_restart_after_session(self):
        d = Daemon(self.st, self.state, self.n, FakeProv(), PaperBroker(), cfg=self.cfg, sender=self.n)
        d.step(D(2026, 11, 17, 9, 1, 0))
        self.assertIsNotNone(d.feed)
        d.step(D(2026, 11, 17, 15, 49, 0))
        self.assertFalse(d.restart_requested)
        d.step(D(2026, 11, 17, 15, 50, 5))
        self.assertTrue(d.restart_requested)
        self.assertTrue(any("Daily capture" in t for _, t in self.tr.sent))
        n = len([1 for _, t in self.tr.sent if "Daily capture" in t])
        d.step(D(2026, 11, 17, 15, 51, 0))
        self.assertEqual(len([1 for _, t in self.tr.sent if "Daily capture" in t]), n)    # once a day


if __name__ == "__main__":
    unittest.main()
