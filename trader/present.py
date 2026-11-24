"""Plain-English presentation layer (UI 2.0). The Telegram user never sees code variable names; every user-facing text
is built here from raw state. Raw output stays available through /debug. Pure functions, Python 3.6 compatible."""
import re

_SYM = re.compile(r"^(?:[A-Z]+:)?(NIFTY|SENSEX)(?:\d{2}[1-9OND]\d{2}|\d{2}[A-Z]{3})(\d+)(CE|PE)$")
_NAMES = {"NIFTY": "Nifty", "SENSEX": "Sensex"}
_REASONS = {"stop": "stop-loss hit", "target": "profit target hit", "time": "time limit reached", "trail": "trailing stop hit",
            "eod": "market close", "flat": "closed manually", "manual": "closed manually"}


def pretty_symbol(sym):
    """'NFO:NIFTY26NOV25300PE' -> 'Nifty 25300 PE'. Unknown shapes are returned unchanged."""
    m = _SYM.match(sym or "")
    if not m:
        return sym or ""
    return "%s %s %s" % (_NAMES[m.group(1)], m.group(2), m.group(3))


def index_name(sym):
    m = _SYM.match(sym or "")
    return _NAMES[m.group(1)] if m else ""


def inr(x, sign=False):
    """Indian digit grouping: 123456.7 -> '1,23,457'. sign=True adds +/-."""
    neg = x < 0
    n = int(round(abs(x)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    pre = "-" if neg else ("+" if sign else "")
    return "%s\u20b9%s" % (pre, s)


def exit_reason(r):
    return _REASONS.get(r, r or "")


def entry_text(p):
    """Telegram text for a new position. p = engine 'entry' payload."""
    lines = ["BOUGHT  %s" % pretty_symbol(p["symbol"]),
             "At %s  @ \u20b9%.2f" % (p["t"], p["price"])]
    if p.get("index_px"):
        lines.append("%s was at %s" % (p.get("index") or "Index", "{:,.2f}".format(p["index_px"])))
    q = p.get("qty")
    if q:
        lines.append("Quantity %d  (invested %s)" % (q, inr(q * p["price"])))
    return "\n".join(lines)


def exit_text(p):
    """Telegram text for a closed position. p = engine 'exit' payload (carries the entry details)."""
    nm = p.get("index") or "Index"

    def ix(v):
        return " (%s %s)" % (nm, "{:,.2f}".format(v)) if v else ""
    lines = ["SOLD  %s" % pretty_symbol(p["symbol"])]
    if p.get("entry_t"):
        lines.append("Bought %s @ \u20b9%.2f%s" % (p["entry_t"], p["entry_px"], ix(p.get("entry_index_px"))))
    lines.append("Sold   %s @ \u20b9%.2f%s" % (p["t"], p["price"], ix(p.get("index_px"))))
    lines.append("Reason: %s" % exit_reason(p["reason"]))
    lines.append("Profit/Loss: %s" % inr(p["pnl"], sign=True))
    return "\n".join(lines)


def blocked_text(why):
    w = why or ""
    if w.startswith("late login"):
        return "you logged in after the 09:15 cut-off, so today is data-only"
    if w.startswith("no login"):
        return "no login by 09:15, so today is data-only"
    if w.startswith("day skipped"):
        return "today is marked as a holiday / skipped"
    if w.startswith("recovery"):
        return "this day was rebuilt afterwards, so nothing was traded"
    return w


def _ago(secs):
    if secs is None:
        return "no price received yet"
    if secs < 90:
        return "last price %d s ago" % secs
    return "last price %d min ago" % (secs // 60)


def status_text(st, now, trades, setup_done):
    """st: RuntimeState, trades: today's trade rows."""
    secs = None if st.last_tick_ts is None else max(0, int((now - st.last_tick_ts).total_seconds()))
    openp = [t for t in trades if t["exit_t"] is None]
    done = [t for t in trades if t["exit_t"] is not None]
    pnl = sum((t["pnl"] or 0.0) for t in done)
    live = st.live_active()
    if st.stopped:
        head = "STOPPED - no new trades until you send /resume"
    elif st.paused:
        head = "PAUSED - no new trades until you send /resume"
    elif st.trading_blocked:
        head = "NOT TRADING today - " + blocked_text(st.trading_blocked)
    elif st.token_ok is False:
        head = "ACTION NEEDED - Kite login required (tap Login)"
    elif not setup_done:
        head = "WAITING - market set-up has not started yet" if st.token_ok is None else "WAITING - setting up today's market watch"
    elif st.feed_ok is False:
        head = "ATTENTION - market data has stopped (%s)" % _ago(secs)
    else:
        head = "ALL GOOD - watching Nifty and Sensex"
    lines = [head,
             "Mode: %s" % ("LIVE orders" if live else "practice (no real orders)"),
             "Login today: %s" % ("done" if st.token_ok else ("needed" if st.token_ok is False else "not checked yet")),
             "Market data: %s" % ("live, " + _ago(secs) if st.feed_ok else ("stopped" if st.feed_ok is False else "not started"))]
    if not trades:
        lines.append("Trades today: none yet")
    else:
        lines.append("Trades today: %d (%d open)   P&L so far: %s" % (len(trades), len(openp), inr(pnl, sign=True)))
    return "\n".join(lines)


def health_text(st, now, errors, bars_built=None, lag_ms=None):
    secs = None if st.last_tick_ts is None else max(0, int((now - st.last_tick_ts).total_seconds()))
    lines = ["Market data: %s" % ("live, " + _ago(secs) if st.feed_ok else ("STOPPED" if st.feed_ok is False else "not started")),
             "Kite login: %s" % ("valid" if st.token_ok else ("EXPIRED / missing" if st.token_ok is False else "not checked yet")),
             "System errors in the last 50 events: %s" % (errors or "none")]
    if bars_built is not None:
        lines.append("Candles built today: %s   (data delay about %s ms)" % (bars_built, lag_ms if lag_ms is not None else "?"))
    return "\n".join(lines)


def ready_text(day, ok, mode_live, detail=""):
    if ok:
        return "READY for %s - Nifty and Sensex are being watched. %s" % (
            day, "LIVE orders are armed." if mode_live else "Practice mode: no real orders.")
    return "NOT READY for %s - %s" % (day, detail or "market set-up is still pending")
