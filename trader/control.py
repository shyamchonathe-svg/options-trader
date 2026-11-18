"""Telegram command handling (pure: text in, reply texts out; no network). Python 3.6 compatible.

Safety model
  * only the whitelisted chat id is answered; every other chat is ignored and logged
  * dangerous commands need a one-time code (2 min); anything that touches LIVE also needs the PIN
  * 3 wrong PINs lock live commands until the next day; live is auto-disarmed at 15:45 and after any restart
  * strategy rules are NOT editable here; /set only changes whitelisted risk limits
  * tightening a limit applies immediately; loosening needs a code and starts next session
"""
import datetime
import random

from trader import rules_v3 as R
from trader import present as P
from trader.state import RISK_BOUNDS

CONFIRM_TTL = 120
MAX_PIN_FAILS = 3

HELP = """Everyday: /status  /positions  /trades  /summary (day report)  /login
More: /health  /risk  /pause /resume /stop /flat
Trade analysis: /analyze [date] [HH:MM] [option] [all] [live]   e.g. /analyze 2026-11-18 09:35 NIFTY25300PE
Technical (for debugging): /debug [status|why|signals|analysis|logs]  /bars <symbol>  /config  /export  /compare
Settings: /set <key> <value>   keys: %s
Live orders (code+PIN): /mode shadow|live  /arm live  /disarm   confirm with: /yes <code> [PIN]
Other: /token <request_token or URL>  /recover  /restart  /note <text>  /ack  /skip  /unskip  /holiday YYYY-MM-DD""" % ", ".join(sorted(RISK_BOUNDS))

COMMANDS = ("analyze debug help start status health positions signals why trades summary compare risk bars config logs replay export "
            "menu pause resume stop flat restart note ack set mode arm disarm token yes login skip unskip holiday recover").split()


def _fmt_r(x):
    return "n/a" if x is None else "%+.2f" % x


