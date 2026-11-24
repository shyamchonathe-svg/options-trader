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
from trader import setups as S

OptionSpec = namedtuple("OptionSpec", "symbol strike side qty")
IndexSpec = namedtuple("IndexSpec", "name symbol step options")

LAST_SLOT = 74
EVAL_FIRST, EVAL_LAST = 3, 67
NEAR_STRIKES = 4          # only options within this many strikes of the index are watched/evaluated


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
        self.triggers = []          # v5 inside setups waiting for a price above the trigger in the next slot


class Engine(object):
    def __init__(self, store, broker, day, mode="paper", rr=3.0, midday_filter=True, max_hold=12,
                 notify=None, rules_version=RULES_VERSION, guard=None, capital=None, use_pct=0.9, vix_regime=True, fixed_qty=None,
                 strategy="v3"):
        self.store = store
        self.broker = broker
        self.day = day
        self.strategy = strategy        # 'v3' = old hammer rule only (tests / parity); 'v5' = pullback + reversal + inside
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
        self._tick_triggers(ix, symbol, slot, px)
        self._progress(ix)

    def on_price(self, symbol, slot, px):
        """Every accepted tick (live only; bar replay reaches the same decision through on_bar)."""
        ix = self._of.get(symbol)
        if ix is None or not ix.triggers:
            return
        self._tick_triggers(ix, symbol, slot, px)

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
        self._bar_triggers(ix)
        while True:
            lo = min(s.next for s in self._watched(ix, ix.eval_next))
            if ix.eval_next >= lo:
                break
            self._evaluate(ix, ix.eval_next)
            ix.eval_next += 1
            self._try_resolve(ix)
            self._bar_triggers(ix)

    def _watched(self, ix, i):
        """Series that must have reached slot i before it is evaluated: the index plus options within NEAR_STRIKES of the
        index close at slot i. Far strikes barely trade; waiting for them stalled every decision (23 Nov)."""
        six = ix.series[ix.spec.symbol]
        if i not in six.by:
            return list(ix.series.values())
        c = six.by[i]["C"]
        out = [six]
        for opt in ix.spec.options:
            if abs(c - opt.strike) <= NEAR_STRIKES * ix.spec.step:
                out.append(ix.series[opt.symbol])
        return out

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
        if i < (1 if self.strategy == "v5" else EVAL_FIRST) or i > EVAL_LAST:
            return                                # v5: the morning reversal can fire from the 09:20 candle
        if self.regime is None:
            self._decide_regime()
        if self.strategy == "v5" and i == 3 and not self.vix_block and self.vix_regime:
            bars = self.store.get_bars(self.day, "INDIA VIX", "vix")       # the 09:30 VIX is only known from here on
            if bars and bars[0]["slot"] <= 1:
                late = [b for b in bars if 2 <= b["slot"] <= 3]
                if V4.vix_fell(bars[0]["c"], late[-1]["c"] if late else None):
                    self.vix_block = "vix-fell-5pct"
        six = ix.series[ix.spec.symbol]
        if i not in six.by:
            return
        dirn = R.index_direction(six.by[i]["C"], six.e10[i], six.e20[i])
        if self.strategy == "v5":
            self._evaluate_v5(ix, i, six, dirn)
            return
        for opt in sorted(ix.spec.options, key=lambda o: o.symbol):
            if abs(six.by[i]["C"] - opt.strike) > NEAR_STRIKES * ix.spec.step:
                continue
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
            setup = p.get("setup")
            if st == "drop":
                self._record(ix, i, opt, "dropped", "no-entry-bar", setup=setup)
                continue
            s = ix.series[opt.symbol]
            view = dict((k, v) for k, v in s.by.items() if k <= i)
            view[i + 1] = {"O": entry, "H": entry, "L": entry, "C": entry}
            sig = self._signal(setup, i, view, s, p["dirn"], opt.side)
            if sig is None or sig.get("entry") is None:
                self._record(ix, i, opt, "dropped", "R<=0", setup=setup)
                continue
            ix.busy[opt.symbol] = i + 1
            self._admit(ix, i, opt, sig, ip, setup)

    def _signal(self, setup, i, view, s, dirn, side):
        """The pure rule behind a pending signal (called twice: when it is found, and when the entry open is known)."""
        if self.strategy != "v5" or setup in (None, "pullback"):
            fn = S.pullback_signal if self.strategy == "v5" else R.signal_at
            return fn(i, view, s.e10, s.e20, dirn, side, self.rr)
        return S.reversal_signal(i, view, s.e10, s.e20, S.REVERSALS[setup], self.rr)

    def _admit(self, ix, i, opt, sig, ip, setup):
        """Gap / strike distance / one-position / risk-guard checks, then the entry. ip = index price at the entry."""
        rev = bool(setup and setup.startswith("reversal"))
        dist = abs(ip - opt.strike) / float(ix.spec.step)
        why = []
        if not rev and ix.gside and opt.side != ix.gside and not (
                self.rules_version == V4.RULES_VERSION
                and V4.gap_lifted(ix.gside, ix.prev_close, ix.series[ix.spec.symbol].by, i)):
            why.append("gap-dir")                      # a reversal trades against the gap on purpose
        limit = S.REVERSAL_MAX_STEPS if rev else (V4.ATM_MAX_STEPS if self.rules_version == V4.RULES_VERSION else R.MAX_DIST_STEPS)
        if dist > limit:
            why.append("not-ATM")
        if not why and ix.ntrades >= self.max_trades:
            why.append("already-traded-today")
        if not why and ix.pos is not None:
            why.append("position-open")
        if not why and self.guard is not None:
            ok, reason = self.guard.allow_entry(self.day, self.mode)
            if not ok:
                why.append("risk:" + reason)
        entry = sig["entry"]
        qty = self._qty(ix, opt, entry)
        if not why and qty <= 0:
            why.append("capital")
        if why:
            self._record(ix, i, opt, "rejected", ",".join(why), sig, ix.gap, dist, setup=setup)
            return False
        sig["qty"], sig["index_px"] = qty, ip
        ix.ntrades += 1
        self._enter(ix, i, opt, sig, ix.gap, dist)
        return True

    # ---------------------------------------------------------------- v5 evaluation, inside triggers
    def _evaluate_v5(self, ix, i, six, dirn):
        for opt in sorted(ix.spec.options, key=lambda o: o.symbol):
            if abs(six.by[i]["C"] - opt.strike) > NEAR_STRIKES * ix.spec.step:
                continue
            s = ix.series[opt.symbol]
            if i not in s.by or (i - 1) not in s.by:
                continue
            view = dict((k, v) for k, v in s.by.items() if k <= i)
            if i > ix.busy.get(opt.symbol, -1):
                setup, sig = "pullback", S.pullback_signal(i, view, s.e10, s.e20, dirn, opt.side, self.rr)
                if sig is None:
                    for name in ("reversal_am", "reversal_pm"):
                        if S.REVERSAL_ENABLED.get(name):
                            sig = S.reversal_signal(i, view, s.e10, s.e20, S.REVERSALS[name], self.rr)
                            if sig is not None:
                                setup = name
                                break
                if sig is not None:
                    if sig["midday"] and self.midday_filter:
                        self._record(ix, i, opt, "skipped", "midday", setup=setup)
                    elif self.vix_block:
                        self._record(ix, i, opt, "skipped", self.vix_block, setup=setup)
                    else:
                        ix.pending.append({"i": i, "opt": opt, "dirn": dirn, "setup": setup})
            tg = S.inside_setup(i - 1, view, s.e10, s.e20, six.by, six.e10, six.e20, opt.side)
            if tg is not None and i > ix.busy.get(opt.symbol, -1) and not any(
                    t["opt"].symbol == opt.symbol and t["i"] == i for t in ix.triggers):
                ix.triggers.append({"i": i, "opt": opt, "trig": tg["trig"], "stop": tg["stop"], "midday": tg["midday"]})

    def _fire(self, ix, tg, entry):
        """An inside trigger traded: build the signal at the actual entry price and admit it."""
        i, opt = tg["i"], tg["opt"]
        ix.triggers = [t for t in ix.triggers if t is not tg]
        if tg["midday"] and self.midday_filter:
            self._record(ix, i, opt, "skipped", "midday", setup="inside")
            return
        if self.vix_block:
            self._record(ix, i, opt, "skipped", self.vix_block, setup="inside")
            return
        r = entry - tg["stop"]
        if r <= 0:
            self._record(ix, i, opt, "dropped", "R<=0", setup="inside")
            return
        sig = {"i": i, "midday": tg["midday"], "t": R.tstr(i), "setup": "inside", "entry": entry, "stop": tg["stop"], "R": r,
               "target": entry + self.rr * r, "note": "stop=big candle low"}
        ix.busy[opt.symbol] = i + 1
        six = ix.series[ix.spec.symbol]
        ip = ix.open_px.get((ix.spec.symbol, i + 1))
        if ip is None:
            ip = six.by[i + 1]["O"] if (i + 1) in six.by else six.by[i]["C"]
        self._admit(ix, i, opt, sig, ip, "inside")

    def _tick_triggers(self, ix, symbol, slot, px):
        """Live: a price above the trigger inside the slot after the inside candle = entry now (buy-stop at the trigger)."""
        for tg in list(ix.triggers):
            if tg["opt"].symbol != symbol:
                continue
            if slot > tg["i"] + 1:
                ix.triggers = [t for t in ix.triggers if t is not tg]
            elif slot == tg["i"] + 1 and px >= tg["trig"]:
                opn = ix.open_px.get((symbol, slot), px)
                self._fire(ix, tg, max(opn, tg["trig"]))

    def _bar_triggers(self, ix):
        """Replay / recovery: decide from the closed bar of the slot after the inside candle (same price rule as ticks)."""
        if not ix.triggers:
            return
        six = ix.series[ix.spec.symbol]
        for tg in list(ix.triggers):
            slot = tg["i"] + 1
            s = ix.series[tg["opt"].symbol]
            if six.next <= slot:
                continue
            if slot in s.by:
                b = s.by[slot]
                if b["H"] >= tg["trig"]:
                    self._fire(ix, tg, max(b["O"], tg["trig"]))
                else:
                    ix.triggers = [t for t in ix.triggers if t is not tg]
            elif s.next > slot:
                ix.triggers = [t for t in ix.triggers if t is not tg]

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

    def _record(self, ix, i, opt, status, reasons, sig=None, gap=None, dist=None, setup=None):
        sid, created = self.store.add_signal(
            self.day, opt.symbol, i, opt.side, status, reasons,
            entry=sig["entry"] if sig else None, stop=sig["stop"] if sig else None,
            target=sig["target"] if sig else None, rules_version=self.rules_version, gap=gap, dist=dist,
            setup=setup or (sig.get("setup") if sig else None))
        if created:
            self.store.event("INFO", "signal", "%s %s slot %d %s %s" % (opt.symbol, opt.side, i, status, reasons))
            if status == "traded":
                pass            # the user is told about trades only (entry/exit); every signal stays in the database
        return sid

    def _enter(self, ix, i, opt, sig, gap, dist):
        flag = "flag:old-trend" if sig.get("old_flag") else ""      # logged only, never blocks (v5 pullback)
        if not self.accepting:
            old = self.store.signal_id(self.day, opt.symbol, i)
            if old is None or self.store.trade_for_signal(old) is None:
                self._record(ix, i, opt, "missed", self.block_reason, sig, gap, dist)
                return
        sid = self._record(ix, i, opt, "traded", flag, sig, gap, dist)
        tr = self.store.trade_for_signal(sid)
        qty = sig.get("qty", opt.qty)
        if tr is None:
            fill = self.broker.buy(opt.symbol, qty, sig["entry"], R.tstr(i + 1))
            tid, _ = self.store.add_trade(sid, self.mode, qty, R.tstr(i + 1), fill.price)
            self.store.event("INFO", "entry", "%s %s qty %d @ %.2f stop %.2f target %.2f index %s %s" % (
                sig.get("setup") or "pullback", opt.symbol, qty, fill.price, sig["stop"], sig["target"], sig.get("index_px"), flag))
            self._emit("entry", {"symbol": opt.symbol, "t": R.tstr(i + 1), "price": fill.price, "stop": sig["stop"],
                                 "target": sig["target"], "qty": qty, "index": ix.spec.name.title(),
                                 "index_px": sig.get("index_px")})
        else:
            tid = tr["id"]
        rev = sig.get("plan") == "rev"
        limit = min(i + (sig["hold"] if rev else self.max_hold), LAST_SLOT)
        ix.pos = {"symbol": opt.symbol, "i": i, "entry": sig["entry"], "stop": sig["stop"], "target": sig["target"],
                  "R": sig["R"], "qty": qty, "trade_id": tid, "index_px": sig.get("index_px"), "entry_t": R.tstr(i + 1), "limit": limit,
                  "last_close": sig["entry"], "last_slot": i + 1, "plan": "rev" if rev else "std", "book": sig.get("book"),
                  "lot": opt.qty, "booked": False, "part_qty": 0, "part_r": 0.0, "part_pnl": 0.0}
        if tr is not None and tr.get("part_t"):                 # restart mid-trade: the partial booking already happened
            ix.pos.update(booked=True, part_qty=tr["part_qty"], part_r=(tr["part_px"] - sig["entry"]) / sig["R"],
                          part_pnl=(tr["part_px"] - sig["entry"]) * tr["part_qty"])

    def _check_exit(self, ix, symbol, slot, bar):
        p = ix.pos
        if p is None or p["symbol"] != symbol or slot < p["i"] + 1:
            return
        if slot > p["limit"]:        # data jumped past the allowed window: time exit at the last real close
            self._exit(ix, p, p["last_slot"], p["last_close"], "time", (p["last_close"] - p["entry"]) / p["R"])
            return
        rev = p["plan"] == "rev"
        if bar is not None:
            p["last_close"], p["last_slot"] = bar["C"], slot
            if bar["L"] <= p["stop"]:
                if rev and p["booked"]:
                    self._exit(ix, p, slot, p["stop"], "trail", (p["stop"] - p["entry"]) / p["R"])
                else:
                    self._exit(ix, p, slot, p["stop"], "stop", -1.0)
                return
            if not rev and bar["H"] >= p["target"]:
                self._exit(ix, p, slot, p["target"], "target", self.rr)
                return
            if rev:
                if not p["booked"] and slot - p["i"] == p["book"]:
                    self._partial(ix, p, slot, bar["C"])         # book half at the close of the 2nd (AM) / 3rd (PM) candle
                if p["booked"]:
                    p["stop"] = max(p["stop"], bar["L"])        # aggressive trail: low of the candle just closed
        if slot == p["limit"]:
            self._exit(ix, p, p["last_slot"], p["last_close"], "time", (p["last_close"] - p["entry"]) / p["R"])

    def _partial(self, ix, p, slot, px):
        half = (p["qty"] // p["lot"] // 2) * p["lot"] if p["lot"] else 0
        p["booked"] = True
        if half <= 0:                                           # one lot cannot be split: keep it whole, still trail
            return
        if not self.store.book_partial(p["trade_id"], R.tstr(slot), px, half):
            return                                              # already booked in an earlier run
        fill = self.broker.sell(p["symbol"], half, px, R.tstr(slot))
        p["part_qty"], p["part_r"] = half, (fill.price - p["entry"]) / p["R"]
        p["part_pnl"] = (fill.price - p["entry"]) * half
        self.store.event("INFO", "partial", "%s sold %d of %d @ %.2f" % (p["symbol"], half, p["qty"], fill.price))
        self._emit("info", {"text": "BOOKED HALF  %s\nSold %d of %d @ \u20b9%.2f at %s. The rest stays with a trailing stop." % (
            p["symbol"], half, p["qty"], fill.price, R.tstr(slot))})

    def _exit(self, ix, p, slot, px, reason, r_mult):
        ix.pos = None
        if not self.store.trade_is_open(p["trade_id"]):
            return                                   # already closed in an earlier run: idempotent
        pq = p.get("part_qty") or 0
        rest = p["qty"] - pq
        fill = self.broker.sell(p["symbol"], rest, px, R.tstr(slot))
        pnl = (fill.price - p["entry"]) * rest + (p.get("part_pnl") or 0.0)
        if pq:
            r_mult = (pq * p["part_r"] + rest * r_mult) / float(p["qty"])
        self.store.close_trade(p["trade_id"], R.tstr(slot), fill.price, reason, r_mult, pnl)
        self.store.event("INFO", "exit", "%s %s @ %.2f R=%.2f" % (p["symbol"], reason, fill.price, r_mult))
        self._emit("exit", {"symbol": p["symbol"], "t": R.tstr(slot), "price": fill.price, "reason": reason,
                            "r": r_mult, "pnl": pnl, "qty": p["qty"], "entry_px": p["entry"], "entry_t": p.get("entry_t"),
                            "index": ix.spec.name.title(), "entry_index_px": p.get("index_px"),
                            "index_px": (ix.series[ix.spec.symbol].by.get(slot) or {}).get("C")})
