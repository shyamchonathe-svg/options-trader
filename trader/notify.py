"""Push alerts. Formatting is pure; Notifier sends via a transport and NEVER raises (alerts must not stop trading)."""
from trader import rules_v3 as R


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _bars(store, day, symbol):
    by = {}
    for src in ("backfill", "live"):                 # live bars win where both exist
        for b in store.get_bars(day, symbol, src):
            by[b["slot"]] = b
    return by


def _peak(store, day, t):
    """How far the option ran after entry, in R: within the 12-bar hold window, and to the day's last bar."""
    R = t["entry"] - t["stop"]
    by = _bars(store, day, t["symbol"])
    e = t["slot"] + 1
    if R <= 0 or e not in by:
        return ""
    win = [by[j] for j in range(e, e + 12) if j in by]
    rest = [by[j] for j in sorted(by) if j >= e]
    hw = max(win, key=lambda b: b["h"])
    pw = max(rest, key=lambda b: b["h"])
    return "\n      ran up to %+.1fR in the 12-bar window, %+.1fR by day end (high %.2f)" % (
        (hw["h"] - t["entry"]) / R, (pw["h"] - t["entry"]) / R, pw["h"])


def _trade_line(store, day, t, tag):
    hold = "" if t["exit_t"] is None else " held %d min" % (_minutes(t["exit_t"]) - _minutes(t["entry_t"]))
    ex = "OPEN" if t["exit_t"] is None else "exit %s @ %.2f (%s)" % (t["exit_t"], t["exit_px"], t["exit_reason"])
    r = "" if t["r_mult"] is None else "  R %+.2f" % t["r_mult"]
    return "  %s%s\n      entry %s @ %.2f  stop %.2f  target %.2f  %s%s%s%s" % (
        tag, t["symbol"], t["entry_t"], t["entry_px"], t["stop"], t["target"], ex, r, hold, _peak(store, day, t))


def day_summary(store, day):
    sigs = store.signals_for_day(day)
    trs = store.trades_for_day(day)
    closed = [t for t in trs if t["exit_t"] is not None]
    wins = len([t for t in closed if (t["r_mult"] or 0) > 0])
    r = sum(t["r_mult"] or 0.0 for t in closed)
    rej = [s for s in sigs if s["status"] == "rejected"]
    real = len([s for s in sigs if s["status"] in ("traded", "missed")])
    lines = ["Day report %s: %s" % (day, "%d trade(s), %d closed (%d win / %d loss), R %+.2f" % (
        len(trs), len(closed), wins, len(closed) - wins, r) if trs else "NO TRADE today")]
    for t in trs:
        lines.append(_trade_line(store, day, t, ""))
    sims = store.sim_trades_for_day(day)
    for t in sims:
        lines.append(_trade_line(store, day, t, "[late-sim, not a real trade] "))
    why = {}
    for s in rej:
        for w in (s["reasons"] or "?").split(","):
            why[w] = why.get(w, 0) + 1
    lines.append("Checked %d pattern matches across the chains: %d signal(s), %d rejected%s." % (
        len(sigs), real, len(rej), (" (" + ", ".join("%s %d" % kv for kv in sorted(why.items())) + ")") if why else ""))
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
