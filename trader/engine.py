"""Bar-driven trading engine for strategy v3.  Python 3.6 compatible.

Inputs (all per symbol, in any interleaving across symbols, slot order within a symbol):
  on_open(symbol, slot, px)             first trade of a bar (entry reference is the OPTION open of the bar after the signal)
  on_bar(symbol, slot, o, h, l, c)      a closed 5-minute bar
  on_missing(symbol, slot)              no bar for the slot (research data holes); EMA carries the previous close
  end_of_day()                          force-closes any open position at the last real close

Decisions use the pure functions in rules_v3 only (signal_at, index_direction, gap_side, ...); this module adds
the sequencing: a signal is evaluated when ALL symbols of the index have processed the slot, the entry is resolved
when the next bar's open is known, then gap / ATM-distance / one-position-per-day are applied in the same order as
rules_v3.select_day_trades, so replay results are identical to the research code.
Exits are checked on closed option bars (stop on wick touch, 3R target on wick touch, time exit after max_hold bars).

Idempotent: signals are keyed (day, symbol, slot) and trades by signal; feeding the same bars again (or restarting
mid-day and re-feeding) never creates a second signal, trade or order.
"""
from collections import namedtuple

from trader import RULES_VERSION
from trader import rules_v3 as R
from trader import rules_v4 as V4

OptionSpec = namedtuple("OptionSpec", "symbol strike side qty")
IndexSpec = namedtuple("IndexSpec", "name symbol step options")

LAST_SLOT = 74
EVAL_FIRST, EVAL_LAST = 3, 67


class Series(object):
    """Bars + EMA10/EMA20 of the close, indexed by slot. Seeded with previous-session closes."""

    def __init__(self, seed=()):
        self.by = {}
        self.e10 = {}
        self.e20 = {}
        self.next = 0
        self._a10 = 2.0 / 11
        self._a20 = 2.0 / 21
        self._v10 = None
        self._v20 = None
        self._last = None
        for c in seed:
            self._upd(c)

    def _upd(self, c):
        if self._v10 is None:
            self._v10 = c
            self._v20 = c
        self._v10 = self._a10 * c + (1 - self._a10) * self._v10
        self._v20 = self._a20 * c + (1 - self._a20) * self._v20
        self._last = c

    def _store(self, slot):
        self.e10[slot] = self._v10
        self.e20[slot] = self._v20
        self.next = slot + 1

    def _fill_missing(self):
        self._upd(self._last if self._last is not None else 0.0)
        self._store(self.next)

    def add(self, slot, bar):
        if slot < self.next:
            return False
        while self.next < slot:
            self._fill_missing()
        self.by[slot] = bar
        self._upd(bar["C"])
        self._store(slot)
        return True

    def missing(self, slot):
        if slot < self.next:
            return False
        while self.next <= slot:
            self._fill_missing()
        return True


class _Index(object):
    def __init__(self, spec, prev_close, seeds):
        self.spec = spec
        self.prev_close = prev_close
        self.series = {}
        seeds = seeds or {}
        self.series[spec.symbol] = Series(seeds.get(spec.symbol, ()))
        for o in spec.options:
            self.series[o.symbol] = Series(seeds.get(o.symbol, ()))
        self.opts = dict((o.symbol, o) for o in spec.options)
        self.open_px = {}
        self.busy = {}
        self.ntrades = 0
        self.pending = []
        self.eval_next = 0
        self.first_open = None
        self.gap = 0.0
        self.gside = None
        self.pos = None


