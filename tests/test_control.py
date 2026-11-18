import datetime, os, tempfile, unittest
from trader.store import Store
from trader.state import RuntimeState
from trader.control import Controller
from trader.pin import PinFile
from trader.risk import RiskGuard
from trader.notify import Notifier, day_summary, format_event
from trader.bot import Bot
from trader.tg_api import TelegramAPI, TelegramError
from tests.fakes import FakeTransport, FixedRng

CHAT = "42"
T0 = datetime.datetime(2025, 11, 17, 10, 0, 0)


class Clock(object):
    def __init__(self): self.t = T0
    def __call__(self): return self.t


def make(live=True, pin=True):
    st = Store()
    state = RuntimeState(st, live_enabled=live, version="t")
    d = tempfile.mkdtemp()
    pf = PinFile(os.path.join(d, "pin"))
    if pin:
        pf.set("123456")
    clk = Clock()
    flats = []
    c = Controller(st, state, CHAT, pf, hooks={"flat": lambda: flats.append(1) or 2, "restart": lambda: flats.append("r")},
                   clock=clk, rng=FixedRng())
    return st, state, c, clk, flats


class ControlTests(unittest.TestCase):
    def test_whitelist(self):
        st, state, c, clk, _ = make()
        self.assertEqual(c.handle("999", "/pause"), [])
        self.assertFalse(state.paused)

    def test_pause_resume_persist(self):
        st, state, c, clk, _ = make()
        c.handle(CHAT, "/pause")
        self.assertTrue(state.paused)
        self.assertTrue(RuntimeState(st).paused)
        c.handle(CHAT, "/resume")
        self.assertFalse(state.paused)

    def test_flat_needs_code(self):
        st, state, c, clk, flats = make()
        r = c.handle(CHAT, "/flat")[0]
        self.assertIn("123456", r)
        self.assertEqual(flats, [])
        self.assertIn("closed 2", c.handle(CHAT, "/yes 123456")[0])
        self.assertEqual(flats, [1])
        self.assertIn("No such", c.handle(CHAT, "/yes 123456")[0])

    def test_code_expires(self):
        st, state, c, clk, flats = make()
        c.handle(CHAT, "/flat")
        clk.t += datetime.timedelta(seconds=121)
        self.assertIn("expired", c.handle(CHAT, "/yes 123456")[0])
        self.assertEqual(flats, [])

    def test_stop(self):
        st, state, c, clk, flats = make()
        c.handle(CHAT, "/stop"); c.handle(CHAT, "/yes 123456")
        self.assertTrue(state.stopped)
        self.assertEqual(flats, [1])

    def test_live_disabled(self):
        st, state, c, clk, _ = make(live=False)
        self.assertIn("not enabled", c.handle(CHAT, "/mode live")[0])
        self.assertEqual(state.mode, "shadow")

    def test_live_flow_pin(self):
        st, state, c, clk, _ = make()
        c.handle(CHAT, "/mode live"); c.handle(CHAT, "/yes 123456 123456")
        self.assertEqual(state.mode, "live")
        self.assertFalse(state.armed)
        c.handle(CHAT, "/arm live")
        self.assertIn("Wrong PIN", c.handle(CHAT, "/yes 123456 000000")[0])
        self.assertFalse(state.armed)
        c.handle(CHAT, "/yes 123456 123456")
        self.assertTrue(state.armed)
        self.assertTrue(state.live_active())
        clk.t = clk.t.replace(hour=15, minute=45)
        c.handle(CHAT, "/status")
        self.assertFalse(state.armed)

    def test_pin_lockout(self):
        st, state, c, clk, _ = make()
        c.handle(CHAT, "/mode live")
        for i in range(2):
            self.assertIn("Wrong PIN", c.handle(CHAT, "/yes 123456 1")[0])
        self.assertIn("locked", c.handle(CHAT, "/yes 123456 1")[0])
        self.assertIn("locked", c.handle(CHAT, "/mode live")[0])
        clk.t += datetime.timedelta(days=1)
        self.assertIn("Confirm", c.handle(CHAT, "/mode live")[0])

    def test_no_pin_set(self):
        st, state, c, clk, _ = make(pin=False)
        self.assertIn("No PIN", c.handle(CHAT, "/mode live")[0])

    def test_set_tighten_and_loosen(self):
        st, state, c, clk, _ = make()
        self.assertIn("applied now", c.handle(CHAT, "/set max_trades_per_day 1")[0])
        self.assertEqual(state.risk["max_trades_per_day"], 1)
        self.assertIn("Confirm", c.handle(CHAT, "/set max_trades_per_day 3")[0])
        c.handle(CHAT, "/yes 123456")
        self.assertEqual(state.risk["max_trades_per_day"], 1)
        self.assertEqual(state.pending_risk["max_trades_per_day"], 3)
        clk.t += datetime.timedelta(days=1)
        c.handle(CHAT, "/status")
        self.assertEqual(state.risk["max_trades_per_day"], 3)

    def test_set_rejects(self):
        st, state, c, clk, _ = make()
        self.assertIn("usage", c.handle(CHAT, "/set rr 5")[0])
        self.assertIn("between", c.handle(CHAT, "/set lots 9")[0])
        self.assertIn("Bad", c.handle(CHAT, "/set lots x")[0])

    def test_audit_hides_secrets(self):
        st, state, c, clk, _ = make()
        c.handle(CHAT, "/token SECRETTOKEN")
        c.handle(CHAT, "/yes 123456 123456")
        msgs = " ".join(e["msg"] for e in st.recent_events(20))
        self.assertNotIn("SECRETTOKEN", msgs)
        self.assertNotIn("123456", msgs)

    def test_readonly_commands(self):
        st, state, c, clk, _ = make()
        sid, _ = st.add_signal("2025-11-17", "NIFTY_22600PE", 10, "PE", "traded", entry=100, stop=90, target=130)
        tid, _ = st.add_trade(sid, "shadow", 1, "10:10", 100.0)
        st.close_trade(tid, "10:30", 130.0, "target", 3.0, 30.0)
        for cmd in ["/help", "/status", "/health", "/positions", "/signals", "/why 10:05", "/trades", "/summary",
                    "/risk", "/bars X", "/config", "/logs", "/replay", "/export", "/note hi", "/ack", "/foo"]:
            out = c.handle(CHAT, cmd)
            self.assertTrue(out and all(isinstance(x, str) for x in out), cmd)
        self.assertIn("+\u20b930", c.handle(CHAT, "/summary")[0])
        self.assertIn("NIFTY_22600PE", c.handle(CHAT, "/trades")[0])
        self.assertIn("Checked", c.handle(CHAT, "/debug analysis")[0])
        for bad in ("feed_ok", "token_ok", "armed=", "paused="):
            self.assertNotIn(bad, c.handle(CHAT, "/status")[0] + c.handle(CHAT, "/health")[0])

    def test_guard_via_controller(self):
        st, state, c, clk, _ = make()
        g = RiskGuard(st, state)
        self.assertTrue(g.allow_entry("2025-11-17", "shadow")[0])
        c.handle(CHAT, "/pause")
        self.assertFalse(g.allow_entry("2025-11-17", "shadow")[0])


