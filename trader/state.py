"""Runtime control state shared by the bot, the runner and the risk guard. Persisted in the kv table so a restart keeps
pause/stop/mode/risk limits. `armed` is NEVER persisted: after any restart live is disarmed. Python 3.6 compatible."""
import datetime
import json

RISK_DEFAULTS = {"max_trades_per_day": 2, "daily_loss_R": 2.0, "halt_after_stops": 2, "lots": 1}
RISK_BOUNDS = {"max_trades_per_day": (1, 4), "daily_loss_R": (0.5, 5.0), "halt_after_stops": (1, 5), "lots": (1, 3)}
# for every key a LOWER value is the tighter (safer) setting
DISARM_AT = datetime.time(15, 45)


class RuntimeState(object):
    def __init__(self, store, live_enabled=False, version=""):
        self.store = store
        self.live_enabled = live_enabled
        self.version = version
        self.armed = False
        self.day = None
        self.started = datetime.datetime.now()
        self.last_tick_ts = None
        self.feed_ok = None
        self.token_ok = None
        self.trading_blocked = None     # None, or why today is DATA_ONLY (late / missing login, skipped day)
        self.mode = store.kv_get("mode", "shadow")
        self.paused = store.kv_get("paused", "0") == "1"
        self.stopped = store.kv_get("stopped", "0") == "1"
        self.risk = dict(RISK_DEFAULTS)
        self.risk.update(json.loads(store.kv_get("risk", "{}")))
        self.pending_risk = json.loads(store.kv_get("pending_risk", "{}"))

    def _save(self):
        s = self.store
        s.kv_set("mode", self.mode)
        s.kv_set("paused", "1" if self.paused else "0")
        s.kv_set("stopped", "1" if self.stopped else "0")
        s.kv_set("risk", json.dumps(self.risk))
        s.kv_set("pending_risk", json.dumps(self.pending_risk))

    def set_paused(self, v):
        self.paused = bool(v)
        self._save()

    def set_stopped(self, v):
        self.stopped = bool(v)
        self._save()

    def set_mode(self, mode):
        self.mode = mode
        if mode != "live":
            self.armed = False
        self._save()

    def live_active(self):
        """Orders may be sent only when live is enabled in config, mode is live AND armed today."""
        return self.live_enabled and self.mode == "live" and self.armed and not self.trading_blocked

    def set_risk(self, key, value):
        self.risk[key] = value
        self._save()

    def queue_risk(self, key, value):
        self.pending_risk[key] = value
        self._save()

    def tick(self, now):
        """Call regularly. Returns a list of notable messages (day roll, auto-disarm)."""
        msgs = []
        day = now.strftime("%Y-%m-%d")
        if self.day != day:
            if self.day is not None:
                if self.armed:
                    self.armed = False
                    msgs.append("live disarmed (new day)")
                if self.pending_risk:
                    self.risk.update(self.pending_risk)
                    msgs.append("loosened risk limits now active: %s" % json.dumps(self.pending_risk, sort_keys=True))
                    self.pending_risk = {}
                    self._save()
            self.day = day
        if self.armed and now.time() >= DISARM_AT:
            self.armed = False
            msgs.append("live auto-disarmed at 15:45")
        for m in msgs:
            self.store.event("INFO", "state", m)
        return msgs
