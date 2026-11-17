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
from trader import reminders
from trader.recon import reconcile
from trader.risk import RiskGuard

T = datetime.time
MORNING, READY, STALE_FROM, EOD, SUMMARY = T(9, 0), T(9, 10), T(9, 20), T(15, 31), T(16, 0)
MARKET_END = T(15, 25)
REMIND = T(15, 50)
CAPTURE_TEXT = ("Daily capture (send today):\n1) Bhavcopies: NSE F&O zip, BSE F&O csv, ind_close csv -> data/raw/<date>/\n"
                "2) 5m charts, clean + EMA10/20: Nifty, Sensex, India VIX, ATM and +/-1 strike CE and PE of both indices\n"
                "3) Daily charts (Nifty, Sensex) only when asked. Tradebook only on real-money days.")
LOGIN_PROMPTS = (T(8, 30), T(8, 40), T(8, 50), T(9, 5), T(9, 12))
DEFAULT_CUTOFF = "09:15"
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
        self.login = None                 # LoginManager (set by main.build when a Kite provider exists)
        self.recover_requested = False
        self.last_recover_try = None
        self.mute = False                 # True while replaying history: no per-signal Telegram lines

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

    # ---- login / day-skipping hooks
    def login_link(self):
        if self.login is None:
            return None
        return "Tap, log in at Zerodha (2FA), done:\n%s\n(valid once, 15 minutes)" % self.login.link()

    def holidays_path(self):
        return os.path.join(self.cfg.state, "holidays.txt") if self.cfg else None

    def is_holiday(self, day):
        from trader.holidays import NSE_HOLIDAYS
        if day in NSE_HOLIDAYS:
            return True
        p = self.holidays_path()
        if p and os.path.exists(p):
            with open(p) as f:
                return day in set(l.split("#")[0].strip() for l in f)
        return False

    def skip_today(self):
        return bool(self.store.kv_get("skip:%s" % self.day)) or self.is_holiday(self.day)

    def set_skip(self, on):
        self.store.kv_set("skip:%s" % self.day, "1" if on else "")
        return "Today (%s) will be %s." % (self.day, "SKIPPED: no prompts, no trading, no data run" if on else "a normal trading day again")

    def add_holiday(self, day):
        p = self.holidays_path()
        with open(p, "a") as f:
            f.write(day + "\n")
        return "Holiday %s added." % day

    def request_recover(self):
        if self.store.kv_get(self._k("recovered")) or self.engine is not None or self.store.kv_get(self._k("engine_ran")):
            n = self._simulate_missed()
            return "Day already recovered/running. Simulated %d would-have trade(s). Today's summary shows them (late-sim)." % n
        self.recover_requested = True
        return "Recovery requested: the day's bars will be pulled from history within 30 s (needs a login today)."

    def cutoff(self):
        raw = (self.cfg.env.get("LOGIN_CUTOFF") if self.cfg else None) or DEFAULT_CUTOFF
        try:
            h, m = raw.split(":")
            return T(int(h), int(m), 59)
        except ValueError:
            return T(9, 15, 59)

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
        if self.login is not None:
            self.login.pump()
        if now.time() >= T(10, 0):
            extra = os.path.join(self.cfg.state, "reminders.txt") if self.cfg else None
            for i, text in enumerate(reminders.due(self.day, extra)):
                if self._once("reminder-%d" % i):
                    self._say("info", "REMINDER: " + text)
        if now.weekday() >= 5:
            return
        t = now.time()
        if self.skip_today():
            self.state.trading_blocked = "day skipped"
            return
        self._login_flow(now, t)
        if self.state.mode == "live" and self.state.armed and not getattr(self.broker, "live", False):
            self.state.armed = False
            self._say("info", "WARNING: live armed but no live broker is installed; disarmed.")
        if self.engine is not None:
            self.engine.mode = "live" if self.state.live_active() else "paper"
        if MORNING <= t < EOD and self.engine is None:
            self._morning(now)
        if (t >= EOD or self.recover_requested) and self.engine is None:
            self._recover(now)
        if t >= READY and t < EOD and self._once("ready"):
            self._say("ready", self._ready_text())
        self._drain()
        if self.pipe is not None and T(9, 15) <= t < EOD:
            self.pipe.close_due(now)
            self._watch_feed(now)
        self._health(now)
        self._vix(now, t)
        if t >= EOD and self._once("eod"):
            self._end_of_day()
        if t >= SUMMARY and self._once("summary"):
            self._summary(now)
        if t >= REMIND and self._once("capture-reminder"):
            self._say("info", CAPTURE_TEXT)
        if t >= REMIND and self.store.kv_get(self._k("summary")) and self.feed is not None and getattr(self.feed, "needs_restart", False):
            self.request_restart()      # Twisted reactor cannot restart: fresh process for the next session

    def _new_day(self, day):
        if self.feed is not None:
            try:
                self.feed.stop()
            except Exception as e:
                self.store.event("ERROR", "feed", "stop: %r" % e)
        self.day, self.engine, self.pipe, self.feed = day, None, None, None
        self.stale_alerted, self.morning_err, self.last_morning_try = False, None, None
        self.state.feed_ok = None
        self.state.trading_blocked = None
        self.recover_requested, self.last_recover_try = False, None

    # ------------------------------------------------------------ login flow
    def _login_flow(self, now, t):
        """Prompts, and the one rule: no login by the cutoff => today is DATA_ONLY (never trades). Data still flows."""
        if self.login is None:
            return
        la = self.login.login_at() if self.login.logged_in_today() else None
        cut = self.cutoff()
        if la is not None:
            h, m, sec = [int(x) for x in la.split(":")]
            self.state.trading_blocked = None if datetime.time(h, m, sec) <= cut else "late login (%s, cutoff %s)" % (la[:5], cut.strftime("%H:%M"))
        elif t > cut:
            self.state.trading_blocked = "no login by %s" % cut.strftime("%H:%M")
        else:
            self.state.trading_blocked = None
        if la is not None or t >= EOD:
            return
        if t <= cut:
            due = [p for p in LOGIN_PROMPTS if t >= p]
            if due:
                keys = ["prompt-%02d%02d" % (p.hour, p.minute) for p in due]
                fresh = [k for k in keys if not self.store.kv_get(self._k(k))]
                for k in keys:
                    self.store.kv_set(self._k(k), "1")
                if fresh:
                    self._say("info", "Kite login needed (trading needs a login by %s).\n%s" % (cut.strftime("%H:%M"), self.login_link()))
        elif self._once("cutoff-passed"):
            self._say("info", "No login by %s: TODAY IS DATA_ONLY (no trading). Log in any time before midnight and the day's data "
                              "is still collected.\n%s" % (cut.strftime("%H:%M"), self.login_link()))

    def _vix(self, now, t):
        """Data only: India VIX every 5 minutes into bars(src='vix'). Never touches the rules; failures are logged, not fatal."""
        if self.engine is None or self.provider is None or not hasattr(self.provider, "vix") or not (T(9, 15) <= t < EOD):
            return
        slot = (t.hour * 60 + t.minute - (9 * 60 + 15)) // 5
        if self.store.kv_get(self._k("vix-slot")) == str(slot):
            return
        self.store.kv_set(self._k("vix-slot"), str(slot))
        try:
            px = self.provider.vix()
            if px:
                self.store.put_bar(self.day, "INDIA VIX", slot, px, px, px, px, 0, "vix")
        except Exception as e:
            if self._once("vix-fail"):
                self.store.event("WARN", "vix", "unavailable: %s" % type(e).__name__)

    def _simulate_missed(self):
        """Late-login days: rebuild each would-have trade from the stored 5-min bars with the SAME research exit rule
        (stop / 3R target on wick touch, time exit after 12 bars). Stored as mode 'late-sim', never mixed into real stats.
        Idempotent. Returns the number of simulated trades."""
        n = 0
        for sg in self.store.signals_for_day(self.day):
            if sg["status"] != "missed" or sg["reasons"] != "late_login" or sg["entry"] is None:
                continue
            sid = self.store.signal_id(self.day, sg["symbol"], sg["slot"])
            if self.store.trade_for_signal(sid) is not None:
                continue
            by = {}
            for src in ("backfill", "live"):             # live bars win where both exist
                for b in self.store.get_bars(self.day, sg["symbol"], src):
                    by[b["slot"]] = {"O": b["o"], "H": b["h"], "L": b["l"], "C": b["c"]}
            r, j, why = R.simulate_exit(by, sg["slot"], sg["entry"], sg["stop"])
            px = {"stop": sg["stop"], "target": sg["target"]}.get(why, by[j]["C"] if j in by else sg["entry"])
            tid, _ = self.store.add_trade(sid, "late-sim", 0, R.tstr(sg["slot"] + 1), sg["entry"])
            self.store.close_trade(tid, R.tstr(j + 1 if why == "time" else j), px, why, r)
            n += 1
        return n

    def _recover(self, now):
        """After the close (or on /recover): a login exists but no engine ran today -> pull the whole day's bars from history."""
        if self.provider is None or self.login is None or self.store.kv_get(self._k("recovered")):
            return
        if self.store.kv_get(self._k("engine_ran")) and not self.recover_requested:
            return                      # a normal session ran today (e.g. restarted after the close): nothing to recover
        if not self.recover_requested and not (self.login.logged_in_today() and self.engine is None):
            return
        if self.last_recover_try is not None and (now - self.last_recover_try).total_seconds() < MORNING_RETRY_S:
            return
        self.last_recover_try = now
        if not self.login.logged_in_today():
            if self.recover_requested and self._once("recover-nologin"):
                self._say("info", "Recovery needs a login first: /login")
            return
        try:
            plan = self.provider.morning(self.day)
        except Exception as e:
            self.store.event("ERROR", "recover", "%s: %s" % (type(e).__name__, str(e)[:150]))
            if self._once("recover-alert"):
                self._say("info", "Recovery failed, retrying every %ds: %s" % (MORNING_RETRY_S, type(e).__name__))
            return
        self.recover_requested = False
        if plan is None:
            return
        self.state.trading_blocked = self.state.trading_blocked or "recovery run"
        self.mute = True
        try:
            n = self._setup(plan, start_feed=False, recovery=True)
            if self.engine is not None and self.pipe is not None:
                self.pipe.flush()
                self.engine.end_of_day()
        finally:
            self.mute = False
        self.state.token_ok = True
        self._simulate_missed()
        self.store.kv_set(self._k("recovered"), "1")
        sigs = [x for x in self.store.signals_for_day(self.day) if x["reasons"] == "late_login"]
        lines = []
        for x in sigs:
            tr = self.store.trade_for_signal(self.store.signal_id(self.day, x["symbol"], x["slot"]))
            lines.append("  %s %s: %s" % (x["symbol"], R.tstr(x["slot"]), "entry %.2f -> %s %.2f, %s, R %+.2f" % (
                tr["entry_px"], tr["exit_t"], tr["exit_px"], tr["exit_reason"], tr["r_mult"]) if tr else "no simulation (bars missing)"))
        self._say("info", "Recovered %d bars for %s from history (DATA_ONLY, nothing traded). The rules ran on the whole day: "
                          "%d signal(s) would have fired%s" % (n, self.day, len(sigs), (":\n" + "\n".join(lines)) if lines else "."))

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
                if self.login is None and self._once("token-alert"):
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
        self._setup(plan, start_feed=True)

    def _engine_notify(self, kind, payload):
        if not self.mute:
            self.notify(kind, payload)

    def _setup(self, plan, start_feed=True, recovery=False):
        """Build engine + pipeline from a morning plan, back-fill, start the feed. Returns bars back-filled."""
        data_only = bool(self.state.trading_blocked)
        if not recovery:
            self.store.kv_set(self._k("engine_ran"), "1")
        eng = Engine(self.store, self.broker, self.day, mode="live" if self.state.live_active() else "paper",
                     notify=self._engine_notify, guard=RiskGuard(self.store, self.state))
        if data_only:
            eng.accepting, eng.block_reason = False, "late_login"
        syms = []
        for spec, prev_close, seeds in plan["indexes"]:
            eng.add_index(spec, prev_close, seeds)
            syms.append(spec.symbol)
            syms.extend(o.symbol for o in spec.options)
        self.engine = eng
        self.pipe = Pipeline(self.store, eng, syms)
        back = plan.get("backfill") or []
        if back:
            was_muted, self.mute = self.mute, True
            eng.accepting = False
            for sym, slot, o, h, l, c in back:
                eng.on_open(sym, slot, o)
                eng.on_bar(sym, slot, o, h, l, c)
                self.store.put_bar(self.day, sym, slot, o, h, l, c, 0, "backfill")
                bb = self.pipe.bb[sym]
                bb.day, bb.closed_slot, bb.last_close = self.day, max(bb.closed_slot, slot), c
            eng.accepting = not data_only
            self.mute = was_muted
        self.feed = plan.get("feed") if start_feed else None
        if self.feed is not None:
            self.feed.set_handler(self.on_tick)
            self.feed.subscribe(syms)
            self.feed.start()
        self.store.event("INFO", "morning", "ready: %d symbols, backfill %d bars%s" % (len(syms), len(back), " DATA_ONLY" if data_only else ""))
        return len(back)

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
        self._simulate_missed()
        text = day_summary(self.store, self.day)
        if self.state.trading_blocked:
            late = len([x for x in self.store.signals_for_day(self.day) if x["reasons"] == "late_login"])
            text += "\nDATA_ONLY: %s. %d signal(s) would have fired, none traded." % (self.state.trading_blocked, late)
            if self.login is not None and not self.login.logged_in_today():
                text += "\nNo login today: no data was collected. Log in before midnight (/login) to recover the day's bars."
        if self.provider is None:
            text += "\n(no market-data provider configured)"
        vb = self.store.get_bars(self.day, "INDIA VIX", "vix")
        if vb:
            text += "\nIndia VIX (data only): open %.2f, close %.2f, high %.2f, low %.2f." % (
                vb[0]["c"], vb[-1]["c"], max(b["c"] for b in vb), min(b["c"] for b in vb))
        self._say("summary", text)
        if datetime.datetime.strptime(self.day, "%Y-%m-%d").weekday() == 4:
            from trader.compare import compare
            self._say("info", compare(self.store))
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
