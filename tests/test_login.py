import datetime, json, tempfile, threading, time, unittest, urllib.request, urllib.error
from trader.login import LoginManager, LoginServer
from trader.main import build
from tests.test_daemon import Prov, tiny_plan, make, at, texts, DAY, D


class LProv(Prov):
    """Provider with the login() API; a good token only after a successful login."""
    def __init__(self, plan, user="AB1234"):
        Prov.__init__(self, plan, token=False)
        self.user, self.logins = user, []

    def login_url(self, state=None): return "https://kite/login?state=%s" % state

    def login(self, tok):
        if tok == "bad":
            return False, "failed", ""
        self.logins.append(tok)
        self.token = True
        return True, "Kite login OK for %s" % self.user, self.user

    def exchange_token(self, text): return self.login(text.strip())[1]


class Clk(object):
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


def rig(plan=None):
    prov = LProv(plan or tiny_plan())
    st, state, tr, d, cfg = make(prov)
    clk = Clk(at(8, 0))
    d.login = LoginManager(st, prov, d.notify, clk)
    return st, state, tr, d, prov, clk


def step(d, clk, t):
    clk.t = t
    d.step(t)


def state_of(link):
    return link.split("state=")[1].split()[0].split("\n")[0]


class Receiver(unittest.TestCase):
    def test_good_login_once(self):
        st, state, tr, d, prov, clk = rig()
        s = state_of(d.login.link())
        ok, *_ = d.login.handle({"status": "success", "request_token": "t1", "state": s})
        self.assertTrue(ok)
        ok2, *_ = d.login.handle({"status": "success", "request_token": "t2", "state": s})   # reuse
        self.assertFalse(ok2); self.assertEqual(prov.logins, ["t1"])

    def test_rejections(self):
        st, state, tr, d, prov, clk = rig()
        for p in ({"status": "success", "request_token": "t", "state": "nope"},
                  {"status": "success", "request_token": "t"},
                  {"status": "error", "request_token": "t", "state": state_of(d.login.link())},
                  {"status": "success", "state": state_of(d.login.link())}):
            self.assertFalse(d.login.handle(p)[0])
        self.assertEqual(prov.logins, [])
        self.assertIsNone(d.login.login_at())

    def test_expired_state(self):
        st, state, tr, d, prov, clk = rig()
        s = state_of(d.login.link())
        st.kv_set("login:state:" + s, str(int(time.time()) - 1))
        self.assertFalse(d.login.handle({"status": "success", "request_token": "t", "state": s})[0])

    def test_http_server(self):
        st, state, tr, d, prov, clk = rig()
        srv = LoginServer(d.login, port=0); srv.start()
        port = srv.port
        out = {}
        def web():
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/other" % port)
            except urllib.error.HTTPError as e:
                out["code"] = e.code
            r = urllib.request.urlopen("http://127.0.0.1:%d/redirect?status=success&request_token=SECRETTOK&state=%s" % (port, s))
            out["body"] = r.read().decode()
        s = state_of(d.login.link())
        th = threading.Thread(target=web); th.start()
        try:
            for _ in range(300):
                d.login.pump(); time.sleep(0.02)
                if "body" in out:
                    break
        finally:
            th.join(); srv.stop()
        self.assertEqual(out["code"], 404)
        self.assertIn("Login OK", out["body"]); self.assertNotIn("SECRETTOK", out["body"])
        self.assertNotIn("SECRETTOK", " ".join(texts(tr)))


