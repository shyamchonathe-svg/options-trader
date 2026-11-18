"""Ticks -> TradeFilter -> BarBuilder -> store + Engine. Single-threaded: callers hand ticks in one at a time."""
import collections
import datetime

from trader.candles import BarBuilder, slot_end
from trader.feed import TradeFilter

FIX_WAIT_S = 60        # how long a closed bar may wait for its exact exchange candle before the live one is used
FIX_SETTLE_S = 3       # never ask for a candle earlier than this after its bar closed (let the exchange finalise it)
FIX_RETRY_S = 4        # candle not published yet: ask again after this many seconds
FIX_CALLS_PER_STEP = 2  # Kite history limit is 3 requests/second; the daemon steps about once a second
NEAR_STEPS = 2.5       # only strikes this close to the index can ever be traded (rule: within 1.5 steps)


class Pipeline(object):
    def __init__(self, store, engine, symbols, fixer=None, near=None):
        """fixer(symbol, slot) -> (o,h,l,c) of the exchange's own candle or None. The live bar is built from sampled
        ticks, so its OPEN (and so the stop and the hammer shape) can differ from the exchange candle; for the symbols
        that can actually be traded the exact candle replaces it before the rules see it. Any failure falls back to
        the live bar after FIX_WAIT_S, so this can only delay a decision by about a minute, never lose one.
        near: {option symbol: (index symbol, strike, step)}"""
        self.store = store
        self.engine = engine
        self.tf = TradeFilter()
        self.bb = dict((s, BarBuilder(s)) for s in symbols)
        self.last_price = {}
        self.last_tick_ts = None      # exchange time of the newest accepted tick
        self.bars_built = 0
        self.fixer = fixer
        self.near = near or {}
        self.index_syms = set(v[0] for v in self.near.values())
        self.hold = collections.deque()      # items: dict(sym, bar, fix, deadline, next_try)
        self.held = {}                       # symbol -> number of bars waiting
        self.stats = {"fixed": 0, "same": 0, "fallback": 0, "unavailable": 0}

    def _deliver(self, sym, c, exact=None):
        self.store.put_bar(c["day"], sym, c["slot"], c["O"], c["H"], c["L"], c["C"], c["n"], c.get("src", "live"))
        o, h, l, cl = (c["O"], c["H"], c["L"], c["C"]) if exact is None else exact
        if exact is not None:
            self.store.put_bar(c["day"], sym, c["slot"], o, h, l, cl, c["n"], "exact")
        self.engine.on_bar(sym, c["slot"], o, h, l, cl)
        self.bars_built += 1

    def _want_fix(self, sym, c):
        if self.fixer is None or c.get("src", "live") != "live" or c.get("n", 0) <= 0:
            return False
        if sym in self.index_syms:
            return True
        info = self.near.get(sym)
        if info is None:
            return False
        px = self.last_price.get(info[0])
        return px is None or abs(px - info[1]) / float(info[2]) <= NEAR_STEPS

    def _bars(self, sym, bars):
        for c in bars:
            fix = self._want_fix(sym, c)
            if fix or self.held.get(sym):
                self.hold.append({"sym": sym, "bar": c, "fix": fix, "deadline": None, "next_try": None})
                self.held[sym] = self.held.get(sym, 0) + 1
            else:
                self._deliver(sym, c)

    def service(self, now, max_calls=FIX_CALLS_PER_STEP):
        """Called about once a second: fetch exact candles for the held bars (rate limited), deliver in order."""
        calls = 0
        n = len(self.hold)
        while n > 0 and self.hold:
            n -= 1
            it = self.hold.popleft()
            sym, c = it["sym"], it["bar"]
            done, exact = False, None
            if not it["fix"]:
                done = not any(h["sym"] == sym and h["fix"] for h in self.hold)
            else:
                if it["deadline"] is None:
                    it["deadline"] = now + datetime.timedelta(seconds=FIX_WAIT_S)
                    end = slot_end(datetime.datetime.strptime(c["day"], "%Y-%m-%d"), c["slot"])
                    it["next_try"] = end + datetime.timedelta(seconds=FIX_SETTLE_S)
                if it["next_try"] is None or now >= it["next_try"]:
                    if calls >= max_calls:
                        self.hold.append(it)
                        continue
                    calls += 1
                    try:
                        exact = self.fixer(sym, c["slot"])
                    except Exception:
                        exact = None
                        self.stats["unavailable"] += 1
                    if exact is not None:
                        done = True
                        same = all(abs(a - b) < 1e-6 for a, b in zip(exact, (c["O"], c["H"], c["L"], c["C"])))
                        self.stats["same" if same else "fixed"] += 1
                    else:
                        it["next_try"] = now + datetime.timedelta(seconds=FIX_RETRY_S)
                if not done and now >= it["deadline"]:
                    done = True
                    self.stats["fallback"] += 1
            if done:
                self.held[sym] -= 1
                self._deliver(sym, c, exact)
            else:
                self.hold.append(it)

    def fix_stats(self):
        st = self.stats
        return "%d corrected, %d already exact, %d fell back to the live bar" % (st["fixed"], st["same"], st["fallback"])

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
        self.drain_holds()

    def drain_holds(self):
        """End of day / shutdown: deliver everything still waiting using the live bars."""
        while self.hold:
            it = self.hold.popleft()
            self.held[it["sym"]] -= 1
            self.stats["fallback"] += it["fix"]
            self._deliver(it["sym"], it["bar"])