class Engine(object):
    def __init__(self, store, broker, day, mode="paper", rr=3.0, midday_filter=True, max_hold=12,
                 notify=None, rules_version=RULES_VERSION, guard=None, capital=None, use_pct=0.9, vix_regime=True, fixed_qty=None):
        self.store = store
        self.broker = broker
        self.day = day
        self.mode = mode
        self.rr = rr
        self.midday_filter = midday_filter
        self.max_hold = max_hold
        self.notify = notify
        self.rules_version = rules_version
        self.guard = guard
        self.capital = capital          # money per index (None = trade one contract lot, used by replay/tests)
        self.use_pct = use_pct          # share of that money a position may use
        self.fixed_qty = dict((k.upper(), int(v)) for k, v in (fixed_qty or {}).items())   # index name -> constant quantity
        self.vix_regime = vix_regime    # v4: India VIX at the open sets target / hold / trades per day (no VIX bars = v3 settings)
        self.max_trades = 1             # per index per day
        self.regime = None              # decided once per day at the first evaluation
        self.vix_block = None           # reason string when the VIX rules forbid trading today
        self.block_reason = "backfill"   # recorded as the reason when accepting is False ('late_login' on data-only days)
        self.accepting = True   # False while back-filling history after a late start: no NEW orders, signals recorded as 'missed'
        self._ix = {}      # index name -> _Index
        self._of = {}      # symbol -> _Index

    # ---------------------------------------------------------------- setup
    def add_index(self, spec, prev_close, seeds=None):
        ix = _Index(spec, prev_close, seeds)
        self._ix[spec.name] = ix
        for sym in ix.series:
            self._of[sym] = ix
        return ix

    # ---------------------------------------------------------------- inputs
    def on_open(self, symbol, slot, px):
        ix = self._of.get(symbol)
        if ix is None:
            return
        ix.open_px.setdefault((symbol, slot), px)
        self._progress(ix)

    def on_bar(self, symbol, slot, o, h, l, c):
        ix = self._of.get(symbol)
        if ix is None:
            return
        bar = {"O": o, "H": h, "L": l, "C": c}
        s = ix.series[symbol]
        if not s.add(slot, bar):
            return
        if symbol == ix.spec.symbol and ix.first_open is None:
            ix.first_open = o
            ix.gap, ix.gside = R.gap_side(o, ix.prev_close)
        self._check_exit(ix, symbol, slot, bar)
        self._progress(ix)

    def on_missing(self, symbol, slot):
        ix = self._of.get(symbol)
        if ix is None:
            return
        if not ix.series[symbol].missing(slot):
            return
        self._check_exit(ix, symbol, slot, None)
        self._progress(ix)

    def flat(self, prices, slot):
        """Close every open position now (manual /flat or /stop). prices: symbol -> last price."""
        n = 0
        for ix in self._ix.values():
            p = ix.pos
            if p is None:
                continue
            px = prices.get(p["symbol"], p["last_close"])
            self._exit(ix, p, slot, px, "manual", (px - p["entry"]) / p["R"])
            n += 1
        return n

    def end_of_day(self):
        for ix in self._ix.values():
            p = ix.pos
            if p is not None:
                self._exit(ix, p, p["last_slot"], p["last_close"], "time", (p["last_close"] - p["entry"]) / p["R"])

    # ---------------------------------------------------------------- progress
    def _progress(self, ix):
        self._try_resolve(ix)
        while True:
            lo = min(s.next for s in ix.series.values())
            if ix.eval_next >= lo:
                break
            self._evaluate(ix, ix.eval_next)
            ix.eval_next += 1
            self._try_resolve(ix)

    def _decide_regime(self):
        """Once per day, before the first signal is evaluated: India VIX at the 09:15 open -> target / hold / trades (rules_v4).
        Reads the VIX bars the daemon stores, so a restart decides the same way. No usable VIX open = v3 settings."""
        self.regime = dict(V4.V3_DEFAULT)
        vix_open = later = None
        if self.vix_regime:
            bars = self.store.get_bars(self.day, "INDIA VIX", "vix")
            if bars and bars[0]["slot"] <= 1:
                vix_open = bars[0]["c"]
                late = [b for b in bars if 2 <= b["slot"] <= 3]
                later = late[-1]["c"] if late else None
        reg = V4.regime(vix_open)
        fell = V4.vix_fell(vix_open, later)
        self.regime = reg
        self.rr, self.max_hold, self.max_trades = reg["rr"], reg["hold"], reg["max_trades"]
        self.rules_version = reg["version"] if vix_open else self.rules_version
        if not reg["trade"]:
            self.vix_block = "vix-below-12"
        elif fell:
            self.vix_block = "vix-fell-5pct"
        text = V4.describe(reg, vix_open, fell)
        if self.store.kv_get("regime-%s" % self.day) is None:
            self.store.kv_set("regime-%s" % self.day, "%s|%s|%s" % (reg["name"], vix_open, self.vix_block or ""))
            self.store.event("INFO", "regime", text)
            if vix_open:
                self._emit("info", {"text": text})

    def _evaluate(self, ix, i):
        if i < EVAL_FIRST or i > EVAL_LAST:
            return
        if self.regime is None:
            self._decide_regime()
        six = ix.series[ix.spec.symbol]
        if i not in six.by:
            return
        dirn = R.index_direction(six.by[i]["C"], six.e10[i], six.e20[i])
        for opt in sorted(ix.spec.options, key=lambda o: o.symbol):
            s = ix.series[opt.symbol]
            if i <= ix.busy.get(opt.symbol, -1) or i not in s.by or (i - 1) not in s.by:
                continue
            view = dict((k, v) for k, v in s.by.items() if k <= i)
            sig = R.signal_at(i, view, s.e10, s.e20, dirn, opt.side, self.rr)
            if sig is None:
                continue
            if sig["midday"] and self.midday_filter:
                self._record(ix, i, opt, "skipped", "midday")
                continue
            if self.vix_block:
                self._record(ix, i, opt, "skipped", self.vix_block)
                continue
            ix.pending.append({"i": i, "opt": opt, "dirn": dirn})

    # ---------------------------------------------------------------- entry resolution
    def _opt_open(self, ix, opt, i):
        """('wait'|'drop'|'ok', px) for the option open of bar i+1."""
        s = ix.series[opt.symbol]
        px = ix.open_px.get((opt.symbol, i + 1))
        if px is not None:
            return "ok", px
        if (i + 1) in s.by:
            return "ok", s.by[i + 1]["O"]
        if s.next > i + 1:
            return "drop", None
        return "wait", None

    def _index_open(self, ix, i):
        six = ix.series[ix.spec.symbol]
        px = ix.open_px.get((ix.spec.symbol, i + 1))
        if px is not None:
            return px
        if (i + 1) in six.by:
            return six.by[i + 1]["O"]
        if six.next > i + 1:
            return six.by[i]["O"]            # same fallback as the research code
        return None

    def _try_resolve(self, ix):
        if not ix.pending:
            return
        i = ix.pending[0]["i"]
        ip = self._index_open(ix, i)
        if ip is None:
            return
        got = []
        for p in ix.pending:
            st, px = self._opt_open(ix, p["opt"], i)
            if st == "wait":
                return
            got.append((p, st, px))
        ix.pending = []
        for p, st, entry in sorted(got, key=lambda g: g[0]["opt"].symbol):
            opt = p["opt"]
            if st == "drop":
                self._record(ix, i, opt, "dropped", "no-entry-bar")
                continue
            s = ix.series[opt.symbol]
            view = dict((k, v) for k, v in s.by.items() if k <= i)
            view[i + 1] = {"O": entry, "H": entry, "L": entry, "C": entry}
            sig = R.signal_at(i, view, s.e10, s.e20, p["dirn"], opt.side, self.rr)
            if sig is None or sig.get("entry") is None:
                self._record(ix, i, opt, "dropped", "R<=0")
                continue
            ix.busy[opt.symbol] = i + 1
            dist = abs(ip - opt.strike) / float(ix.spec.step)
            why = []
            if ix.gside and opt.side != ix.gside and not (
                    self.rules_version == V4.RULES_VERSION
                    and V4.gap_lifted(ix.gside, ix.prev_close, ix.series[ix.spec.symbol].by, i)):
                why.append("gap-dir")
            if dist > (V4.ATM_MAX_STEPS if self.rules_version == V4.RULES_VERSION else R.MAX_DIST_STEPS):
                why.append("not-ATM")
            if not why and ix.ntrades >= self.max_trades:
                why.append("already-traded-today")
            if not why and ix.pos is not None:
                why.append("position-open")
            if not why and self.guard is not None:
                ok, reason = self.guard.allow_entry(self.day, self.mode)
                if not ok:
                    why.append("risk:" + reason)
            qty = self._qty(ix, opt, entry)
            if not why and qty <= 0:
                why.append("capital")
            if why:
                self._record(ix, i, opt, "rejected", ",".join(why), sig, ix.gap, dist)
                continue
            sig["qty"], sig["index_px"] = qty, ip
            ix.ntrades += 1
            self._enter(ix, i, opt, sig, ix.gap, dist)

    def _qty(self, ix, opt, entry):
        """Quantity. With a fixed quantity for this index (v4): always that many, in whole lots, reduced ONLY when the money
        does not cover it (available = per-index capital x use_pct + today's realised P&L on this index, so a drawdown
        shrinks it); 0 = cannot afford one lot. Without one: whole lots that fit in use_pct of the capital.
        opt.qty is the contract's lot size. capital None keeps the old one-lot behaviour (replay / tests)."""
        if self.capital is None:
            return opt.qty
        if entry <= 0 or opt.qty <= 0:
            return 0
        want = self.fixed_qty.get(ix.spec.name.upper())
        avail = self.capital * self.use_pct
        if want:
            avail += sum(t["pnl"] for t in self.store.trades_for_day(self.day)
                         if t["symbol"] in ix.opts and t["pnl"] is not None)
        lots = int(max(avail, 0) // (entry * opt.qty))
        if want:
            lots = min(lots, int(want // opt.qty))
        return lots * opt.qty

    # ---------------------------------------------------------------- records / orders
    def _emit(self, kind, payload):
        if self.notify is None:
            return
        try:
            self.notify(kind, payload)
        except Exception as e:          # a broken notifier must never stop trading logic
            self.store.event("ERROR", "notify", "%s: %r" % (kind, e))

    def _record(self, ix, i, opt, status, reasons, sig=None, gap=None, dist=None):
        sid, created = self.store.add_signal(
            self.day, opt.symbol, i, opt.side, status, reasons,
            entry=sig["entry"] if sig else None, stop=sig["stop"] if sig else None,
            target=sig["target"] if sig else None, rules_version=self.rules_version, gap=gap, dist=dist)
        if created:
            self.store.event("INFO", "signal", "%s %s slot %d %s %s" % (opt.symbol, opt.side, i, status, reasons))
            if status == "traded":
                pass            # the user is told about trades only (entry/exit); every signal stays in the database
        return sid

    def _enter(self, ix, i, opt, sig, gap, dist):
        if not self.accepting:
            old = self.store.signal_id(self.day, opt.symbol, i)
            if old is None or self.store.trade_for_signal(old) is None:
                self._record(ix, i, opt, "missed", self.block_reason, sig, gap, dist)
                return
        sid = self._record(ix, i, opt, "traded", "", sig, gap, dist)
        tr = self.store.trade_for_signal(sid)
        qty = sig.get("qty", opt.qty)
        if tr is None:
            fill = self.broker.buy(opt.symbol, qty, sig["entry"], R.tstr(i + 1))
            tid, _ = self.store.add_trade(sid, self.mode, qty, R.tstr(i + 1), fill.price)
            self.store.event("INFO", "entry", "%s qty %d @ %.2f stop %.2f target %.2f index %s" % (
                opt.symbol, qty, fill.price, sig["stop"], sig["target"], sig.get("index_px")))
            self._emit("entry", {"symbol": opt.symbol, "t": R.tstr(i + 1), "price": fill.price, "stop": sig["stop"],
                                 "target": sig["target"], "qty": qty, "index": ix.spec.name.title(),
                                 "index_px": sig.get("index_px")})
        else:
            tid = tr["id"]
        ix.pos = {"symbol": opt.symbol, "i": i, "entry": sig["entry"], "stop": sig["stop"], "target": sig["target"],
                  "R": sig["R"], "qty": qty, "trade_id": tid, "index_px": sig.get("index_px"), "entry_t": R.tstr(i + 1), "limit": min(i + self.max_hold, LAST_SLOT),
                  "last_close": sig["entry"], "last_slot": i + 1}

    def _check_exit(self, ix, symbol, slot, bar):
        p = ix.pos
        if p is None or p["symbol"] != symbol or slot < p["i"] + 1:
            return
        if slot > p["limit"]:        # data jumped past the allowed window: time exit at the last real close
            self._exit(ix, p, p["last_slot"], p["last_close"], "time", (p["last_close"] - p["entry"]) / p["R"])
            return
        if bar is not None:
            p["last_close"], p["last_slot"] = bar["C"], slot
            if bar["L"] <= p["stop"]:
                self._exit(ix, p, slot, p["stop"], "stop", -1.0)
                return
            if bar["H"] >= p["target"]:
                self._exit(ix, p, slot, p["target"], "target", self.rr)
                return
        if slot == p["limit"]:
            self._exit(ix, p, p["last_slot"], p["last_close"], "time", (p["last_close"] - p["entry"]) / p["R"])

    def _exit(self, ix, p, slot, px, reason, r_mult):
        ix.pos = None
        if not self.store.trade_is_open(p["trade_id"]):
            return                                   # already closed in an earlier run: idempotent
        fill = self.broker.sell(p["symbol"], p["qty"], px, R.tstr(slot))
        pnl = (fill.price - p["entry"]) * p["qty"]
        self.store.close_trade(p["trade_id"], R.tstr(slot), fill.price, reason, r_mult, pnl)
        self.store.event("INFO", "exit", "%s %s @ %.2f R=%.2f" % (p["symbol"], reason, fill.price, r_mult))
        self._emit("exit", {"symbol": p["symbol"], "t": R.tstr(slot), "price": fill.price, "reason": reason,
                            "r": r_mult, "pnl": pnl, "qty": p["qty"], "entry_px": p["entry"], "entry_t": p.get("entry_t"),
                            "index": ix.spec.name.title(), "entry_index_px": p.get("index_px"),
                            "index_px": (ix.series[ix.spec.symbol].by.get(slot) or {}).get("C")})
