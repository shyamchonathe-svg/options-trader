"""Tick -> 5-minute bars. Slot 0 = 09:15, slot 74 = 15:25. Timestamps are naive IST datetimes (exchange time).
Policy:
  * a bar closes when the first tick of a LATER slot arrives, or when close_due(now) passes slot end + grace
  * a slot with no ticks gets a flat bar (O=H=L=C=previous close, src 'flat', n=0) so EMA sequences have no holes
  * ticks older than the current slot ("late") are ignored and counted; ticks outside 09:15-15:30 are ignored
"""
import datetime

OPEN_MIN = 9 * 60 + 15
LAST_SLOT = 74
GRACE_S = 2


def slot_of(ts):
    m = ts.hour * 60 + ts.minute
    s = (m - OPEN_MIN) // 5
    return s if 0 <= s <= LAST_SLOT else None


def slot_end(day_dt, slot):
    """datetime at which `slot` ends (day_dt: any datetime/date of that day)."""
    base = datetime.datetime(day_dt.year, day_dt.month, day_dt.day, 9, 15)
    return base + datetime.timedelta(minutes=5 * (slot + 1))


class BarBuilder(object):
    def __init__(self, symbol):
        self.symbol = symbol
        self.cur = None            # dict for the open slot
        self.last_close = None
        self.late = 0
        self.ignored = 0
        self.day = None
        self.closed_slot = -1      # highest slot already emitted

    def _emit(self, bar, src="live"):
        out = dict(bar); out["src"] = src; out["symbol"] = self.symbol
        self.last_close = bar["C"]
        self.closed_slot = max(self.closed_slot, bar["slot"])
        return out

    def _flat(self, day, slot):
        c = self.last_close
        return {"day": day, "slot": slot, "O": c, "H": c, "L": c, "C": c, "n": 0}

    def on_tick(self, ts, price):
        """Returns list of bars that closed because of this tick (may include flat fillers)."""
        s = slot_of(ts)
        if s is None:
            self.ignored += 1; return []
        day = ts.strftime("%Y-%m-%d")
        closed = []
        if self.day != day:                      # new session
            self.day = day; self.cur = None; self.last_close = None; self.closed_slot = -1
        if self.cur is not None and s < self.cur["slot"]:
            self.late += 1; return []
        if self.cur is None and s <= self.closed_slot:      # slot already emitted (e.g. by timer)
            self.late += 1; return []
        if self.cur is not None and s == self.cur["slot"]:
            b = self.cur
            b["H"] = max(b["H"], price); b["L"] = min(b["L"], price); b["C"] = price; b["n"] += 1
            return []
        if self.cur is not None:                 # moved to a later slot: close current, fill gaps
            closed.append(self._emit(self.cur))
            for g in range(self.cur["slot"] + 1, s):
                if self.last_close is not None:
                    closed.append(self._emit(self._flat(day, g), "flat"))
        if self.cur is None and self.closed_slot >= 0 and self.last_close is not None:   # gap after timer close
            for g in range(self.closed_slot + 1, s):
                closed.append(self._emit(self._flat(day, g), "flat"))
        self.cur = {"day": day, "slot": s, "O": price, "H": price, "L": price, "C": price, "n": 1}
        return closed

    def close_due(self, now):
        """Timer path: close the open bar once now >= slot end + grace. Returns list (0 or 1 bars)."""
        if self.cur is None: return []
        if now >= slot_end(now, self.cur["slot"]) + datetime.timedelta(seconds=GRACE_S):
            b = self._emit(self.cur); self.cur = None
            return [b]
        return []

    def flush(self):
        """End of day: close whatever is open."""
        if self.cur is None: return []
        b = self._emit(self.cur); self.cur = None
        return [b]