class Controller(object):
    def __init__(self, store, state, chat_id, pinfile=None, hooks=None, clock=None, rng=None):
        self.store = store
        self.state = state
        self.chat_id = str(chat_id)
        self.pinfile = pinfile
        self.hooks = hooks or {}
        self.clock = clock or datetime.datetime.now
        self.rng = rng or random.SystemRandom()
        self.pending = {}

    # ------------------------------------------------------------------ entry
    @staticmethod
    def is_sensitive(text):
        t = text.strip().lower()
        return t.startswith("/token") or t.startswith("/yes")

    def handle(self, chat_id, text):
        if str(chat_id) != self.chat_id:
            self.store.event("WARN", "unauth", "ignored chat %s" % chat_id)
            return []
        now = self.clock()
        self.state.tick(now)
        text = (text or "").strip()
        if not text.startswith("/"):
            return ["Send /help for the command list."]
        parts = text.split()
        cmd = parts[0][1:].split("@")[0].lower()
        args = parts[1:]
        shown = "/" + cmd if cmd in ("token", "yes") else text[:200]
        self.store.event("AUDIT", "cmd", shown)
        if cmd not in COMMANDS:
            return ["Unknown command. /help"]
        try:
            out = getattr(self, "cmd_" + cmd)(args, now)
        except Exception as e:
            self.store.event("ERROR", "cmd", "%s: %r" % (cmd, e))
            return ["Command failed: %s" % e]
        return out if isinstance(out, list) else [out]

    # ------------------------------------------------------------------ helpers
    def _day(self, args, now):
        return args[0] if args and len(args[0]) == 10 else now.strftime("%Y-%m-%d")

    def _hook(self, name, *a):
        h = self.hooks.get(name)
        return None if h is None else h(*a)

    def _ask(self, action, args, desc, need_pin, now):
        for c in [c for c, p in self.pending.items() if p["exp"] < now]:
            del self.pending[c]
        code = "%06d" % self.rng.randrange(1000000)
        self.pending[code] = {"action": action, "args": args, "pin": need_pin,
                              "exp": now + datetime.timedelta(seconds=CONFIRM_TTL)}
        return "Confirm: %s\nReply: /yes %s%s   (valid 2 minutes)" % (desc, code, " <PIN>" if need_pin else "")

    def _pin_locked(self, now):
        return self.store.kv_get("pin_lock_day") == now.strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ read-only
    def cmd_help(self, args, now):
        return HELP

    cmd_start = cmd_help

    def cmd_menu(self, args, now):
        return "Tap a button, or type /help for every command."

    def cmd_status(self, args, now):
        day = now.strftime("%Y-%m-%d")
        return P.status_text(self.state, now, self.store.trades_for_day(day), getattr(self.state, "setup_done", False))

    def cmd_health(self, args, now):
        st = self.state
        row = self.store.db.execute("SELECT * FROM health ORDER BY rowid DESC LIMIT 1").fetchone()
        errs = len([e for e in self.store.recent_events(50) if e["level"] == "ERROR"])
        return P.health_text(st, now, errs, None if row is None else row["bars_built"], None if row is None else row["lag_ms"])

    def cmd_analyze(self, args, now):
        """Re-examine any stored day like a chart: which v3 conditions matched or failed for a candle/option."""
        from trader.analyze import analyze
        day, hhmm, flags, rest = now.strftime("%Y-%m-%d"), None, set(), []
        for a in args:
            if len(a) == 10 and a[4] == "-":
                day = a
            elif ":" in a:
                hhmm = a
            elif a.lower() in ("all", "live"):
                flags.add(a.lower())
            else:
                rest.append(a)
        try:
            return analyze(self.store, day, hhmm, " ".join(rest) or None, "live" if "live" in flags else "hist", "all" in flags)
        except ValueError as e:
            return str(e)

    def cmd_debug(self, args, now):
        """Raw, technical views (variable names allowed here only)."""
        sub = args[0].lower() if args else "status"
        rest = args[1:]
        if sub == "status":
            st, day = self.state, now.strftime("%Y-%m-%d")
            age = "n/a" if st.last_tick_ts is None else "%ds" % max(0, int((now - st.last_tick_ts).total_seconds()))
            return ("v%s mode=%s armed=%s paused=%s stopped=%s feed_ok=%s last_tick=%s token_ok=%s setup_done=%s blocked=%s\n"
                    "signals %d, trades %d") % (st.version, st.mode, st.armed, st.paused, st.stopped, st.feed_ok, age,
                                                st.token_ok, getattr(st, "setup_done", None), st.trading_blocked,
                                                len(self.store.signals_for_day(day)), len(self.store.trades_for_day(day)))
        if sub == "signals":
            return self.cmd_signals(rest, now)
        if sub == "why":
            return self.cmd_why(rest, now)
        if sub == "analysis":
            from trader.notify import analysis_report
            return analysis_report(self.store, self._day(rest, now))
        if sub == "logs":
            return self.cmd_logs(rest, now)
        return "usage: /debug status|why HH:MM [symbol]|signals [day]|analysis [day]|logs [n]"

    def cmd_positions(self, args, now):
        day = now.strftime("%Y-%m-%d")
        rows = [t for t in self.store.trades_for_day(day) if t["exit_t"] is None]
        if not rows:
            return "No open positions."
        return "\n".join("%s  qty %s  bought %s @ %.2f   (stop %.2f, target %.2f)" % (
            P.pretty_symbol(t["symbol"]), t["qty"], t["entry_t"], t["entry_px"], t["stop"], t["target"]) for t in rows)

    def cmd_signals(self, args, now):
        rows = self.store.signals_for_day(self._day(args, now))
        if not rows:
            return "No signals."
        return "\n".join("%s %s %s %s%s" % (R.tstr(s["slot"]), s["symbol"], s["side"], s["status"],
                                           (" (%s)" % s["reasons"]) if s["reasons"] else "") for s in rows)

    def cmd_why(self, args, now):
        if not args or ":" not in args[0]:
            return "usage: /why HH:MM [symbol]"
        h, m = args[0].split(":")
        slot = (int(h) * 60 + int(m) - (9 * 60 + 15)) // 5
        rows = [s for s in self.store.signals_for_day(now.strftime("%Y-%m-%d")) if s["slot"] in (slot, slot - 1)]
        if len(args) > 1:
            rows = [s for s in rows if args[1].lower() in s["symbol"].lower()]
        if not rows:
            return "No signal recorded near %s (the rules found nothing to act on)." % args[0]
        out = []
        for s in rows:
            out.append("%s %s %s: %s%s | entry %s stop %s target %s | gap %s dist %s steps | rules %s" % (
                R.tstr(s["slot"]), s["symbol"], s["side"], s["status"],
                (" - " + s["reasons"]) if s["reasons"] else "",
                s["entry"], s["stop"], s["target"],
                "n/a" if s["gap"] is None else "%.2f%%" % (100 * s["gap"]),
                "n/a" if s["dist"] is None else "%.2f" % s["dist"], s["rules_version"]))
        return out

    def cmd_trades(self, args, now):
        from trader.notify import day_summary
        return day_summary(self.store, self._day(args, now))

    def cmd_summary(self, args, now):
        from trader.notify import day_summary
        return day_summary(self.store, self._day(args, now))

    def cmd_compare(self, args, now):
        from trader.compare import compare
        return compare(self.store)

    def cmd_risk(self, args, now):
        day = now.strftime("%Y-%m-%d")
        closed = self.store.closed_trades_for_day(day)
        pend = "" if not self.state.pending_risk else "\npending (next session): %s" % self.state.pending_risk
        return "limits: %s%s\ntoday: %d trades, closed R %s" % (
            self.state.risk, pend, len(self.store.trades_for_day(day)), _fmt_r(sum(t["r_mult"] or 0 for t in closed)))

    def cmd_bars(self, args, now):
        if not args:
            return "usage: /bars <symbol>"
        name = " ".join(args)
        rows = self.store.get_bars(now.strftime("%Y-%m-%d"), name)[-6:]
        if not rows:
            rows = self.store.get_bars(now.strftime("%Y-%m-%d"), name, "vix")[-6:]
        if not rows:
            return "No bars stored for %s today." % name
        return "\n".join("%s O%.2f H%.2f L%.2f C%.2f n=%s" % (R.tstr(r["slot"]), r["o"], r["h"], r["l"], r["c"], r["n"]) for r in rows)

    def cmd_config(self, args, now):
        txt = self._hook("config")
        return "v%s rules %s\nlimits %s\nlive enabled: %s\n%s" % (
            self.state.version, getattr(R, "__name__", ""), self.state.risk, self.state.live_enabled, txt or "")

    def cmd_logs(self, args, now):
        n = min(30, int(args[0])) if args and args[0].isdigit() else 10
        rows = self.store.recent_events(n)
        return "\n".join("%s %s %s %s" % (r["ts"][11:], r["level"], r["kind"], r["msg"]) for r in rows) or "No events."

    def cmd_replay(self, args, now):
        r = self._hook("replay", args)
        return r or "Replay is not available in this build."

    def cmd_export(self, args, now):
        r = self._hook("export", args)
        return r or "Export is not available in this build."

    # ------------------------------------------------------------------ control
    def cmd_pause(self, args, now):
        self.state.set_paused(True)
        return "Paused: no new entries (open positions keep running). /resume to continue."

    def cmd_resume(self, args, now):
        self.state.set_paused(False)
        self.state.set_stopped(False)
        return "Resumed."

    def cmd_note(self, args, now):
        self.store.event("INFO", "note", " ".join(args)[:300])
        return "Noted."

    def cmd_ack(self, args, now):
        self.store.event("INFO", "ack", "alerts acknowledged")
        return "Acknowledged."

    def cmd_token(self, args, now):
        if not args:
            return "usage: /token <request_token>"
        r = self._hook("token", args[0])
        return r or "Token handling is not available in this build."

    def cmd_login(self, args, now):
        r = self._hook("login")
        return r or "Login links are not available in this build (no Kite configured)."

    def cmd_skip(self, args, now):
        return self._hook("skip", True) or "Not available."

    def cmd_unskip(self, args, now):
        return self._hook("skip", False) or "Not available."

    def cmd_holiday(self, args, now):
        if not args:
            return "usage: /holiday YYYY-MM-DD"
        try:
            datetime.datetime.strptime(args[0], "%Y-%m-%d")
        except ValueError:
            return "Date must look like 2026-11-25."
        return self._hook("holiday", args[0]) or "Not available."

    def cmd_recover(self, args, now):
        return self._hook("recover") or "Not available."

    def cmd_stop(self, args, now):
        return self._ask("stop", [], "STOP: pause new entries AND close all open positions", False, now)

    def cmd_flat(self, args, now):
        return self._ask("flat", [], "close all open positions now", False, now)

    def cmd_restart(self, args, now):
        return self._ask("restart", [], "restart the trader process", False, now)

    def cmd_disarm(self, args, now):
        self.state.armed = False
        return "Live disarmed."

    def cmd_mode(self, args, now):
        if not args or args[0] not in ("shadow", "live"):
            return "usage: /mode shadow|live"
        if args[0] == "shadow":
            self.state.set_mode("shadow")
            return "Mode: shadow (paper). Live disarmed."
        if not self.state.live_enabled:
            return "Live trading is not enabled in this build."
        return self._live_ask("mode_live", "switch to LIVE mode (still needs /arm live)", now)

    def cmd_arm(self, args, now):
        if args[:1] != ["live"]:
            return "usage: /arm live"
        if not self.state.live_enabled:
            return "Live trading is not enabled in this build."
        if self.state.mode != "live":
            return "Set /mode live first."
        if self.state.trading_blocked:
            return "No trading today (%s). Live cannot be armed." % self.state.trading_blocked
        return self._live_ask("arm_live", "ARM live trading for today (auto-disarms at 15:45)", now)

    def _live_ask(self, action, desc, now):
        if self.pinfile is None or not self.pinfile.is_set():
            return "No PIN set. On the VM run: python -m trader.pin set"
        if self._pin_locked(now):
            return "Live commands are locked until tomorrow (too many wrong PINs)."
        return self._ask(action, [], desc, True, now)

    def cmd_set(self, args, now):
        if len(args) != 2 or args[0] not in RISK_BOUNDS:
            return "usage: /set <key> <value>   keys: %s (strategy rules cannot be changed here)" % ", ".join(sorted(RISK_BOUNDS))
        key = args[0]
        lo, hi = RISK_BOUNDS[key]
        try:
            val = float(args[1]) if isinstance(self.state.risk[key], float) else int(args[1])
        except ValueError:
            return "Bad value."
        if not lo <= val <= hi:
            return "%s must be between %s and %s." % (key, lo, hi)
        cur = self.state.risk[key]
        if val <= cur:
            self.state.set_risk(key, val)
            self.store.event("INFO", "risk", "%s %s -> %s (tighten, now)" % (key, cur, val))
            return "%s = %s (applied now)." % (key, val)
        return self._ask("set_loosen", [key, val], "LOOSEN %s %s -> %s (takes effect next session)" % (key, cur, val), False, now)

    def cmd_yes(self, args, now):
        if not args:
            return "usage: /yes <code> [PIN]"
        p = self.pending.get(args[0])
        if p is None or p["exp"] < now:
            self.pending.pop(args[0], None)
            return "No such confirmation (or it expired)."
        if p["pin"]:
            if self._pin_locked(now):
                return "Live commands are locked until tomorrow."
            pin = args[1] if len(args) > 1 else ""
            if not self.pinfile.verify(pin):
                fails = int(self.store.kv_get("pin_fails", "0")) + 1
                self.store.kv_set("pin_fails", fails)
                self.store.event("WARN", "pin", "wrong PIN (%d)" % fails)
                if fails >= MAX_PIN_FAILS:
                    self.store.kv_set("pin_lock_day", now.strftime("%Y-%m-%d"))
                    self.store.kv_set("pin_fails", 0)
                    self.pending.clear()
                    return "Wrong PIN. Live commands are now locked until tomorrow."
                return "Wrong PIN (%d of %d)." % (fails, MAX_PIN_FAILS)
            self.store.kv_set("pin_fails", 0)
        del self.pending[args[0]]
        return self._do(p["action"], p["args"], now)

    def _do(self, action, a, now):
        if action == "flat":
            n = self._hook("flat")
            return "Flat: closed %s position(s)." % (n if n is not None else "?")
        if action == "stop":
            self.state.set_stopped(True)
            n = self._hook("flat")
            return "Stopped: no new entries; closed %s position(s). /resume to continue." % (n if n is not None else "?")
        if action == "restart":
            self.store.event("INFO", "restart", "requested from Telegram")
            self._hook("restart")
            return "Restart requested."
        if action == "mode_live":
            self.state.set_mode("live")
            return "Mode: LIVE (not armed). /arm live to arm."
        if action == "arm_live":
            self.state.armed = True
            self.store.event("WARN", "arm", "live ARMED")
            return "LIVE ARMED until 15:45 (/disarm to stop)."
        if action == "set_loosen":
            self.state.queue_risk(a[0], a[1])
            return "%s = %s queued for next session." % (a[0], a[1])
        return "Unknown action."
