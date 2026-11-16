"""The daily life-cycle, driven by step(now) once every ~second (single thread; ticks arrive via a queue).

 09:00  morning: provider.morning(day) -> indexes/seeds/back-fill, build Engine+Pipeline, start feed
        (a restart at any time of day does the same, with the missed part back-filled; back-filled signals are recorded
         as 'missed' and never traded)
 09:10  ready check message
 09:15-15:30  bars, signals, entries/exits, feed-stale watch, heartbeat, health rows
 15:31  end of day: close the last bars, force-close any open position
 15:45  summary, reconciliation vs historical bars, DB export to Telegram, live auto-disarm
Every once-a-day step is remembered in the kv table, so a restart never repeats a summary or an export.
"""
import datetime
import os
import queue
import time

from trader import rules_v3 as R
from trader.engine import Engine
from trader.export import make_export
from trader.notify import day_summary
from trader.pipeline import Pipeline
from trader.recon import reconcile
from trader.risk import RiskGuard

T = datetime.time
MORNING, READY, STALE_FROM, EOD, SUMMARY = T(9, 0), T(9, 10), T(9, 20), T(15, 31), T(15, 45)
MARKET_END = T(15, 25)
STALE_S = 90
MORNING_RETRY_S = 30


class Daemon(object):
    def __init__(self, store, state, notifier, provider, broker, cfg=None, sender=None, heartbeat=None):
        self.store, self.state, self.notify, self.provider, self.broker = store, state, notifier, provider, broker
        self.cfg = cfg
        self.sender = sender              # object with send_file(path, caption) (the Notifier)
        self.heartbeat = heartbeat
        self.q = queue.Queue()
        self.engine = None
        self.pipe = None
        self.feed = None
        self.day = None
        self.stale_alerted = False
        self.last_morning_try = None
        self.morning_err = None
        self.last_health = None
        self.restart_requested = False

    # ------------------------------------------------------------ small helpers
    def _k(self, name):
        return "d:%s:%s" % (self.day, name)

    def _once(self, name):
        """True the first time per day (and remembers it across restarts)."""
        if self.store.kv_get(self._k(name)):
            return False
        self.store.kv_set(self._k(name), "1")
        return True

    def _say(self, kind, text):
        self.notify(kind, {"text": text})

    def on_tick(self, tick):
        """Thread-safe: called by the feed thread."""
        self.q.put(tick)

    # ------------------------------------------------------------ hooks for the Telegram controller
    def flat(self):
        if self.engine is None:
            return 0
        slot = max(0, min(74, (self.now_cache.hour * 60 + self.now_cache.minute - 555) // 5))
        return self.engine.flat(self.pipe.last_price, slot)

    def request_restart(self):
        self.restart_requested = True

    def export_now(self, args=None):
        path = make_export(self.store, self.cfg.exports, self.day or "manual")
        if self.sender is not None:
            self.sender.send_file(path, "db export")
            return "Export sent (%d KB)." % (os.path.getsize(path) // 1024)
        return "Saved %s" % path

    now_cache = datetime.datetime(2000, 1, 1)

    # ------------------------------------------------------------ main step
    def step(self, now):
        self.now_cache = now
        for m in self.state.tick(now):
            self._say("info", "state: " + m)
        day = now.strftime("%Y-%m-%d")
        if day != self.day:
            self._new_day(day)
        if self.heartbeat:
            self.heartbeat()
        if now.weekday() >= 5:
            return
        t = now.time()
        if self.state.mode == "live" and self.state.armed and not getattr(self.broker, "live", False):
            self.state.armed = False
            self._say("info", "WARNING: live armed but no live broker is installed; disarmed.")
        if self.engine is not None:
            self.engine.mode = "live" if self.state.live_active() else "paper"
        if MORNING <= t < EOD and self.engine is None:
            self._morning(now)
        if t >= READY and t < EOD and self._once("ready"):
            self._say("ready", self._ready_text())
        self._drain()
        if self.pipe is not None and T(9, 15) <= t < EOD:
            self.pipe.close_due(now)
            self._watch_feed(now)
        self._health(now)
        if t >= EOD and self._once("eod"):
            self._end_of_day()
        if t >= SUMMARY and self._once("summary"):
            self._summary(now)

    def _new_day(self, day):
        if self.feed is not None:
            try:
                self.feed.stop()
            except Exception as e:
                self.store.event("ERROR", "feed", "stop: %r" % e)
        self.day, self.engine, self.pipe, self.feed = day, None, None, None
        self.stale_alerted, self.morning_err, self.last_morning_try = False, None, None
        self.state.feed_ok = None

    # ------------------------------------------------------------ morning
    def _morning(self, now):
        if self.provider is None:
            return
        if self.last_morning_try is not None and (now - self.last_morning_try).total_seconds() < MORNING_RETRY_S:
            return
        self.last_morning_try = now
        try:
            self.state.token_ok = self.provider.token_ok()
            if not self.state.token_ok:
                if self._once("token-alert"):
                    self._say("token_missing", "Kite token missing or expired. Send /token <request_token> (login link: /config).")
                return
            plan = self.provider.morning(self.day)
        except Exception as e:
            self.morning_err = "%s: %s" % (type(e).__name__, str(e)[:150])
            self.store.event("ERROR", "morning", self.morning_err)
            if self._once("morning-alert"):
                self._say("info", "Morning setup failed, retrying every %ds: %s" % (MORNING_RETRY_S, self.morning_err))
            return
        if plan is None:
            self.morning_err = "not a trading day / no session"
            return
        self.morning_err = None
        eng = Engine(self.store, self.broker, self.day, mode="live" if self.state.live_active() else "paper",
                     notify=self.notify, guard=RiskGuard(self.store, self.state))
        syms = []
        for spec, prev_close, seeds in plan["indexes"]:
            eng.add_index(spec, prev_close, seeds)
            syms.append(spec.symbol)
            syms.extend(o.symbol for o in spec.options)
        self.engine = eng
        self.pipe = Pipeline(self.store, eng, syms)
        back = plan.get("backfill") or []
        if back:
            eng.accepting = False
            for sym, slot, o, h, l, c in back:
                eng.on_open(sym, slot, o)
                eng.on_bar(sym, slot, o, h, l, c)
                self.store.put_bar(self.day, sym, slot, o, h, l, c, 0, "backfill")
                bb = self.pipe.bb[sym]
                bb.day, bb.closed_slot, bb.last_close = self.day, max(bb.closed_slot, slot), c
            eng.accepting = True
        self.feed = plan.get("feed")
        if self.feed is not None:
            self.feed.set_handler(self.on_tick)
            self.feed.subscribe(syms)
            self.feed.start()
        self.store.event("INFO", "morning", "ready: %d symbols, backfill %d bars" % (len(syms), len(back)))

    def _ready_text(self):
        if self.provider is None:
            return "Ready check %s: no market-data provider configured yet (control plane only). mode=%s" % (self.day, self.state.mode)
        if self.engine is None:
            return "NOT READY %s: %s" % (self.day, self.morning_err or ("token missing" if self.state.token_ok is False else "morning setup pending"))
        names = ", ".join(sorted(self.pipe.bb))
        return "READY %s mode=%s feed=%s\nwatching: %s" % (self.day, self.state.mode, "on" if self.feed else "off", names)

    # ------------------------------------------------------------ run-time
    def _drain(self):
        n = 0
        while n < 5000:
            try:
                tk = self.q.get_nowait()
            except queue.Empty:
                return
            n += 1
            if self.pipe is not None:
                try:
                    self.pipe.on_tick(tk)
                except Exception as e:
                    self.store.event("ERROR", "tick", "%s: %r" % (tk.symbol, e))

    def _watch_feed(self, now):
        t = now.time()
        if not (STALE_FROM <= t < MARKET_END) or self.feed is None:
            return
        last = self.pipe.last_tick_ts or datetime.datetime(now.year, now.month, now.day, 9, 15)
        age = (now - last).total_seconds()
        self.state.last_tick_ts = last
        if age > STALE_S and not self.stale_alerted:
            self.stale_alerted, self.state.feed_ok = True, False
            self._say("feed_stale", "FEED STALE: no new trade for %d s (last %s)." % (age, last.strftime("%H:%M:%S")))
        elif age <= STALE_S and self.stale_alerted:
            self.stale_alerted, self.state.feed_ok = False, True
            self._say("info", "Feed recovered.")
        elif age <= STALE_S:
            self.state.feed_ok = True

    def _health(self, now):
        if self.pipe is None:
            return
        if self.last_health is not None and (now - self.last_health).total_seconds() < 60:
            return
        self.last_health = now
        lt = self.pipe.last_tick_ts
        self.store.db.execute("INSERT INTO health VALUES(?,?,?,?)", (
            now.strftime("%Y-%m-%d %H:%M:%S"), lt.strftime("%H:%M:%S") if lt else None, self.pipe.bars_built,
            None if lt is None else int((now - lt).total_seconds() * 1000)))
        self.store.db.commit()

    def _end_of_day(self):
        if self.pipe is not None:
            self.pipe.flush()
            self.engine.end_of_day()
        if self.feed is not None:
            try:
                self.feed.stop()
            except Exception as e:
                self.store.event("ERROR", "feed", "stop: %r" % e)

    def _summary(self, now):
        text = day_summary(self.store, self.day)
        if self.provider is None:
            text += "\n(no market-data provider configured)"
        self._say("summary", text)
        if self.pipe is not None and self.provider is not None:
            try:
                hist = self.provider.history(self.day, sorted(self.pipe.bb))
                n, bad, mx = reconcile(self.store, self.day, hist)
                self._say("info", "Reconciliation: %d bars compared, %d differ (max diff %.2f)." % (n, bad, mx)
                          + ("  CHECK the tick path." if bad else ""))
            except Exception as e:
                self.store.event("ERROR", "recon", "%r" % e)
                self._say("info", "Reconciliation failed: %s" % type(e).__name__)
        if self.cfg is not None:
            try:
                self.export_now()
            except Exception as e:
                self.store.event("ERROR", "export", "%r" % e)