class NotifyBotTests(unittest.TestCase):
    def test_notifier_never_raises(self):
        st = Store(); tr = FakeTransport(); n = Notifier(tr, CHAT, st)
        n("entry", {"symbol": "X", "qty": 1, "price": 1.0, "stop": .5, "target": 2.0, "t": "10:00"})
        self.assertEqual(len(tr.sent), 1)
        tr.fail = True
        n("exit", {"symbol": "X", "reason": "stop", "price": 1, "r": -1, "pnl": -1, "t": "10:30"})
        self.assertEqual(len(tr.sent), 1)
        self.assertTrue(st.recent_events(5, ("alert-send",)))

    def test_format_skips_noise(self):
        self.assertIsNone(format_event("signal", {"status": "skipped", "symbol": "X", "t": "", "reasons": ""}))
        self.assertIn("halt", format_event("halt", {"text": "halt now"}))

    def test_bot_offset_and_delete(self):
        st, state, c, clk, _ = make()
        tr = FakeTransport()
        tr.updates = [{"update_id": 5, "message": {"chat": {"id": 42}, "text": "/pause", "message_id": 1}},
                      {"update_id": 6, "message": {"chat": {"id": 42}, "text": "/token abc", "message_id": 2}}]
        b = Bot(tr, c, st, sleep=lambda s: None)
        self.assertEqual(b.poll_once(), 2)
        self.assertEqual(st.kv_get("tg_offset"), "7")
        self.assertEqual(tr.deleted, [(42, 2)])
        self.assertEqual(b.poll_once(), 0)

    def test_bot_offset_saved_before_handling(self):
        st, state, c, clk, _ = make()
        tr = FakeTransport()
        tr.updates = [{"update_id": 9, "message": {"chat": {"id": 42}, "text": "/pause", "message_id": 1}}]
        c.handle = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        b = Bot(tr, c, st, sleep=lambda s: None)
        with self.assertRaises(RuntimeError):
            b.poll_once()
        self.assertEqual(st.kv_get("tg_offset"), "10")

    def test_api_redacts_token(self):
        class S(object):
            def post(self, url, **k):
                raise RuntimeError("failed " + url)
        api = TelegramAPI("SECRET123", session=S())
        try:
            api.send_message(1, "x")
        except TelegramError as e:
            self.assertNotIn("SECRET123", str(e))
        else:
            self.fail("no error")

    def test_api_url(self):
        calls = []
        class R(object):
            def json(self): return {"ok": True, "result": []}
        class S(object):
            def post(self, url, **k):
                calls.append((url, k)); return R()
        TelegramAPI("T", session=S()).get_updates(5, 1)
        self.assertTrue(calls[0][0].endswith("/botT/getUpdates"))
        self.assertEqual(calls[0][1]["data"]["offset"], 5)


if __name__ == "__main__":
    unittest.main()
