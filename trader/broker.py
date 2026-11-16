"""Broker interface + PaperBroker. The engine only ever talks to this interface.
A KiteBroker (real orders) comes in a later phase and must implement the same two calls.
Python 3.6 compatible."""
from collections import namedtuple

Fill = namedtuple("Fill", "order_id symbol side qty price ts ref_price")


class Broker(object):
    def buy(self, symbol, qty, ref_price, ts):
        raise NotImplementedError

    def sell(self, symbol, qty, ref_price, ts):
        raise NotImplementedError


class PaperBroker(Broker):
    """Fills instantly at the reference price (+/- optional slippage in points).
    Entry reference = open of the bar after the signal (first trade of that bar);
    both the reference and the fill price are kept so the rule can be revisited (design Q4)."""

    def __init__(self, slip=0.0):
        self.slip = float(slip)
        self.fills = []
        self._n = 0

    def _fill(self, symbol, side, qty, ref_price, ts, px):
        self._n += 1
        f = Fill("P%06d" % self._n, symbol, side, qty, px, ts, ref_price)
        self.fills.append(f)
        return f

    def buy(self, symbol, qty, ref_price, ts):
        return self._fill(symbol, "BUY", qty, ref_price, ts, ref_price + self.slip)

    def sell(self, symbol, qty, ref_price, ts):
        return self._fill(symbol, "SELL", qty, ref_price, ts, ref_price - self.slip)