class Flow(unittest.TestCase):
    def test_login_before_cutoff_trades(self):
        st, state, tr, d, prov, clk = rig()
        step(d, clk, at(8, 30))
        self.assertEqual(len([x for x in texts(tr) if "login needed" in x]), 1)
        step(d, clk, at(8, 31))
        self.assertEqual(len([x for x in texts(tr) if "login needed" in x]), 1)
        clk.t = at(9, 3)
        d.login.handle({"status": "success", "request_token": "t", "state": state_of(d.login.link())})
        step(d, clk, at(9, 4))
        self.assertIsNone(state.trading_blocked)
        self.assertTrue(d.engine.accepting)
        step(d, clk, at(9, 6))        # logged in: no more prompts
        self.assertEqual(len([x for x in texts(tr) if "login needed" in x]), 1)

    def test_late_login_is_data_only(self):
        st, state, tr, d, prov, clk = rig()
        for t in (at(8, 30), at(8, 40), at(8, 50), at(9, 5), at(9, 12), at(9, 16), at(9, 17)):
            step(d, clk, t)
        self.assertEqual(len([x for x in texts(tr) if "login needed" in x]), 5)
        self.assertEqual(len([x for x in texts(tr) if "DATA_ONLY" in x]), 1)
        self.assertIsNone(d.engine)
        clk.t = at(11, 0)
        d.login.handle({"status": "success", "request_token": "t", "state": state_of(d.login.link())})
        step(d, clk, at(11, 1))
        self.assertTrue(state.trading_blocked.startswith("late login"))
        self.assertFalse(d.engine.accepting)
        self.assertEqual(d.engine.block_reason, "late_login")
        self.assertEqual(st.trades_for_day("2026-11-17"), [])
        state.live_enabled = True; state.mode = "live"; state.armed = True
        self.assertFalse(state.live_active())

    def test_restart_keeps_decision(self):
        st, state, tr, d, prov, clk = rig()
        step(d, clk, at(9, 17))
        clk.t = at(10, 0)
        d.login.handle({"status": "success", "request_token": "t", "state": state_of(d.login.link())})
        step(d, clk, at(10, 1))
        st2, state2, tr2, d2, *_ = (st, None, None, None)
        from trader.daemon import Daemon
        from trader.state import RuntimeState
        state2 = RuntimeState(st, version="t")
        d2 = Daemon(st, state2, d.notify, prov, d.broker, cfg=d.cfg)
        d2.login = LoginManager(st, prov, d.notify, clk)
        clk.t = at(10, 5); d2.step(clk.t)
        self.assertTrue(state2.trading_blocked)

    def test_no_login_all_day_then_recover_after_close(self):
        bars = [("NIFTY_index", 0, 22500.0, 22510.0, 22490.0, 22505.0), ("NIFTY_22500CE", 0, 100.0, 101.0, 99.0, 100.5)]
        st, state, tr, d, prov, clk = rig(tiny_plan(backfill=bars))
        for t in (at(9, 17), at(15, 32), at(16, 1)):
            step(d, clk, t)
        self.assertTrue(any("No login today" in x for x in texts(tr)))
        self.assertIsNone(d.engine)
        clk.t = at(16, 30)
        d.login.handle({"status": "success", "request_token": "t", "state": state_of(d.login.link())})
        step(d, clk, at(16, 31))
        self.assertTrue(any("Recovered" in x for x in texts(tr)))
        self.assertFalse(any(x.startswith("signal") for x in texts(tr)))     # no per-signal flood during recovery
        self.assertTrue(state.token_ok)
        self.assertEqual(len(st.trades_for_day("2026-11-17")), 0)         # sims never mix into real trades
        self.assertEqual(st.trades_for_day("2026-11-17"), [])
        n = len(tr.sent)
        step(d, clk, at(16, 32)); step(d, clk, at(16, 40))
        self.assertEqual(len(tr.sent), n)

    def test_skip_and_holiday(self):
        st, state, tr, d, prov, clk = rig()
        step(d, clk, at(8, 0))
        d.set_skip(True)
        step(d, clk, at(8, 30)); step(d, clk, at(9, 17))
        self.assertEqual(tr.sent, [])
        d.set_skip(False)
        d.add_holiday("2026-11-17")
        step(d, clk, at(8, 31))
        self.assertEqual(tr.sent, [])

    def test_arm_refused_when_blocked(self):
        st, state, tr, d, prov, clk = rig()
        step(d, clk, at(9, 17))
        self.assertTrue(state.trading_blocked)
        from trader.main import build
        self.assertIn("No trading today", self._arm(st, state, d))

    def _arm(self, st, state, d):
        from trader.control import Controller
        c = Controller(st, state, "1", None, hooks={}, clock=lambda: at(9, 20))
        state.live_enabled = True; state.mode = "live"
        return c.cmd_arm(["live"], at(9, 20))



