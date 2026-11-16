import sys, os, unittest, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trader import candles as c

D = datetime.datetime
def t(h, m, s=0): return D(2026, 11, 16, h, m, s)

class T(unittest.TestCase):
    def test_slots(self):
        self.assertEqual(c.slot_of(t(9, 15)), 0); self.assertEqual(c.slot_of(t(9, 19, 59)), 0)
        self.assertEqual(c.slot_of(t(9, 20)), 1); self.assertEqual(c.slot_of(t(15, 25)), 74)
        self.assertIsNone(c.slot_of(t(9, 14, 59))); self.assertIsNone(c.slot_of(t(15, 30)))

    def test_ohlc_and_close_on_next_slot(self):
        b = c.BarBuilder("X")
        self.assertEqual(b.on_tick(t(9, 15, 1), 100), [])
        b.on_tick(t(9, 16), 105); b.on_tick(t(9, 17), 98); b.on_tick(t(9, 19, 59), 102)
        out = b.on_tick(t(9, 20, 0), 103)
        self.assertEqual(len(out), 1)
        o = out[0]
        self.assertEqual((o["slot"], o["O"], o["H"], o["L"], o["C"], o["n"], o["src"]), (0, 100, 105, 98, 102, 4, "live"))

    def test_gap_gets_flat_bars(self):
        b = c.BarBuilder("X")
        b.on_tick(t(9, 15), 100); out = b.on_tick(t(9, 30), 110)   # slots 1,2 empty
        self.assertEqual([x["slot"] for x in out], [0, 1, 2])
        self.assertEqual([x["src"] for x in out], ["live", "flat", "flat"])
        self.assertEqual((out[1]["O"], out[1]["C"], out[1]["n"]), (100, 100, 0))

    def test_late_and_outside_ticks(self):
        b = c.BarBuilder("X")
        b.on_tick(t(9, 25), 100); b.on_tick(t(9, 17), 50); b.on_tick(t(8, 59), 1); b.on_tick(t(15, 31), 1)
        self.assertEqual((b.late, b.ignored), (1, 2))
        self.assertEqual(b.cur["L"], 100)

    def test_timer_close(self):
        b = c.BarBuilder("X")
        b.on_tick(t(9, 15, 30), 100)
        self.assertEqual(b.close_due(t(9, 20, 1)), [])           # inside grace
        out = b.close_due(t(9, 20, 3))
        self.assertEqual(len(out), 1); self.assertIsNone(b.cur)
        out2 = b.on_tick(t(9, 20, 5), 101)                       # next bar starts clean, no duplicate of slot 0
        self.assertEqual(out2, [])

    def test_new_day_resets(self):
        b = c.BarBuilder("X")
        b.on_tick(t(15, 25), 100)
        out = b.on_tick(D(2026, 11, 17, 9, 15), 200)
        self.assertEqual(out, [])                                 # prior day's open bar is dropped unless flushed
        self.assertEqual(b.cur["slot"], 0)

    def test_timer_then_late_tick_is_not_duplicate(self):
        b = c.BarBuilder("X")
        b.on_tick(t(9, 15), 100); b.close_due(t(9, 20, 3))
        self.assertEqual(b.on_tick(t(9, 19, 59), 77), [])        # late for already-emitted slot 0
        self.assertEqual(b.late, 1); self.assertIsNone(b.cur)

    def test_timer_then_gap_filled(self):
        b = c.BarBuilder("X")
        b.on_tick(t(9, 15), 100); b.close_due(t(9, 20, 3))
        out = b.on_tick(t(9, 30), 110)                           # slots 1,2 never traded
        self.assertEqual([x["slot"] for x in out], [1, 2]); self.assertEqual(out[0]["src"], "flat")

if __name__ == "__main__":
    unittest.main()
