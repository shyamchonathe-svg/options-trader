import os, tempfile, unittest
from trader.store import Store
from trader.state import RuntimeState
from trader.risk import RiskGuard
from trader.pin import PinFile, hash_pin, verify_pin

D = "2025-11-17"


def closed(st, slot, sym, r, reason):
    sid, _ = st.add_signal(D, sym, slot, "CE", "traded")
    tid, _ = st.add_trade(sid, "live", 1, "10:00", 100.0)
    st.close_trade(tid, "10:20", 100.0, reason, r, r)


class RiskTests(unittest.TestCase):
    def test_shadow_ignores_limits(self):
        st = Store(); state = RuntimeState(st); g = RiskGuard(st, state)
        closed(st, 1, "A", -1, "stop"); closed(st, 2, "B", -1, "stop")
        self.assertTrue(g.allow_entry(D, "shadow")[0])
        self.assertFalse(g.allow_entry(D, "live")[0])

    def test_live_max_trades(self):
        st = Store(); state = RuntimeState(st); g = RiskGuard(st, state)
        state.set_risk("halt_after_stops", 5); state.set_risk("daily_loss_R", 5.0)
        closed(st, 1, "A", 3, "target"); closed(st, 2, "B", 3, "target")
        ok, why = g.allow_entry(D, "live")
        self.assertFalse(ok); self.assertIn("max-trades", why)

    def test_stopped_blocks_all(self):
        st = Store(); state = RuntimeState(st); g = RiskGuard(st, state)
        state.set_stopped(True)
        self.assertFalse(g.allow_entry(D, "shadow")[0])


class PinTests(unittest.TestCase):
    def test_hash(self):
        h = hash_pin("123456")
        self.assertTrue(verify_pin("123456", h)); self.assertFalse(verify_pin("123457", h))
        self.assertNotEqual(h, hash_pin("123456"))

    def test_file(self):
        p = os.path.join(tempfile.mkdtemp(), "pin")
        pf = PinFile(p)
        self.assertFalse(pf.is_set())
        with self.assertRaises(ValueError): pf.set("123")
        pf.set("654321")
        self.assertTrue(pf.verify("654321")); self.assertFalse(pf.verify("1"))
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")
        self.assertNotIn("654321", open(p).read())

if __name__ == "__main__":
    unittest.main()
