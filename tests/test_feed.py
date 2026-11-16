import sys, os, unittest, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trader.feed import Tick, TradeFilter
D = datetime.datetime
def t(m, s=0): return D(2026, 11, 16, 9, m, s)

class T(unittest.TestCase):
    def test_option_only_new_trades(self):
        f = TradeFilter()
        self.assertFalse(f.accept(Tick("O", t(15), 100, 0)))      # first packet primes
        self.assertTrue(f.accept(Tick("O", t(16), 101, 50)))      # volume up -> trade
        self.assertFalse(f.accept(Tick("O", t(17), 101, 50)))     # depth-only update: same volume
        self.assertTrue(f.accept(Tick("O", t(18), 99, 60)))
        self.assertFalse(f.accept(Tick("O", t(19), 99, 10)))      # counter reset -> ignored

    def test_midday_start_primes_without_using_stale_snapshot(self):
        f = TradeFilter()
        self.assertFalse(f.accept(Tick("O", t(40), 120, 5000)))   # connected mid-day: stale snapshot ignored
        self.assertTrue(f.accept(Tick("O", t(41), 121, 5010)))

    def test_index_uses_exchange_timestamp(self):
        f = TradeFilter()
        self.assertTrue(f.accept(Tick("I", t(15, 1), 25000, None)))
        self.assertFalse(f.accept(Tick("I", t(15, 1), 25000, None)))   # duplicate timestamp
        self.assertTrue(f.accept(Tick("I", t(15, 2), 25001, None)))

if __name__ == "__main__":
    unittest.main()
