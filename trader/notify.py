"""Push alerts. Formatting is pure; Notifier sends via a transport and NEVER raises (alerts must not stop trading)."""
from trader import rules_v3 as R


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def day_summary(store, day):
    sigs = store.signals_for_day(day)
    trs = store.trades_for_day(day)
    closed = [t for t in trs if t["exit_t"] is not None]
    wins = len([t for t in closed if (t["r_mult"] or 0) > 0])
    r = sum(t["r_mult"] or 0.0 for t in closed)
    rej = len([s for s in sigs if s["status"] == "rejected"])
    real = len([s for s in sigs if s["status"] in ("traded", "missed")])
    lines = ["Summary %s: %d signals, %d trades, %d closed (%d win / %d loss), R %+.2f  [%d pattern matches checked, %d rejected]" % (
        day, real, len(trs), len(closed), wins, len(closed) - wins, r, len(sigs), rej)]
    for t in trs:
        lines.append("  %s %s in %.2f -> %s R %s" % (
            t["symbol"], t["entry_t"], t["entry_px"],
            "open" if t["exit_t"] is None else "%.2f %s" % (t["exit_px"], t["exit_reason"]),
            "n/a" if t["r_mult"] is None else "%+.2f" % t["r_mult"]))
    for t in store.sim_trades_for_day(day):
        lines.append("  late-sim %s in %s %.2f -> %s %.2f %s R %+.2f (hold %s min)" % (
            t["symbol"], t["entry_t"], t["entry_px"], t["exit_t"], t["exit_px"], t["exit_reason"], t["r_mult"],
            _minutes(t["exit_t"]) - _minutes(t["entry_t"])))
    return "\n".join(lines)


def format_event(kind, p):
    if kind == "signal":
        if p["status"] in ("skipped", "dropped"):
            return None
        if p["status"] == "rejected" and p.get("reasons") == "not-ATM":
            return None             # by-design noise: stays in the database and the exports, not on Telegram
        tag = {"traded": "SIGNAL", "missed": "SIGNAL MISSED"}.get(p["status"], "pattern rejected")
        return "%s %s at %s%s" % (tag, p["symbol"], p["t"], (" (%s)" % p["reasons"]) if p["reasons"] else "")
    if kind == "entry":
        return "ENTRY %s qty %s @ %.2f  stop %.2f  target %.2f  (%s)" % (p["symbol"], p["qty"], p["price"], p["stop"], p["target"], p["t"])
    if kind == "exit":
        return "EXIT %s %s @ %.2f  R %+.2f  pnl %.2f  (%s)" % (p["symbol"], p["reason"], p["price"], p["r"], p["pnl"], p["t"])
    if kind in ("halt", "feed_stale", "token_missing", "ready", "summary", "info"):
        return p.get("text", kind)
    return None


class Notifier(object):
    def __init__(self, transport, chat_id, store):
        self.transport = transport
        self.chat_id = chat_id
        self.store = store

    def send(self, text):
        try:
            self.transport.send_message(self.chat_id, text)
            return True
        except Exception as e:
            try:
                self.store.event("ERROR", "alert-send", "%s" % type(e).__name__)
            except Exception:
                pass
            return False

    def send_file(self, path, caption=""):
        try:
            self.transport.send_document(self.chat_id, path, caption)
            return True
        except Exception as e:
            try:
                self.store.event("ERROR", "alert-send", "file: %s" % type(e).__name__)
            except Exception:
                pass
            return False

    def __call__(self, kind, payload):
        text = format_event(kind, payload)
        if text:
            self.send(text)
