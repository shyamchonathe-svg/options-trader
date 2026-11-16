import unittest
from trader.broker import PaperBroker


class Paper(unittest.TestCase):
    def test_fills_at_reference_and_keeps_both(self):
        b = PaperBroker()
        f = b.buy("X", 75, 100.0, "09:35")
        self.assertEqual((f.price, f.ref_price, f.side, f.qty), (100.0, 100.0, "BUY", 75))
        g = b.sell("X", 75, 110.0, "09:50")
        self.assertEqual((g.price, g.side), (110.0, "SELL"))
        self.assertNotEqual(f.order_id, g.order_id)
        self.assertEqual(len(b.fills), 2)

    def test_slippage_hurts_both_sides(self):
        b = PaperBroker(slip=0.5)
        self.assertEqual(b.buy("X", 1, 100.0, "t").price, 100.5)
        self.assertEqual(b.sell("X", 1, 110.0, "t").price, 109.5)


if __name__ == "__main__":
    unittest.main()