class Sim(unittest.TestCase):
    def test_late_sim_trade(self):
        st, state, tr, d, prov, clk = rig()
        sid, _ = st.add_signal("2026-11-17", "X", 4, "CE", "missed", "late_login", entry=100.0, stop=90.0, target=130.0,
                               rules_version="v", gap=0, dist=0)
        for slot, (o, h, l, c) in {5: (100, 105, 95, 104), 6: (104, 131, 103, 128)}.items():
            st.put_bar("2026-11-17", "X", slot, o, h, l, c, 0, "backfill")
        d.day = "2026-11-17"
        self.assertEqual(d._simulate_missed(), 1)
        self.assertEqual(d._simulate_missed(), 0)                          # idempotent
        t = st.sim_trades_for_day("2026-11-17")[0]
        self.assertEqual((t["exit_reason"], t["exit_px"], t["r_mult"], t["entry_t"], t["exit_t"]), ("target", 130.0, 3.0, "09:40", "09:45"))
        self.assertEqual(st.trades_for_day("2026-11-17"), [])
        from trader.notify import day_summary
        txt = day_summary(st, "2026-11-17")
        self.assertIn("[late-sim, not a real trade] X", txt)
        self.assertIn("entry 09:40 @ 100.00  stop 90.00  target 130.00  exit 09:45 @ 130.00 (target)  R +3.00 held 5 min", txt)
        self.assertIn("ran up to +3.1R", txt)


class Hol(unittest.TestCase):
    def test_builtin_holiday(self):
        st, state, tr, d, prov, clk = rig()
        h = D(2026, 11, 24)
        for t in (h.replace(hour=8, minute=30), h.replace(hour=9, minute=17)):
            d.step(t)
        self.assertEqual(tr.sent, [])



class Misc(unittest.TestCase):
    def test_reminders_once(self):
        st, state, tr, d, prov, clk = rig()
        day = D(2026, 12, 18)
        d.step(day.replace(hour=9, minute=0)); self.assertFalse(any("REMINDER" in x for x in texts(tr)))
        d.step(day.replace(hour=10, minute=1)); d.step(day.replace(hour=10, minute=2))
        self.assertEqual(len([x for x in texts(tr) if "REMINDER" in x and "Kite Connect renewal" in x]), 1)

    def test_no_bogus_recovery_after_restart_post_close(self):
        st, state, tr, d, prov, clk = rig()
        clk.t = at(9, 3)
        d.login.handle({"status": "success", "request_token": "t", "state": state_of(d.login.link())})
        step(d, clk, at(9, 4))                                      # normal session started
        from trader.daemon import Daemon
        from trader.state import RuntimeState
        d2 = Daemon(st, RuntimeState(st, version="t"), d.notify, prov, d.broker, cfg=d.cfg)
        d2.login = LoginManager(st, prov, d.notify, clk)
        clk.t = at(15, 55); d2.step(clk.t)                          # process restarted after the close
        self.assertFalse(any("Recovered" in x for x in texts(tr)))

    def test_no_trade_report(self):
        st, state, tr, d, prov, clk = rig()
        from trader.notify import day_summary
        st.add_signal("2026-11-17", "X", 4, "CE", "rejected", "not-ATM", rules_version="v", gap=0, dist=3)
        txt = day_summary(st, "2026-11-17")
        self.assertIn("NO TRADE today", txt); self.assertIn("not-ATM 1", txt)


if __name__ == "__main__":
    unittest.main()
