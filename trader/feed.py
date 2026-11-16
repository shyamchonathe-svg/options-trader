"""Feed contract shared by ReplayFeed (lab) and KiteFeed (VM). No Kite imports here.

Kite facts this encodes (kite.trade/docs/connect/v3/websocket):
  * Exchange timestamps exist only in FULL mode (ltp/quote packets carry no time) -> subscribe in 'full'.
  * In full mode a packet is sent on ANY change (including market-depth changes), with the SAME last price and
    last_trade_time as before. Exchange candles are built from TRADES only, so a depth-only packet must not
    create/open a bar. We therefore accept an option tick only when day-volume increased, and time-stamp it with
    last_trade_time (not exchange_timestamp).
  * Index packets (NIFTY 50, SENSEX) have no volume/last_trade_time: every packet with a new exchange_timestamp counts.
"""
from collections import namedtuple

# symbol: exchange:tradingsymbol key (e.g. "BFO:SENSEX2591180300CE"); ts: naive IST datetime;
# volume: cumulative day volume for options, None for indices.
Tick = namedtuple("Tick", "symbol ts price volume")


class TradeFilter(object):
    """Keeps only ticks that represent a NEW trade (see module doc). The first packet seen for a symbol only primes
    the volume (it may be a stale snapshot); missing bars are repaired from the historical API."""
    def __init__(self):
        self.last_vol = {}
        self.last_idx_ts = {}

    def accept(self, tick):
        if tick.volume is None:                       # index: new exchange timestamp = new value
            prev = self.last_idx_ts.get(tick.symbol)
            self.last_idx_ts[tick.symbol] = tick.ts
            return prev is None or tick.ts > prev
        prev = self.last_vol.get(tick.symbol)
        self.last_vol[tick.symbol] = tick.volume
        if prev is None:
            return False                              # prime only
        if tick.volume < prev:                        # new session / counter reset
            return False
        return tick.volume > prev


class Feed(object):
    """Interface. Implementations call on_tick(Tick) for every packet; runner applies TradeFilter."""
    def subscribe(self, symbols): raise NotImplementedError
    def set_handler(self, on_tick): raise NotImplementedError
    def start(self): raise NotImplementedError
    def stop(self): raise NotImplementedError
