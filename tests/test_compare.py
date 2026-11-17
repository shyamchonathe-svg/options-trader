import random, unittest
from trader import rules_v3 as R
from trader.compare import run_exit, compare
from tests.test_login import rig, step, at, texts, D


def bars(spec, start=5):
    return dict((start + k, {"O": o, "H": h, "L": l, "C": c}) for k, (o, h, l, c) in enumerate(spec))


class Exits(unittest.TestCase):
    def test_baseline_matches_research_exit(self):
        rnd = random.Random(7)
        for _ in range(300):
            px, by = 100.0, {}
            for j in range(5, 40):
                o = px; c = o * (1 + rnd.uniform(-.03, .03)); h = max(o, c) * (1 + rnd.uniform(0, .02)); l = min(o, c) * (1 - rnd.uniform(0, .02))
                by[j] = {"O": o, "H": h, "L": l, "C": c}; px = c
            entry, stop = by[5]["O"], by[5]["O"] * 0.9
            a = R.simulate_exit(by, 4, entry, stop)
            b = run_exit(by, 4, entry, stop, rr=3.0, hold=12)
            self.assertEqual(round(a[0], 9), round(b[0], 9)); self.assertEqual((a[1], a[2]), (b[1], b[2]))

    def test_trend_day_trail_beats_fixed_target(self):
        # entry 100, stop 90 (R=10). Runs to 160 (+6R) over many bars with higher lows, then reverses.
        spec = [(100, 112, 99, 111), (111, 125, 110, 124), (124, 140, 122, 138), (138, 152, 136, 150), (150, 161, 148, 160), (160, 176, 158, 174), (174, 192, 172, 190), (190, 205, 188, 203), (203, 203, 130, 135)]
        by = bars(spec)
        fixed = run_exit(by, 4, 100.0, 90.0, rr=3.0, hold=12)
        trail = run_exit(by, 4, 100.0, 90.0, rr=None, hold=None, trail=3, arm=1.0)
        self.assertEqual(fixed[:3], (3.0, 7, "target"))
        self.assertGreater(trail[0], 3.0)
        self.assertEqual(trail[2], "trail")

    def test_trail_gives_back_on_chop(self):
        spec = [(100, 111, 99, 110), (110, 111, 95, 96), (96, 97, 80, 82)]     # +1R armed then falls
        by = bars(spec)
        r_trail = run_exit(by, 4, 100.0, 90.0, rr=None, hold=12, trail=3, arm=1.0)
        self.assertLessEqual(r_trail[0], 0.0)

    def test_compare_report(self):
        st, state, tr, d, prov, clk = rig()
        self.assertIn("no trades", compare(st))
        sid, _ = st.add_signal("2026-11-17", "X", 4, "CE", "missed", "late_login", entry=100.0, stop=90.0, target=130.0,
                               rules_version="v", gap=0, dist=0)
        tid, _ = st.add_trade(sid, "late-sim", 0, "09:40", 100.0); st.close_trade(tid, "10:00", 130.0, "target", 3.0)
        for slot, b in bars([(100, 112, 99, 111), (111, 135, 110, 130)]).items():
            st.put_bar("2026-11-17", "X", slot, b["O"], b["H"], b["L"], b["C"], 0, "backfill")
        txt = compare(st)
        self.assertIn("1 trade(s)", txt); self.assertIn("v3 now", txt); self.assertIn("do NOT pick a winner", txt)

    def test_compare_command(self):
        from trader.control import Controller
        st, state, tr, d, prov, clk = rig()
        c = Controller(st, state, "1", None, hooks={}, clock=lambda: at(9, 20))
        self.assertIn("Exit comparison", c.cmd_compare([], at(9, 20)))


class Vix(unittest.TestCase):
    def test_vix_bars_data_only(self):
        st, state, tr, d, prov, clk = rig()
        prov.vix = lambda: 14.25
        clk.t = at(9, 3)
        d.login.handle({"status": "success", "request_token": "t", "state": __import__("tests.test_login", fromlist=["x"]).state_of(d.login.link())})
        step(d, clk, at(9, 4))
        step(d, clk, at(9, 16)); step(d, clk, at(9, 17)); step(d, clk, at(9, 21))
        vb = st.get_bars("2026-11-17", "INDIA VIX", "vix")
        self.assertEqual([b["slot"] for b in vb], [0, 1])             # one bar per 5-min slot
        self.assertEqual(vb[0]["c"], 14.25)

    def test_vix_failure_not_fatal(self):
        st, state, tr, d, prov, clk = rig()
        def boom(): raise RuntimeError("no")
        prov.vix = boom
        clk.t = at(9, 3)
        from tests.test_login import state_of
        d.login.handle({"status": "success", "request_token": "t", "state": state_of(d.login.link())})
        step(d, clk, at(9, 4)); step(d, clk, at(9, 16)); step(d, clk, at(9, 21))
        self.assertIsNotNone(d.engine)


if __name__ == "__main__":
    unittest.main()
