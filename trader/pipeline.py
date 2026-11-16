"""Ticks -> TradeFilter -> BarBuilder -> store + Engine. Single-threaded: callers hand ticks in one at a time."""
from trader.candles import BarBuilder
from trader.feed import TradeFilter


class Pipeline(object):
    def __init__(self, store, engine, symbols):
        self.store = store
        self.engine = engine
        self.tf = TradeFilter()
        self.bb = dict((s, BarBuilder(s)) for s in symbols)
        self.last_price = {}
        self.last_tick_ts = None      # exchange time of the newest accepted tick
        self.bars_built = 0

    def _bars(self, sym, bars):
        for c in bars:
            self.store.put_bar(c["day"], sym, c["slot"], c["O"], c["H"], c["L"], c["C"], c["n"], c.get("src", "live"))
            self.engine.on_bar(sym, c["slot"], c["O"], c["H"], c["L"], c["C"])
            self.bars_built += 1

    def on_tick(self, tick):
        b = self.bb.get(tick.symbol)
        if b is None or not self.tf.accept(tick):
            return
        before = None if b.cur is None else b.cur["slot"]
        closed = b.on_tick(tick.ts, tick.price)
        self.last_price[tick.symbol] = tick.price
        self.last_tick_ts = tick.ts
        if b.cur is not None and b.cur["slot"] != before:
            self.engine.on_open(tick.symbol, b.cur["slot"], tick.price)
        self._bars(tick.symbol, closed)

    def close_due(self, now):
        for sym, b in self.bb.items():
            self._bars(sym, b.close_due(now))

    def flush(self):
        for sym, b in self.bb.items():
            self._bars(sym, b.flush())
