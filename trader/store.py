"""SQLite spine (single writer). Python 3.6+ stdlib only."""
import sqlite3, time

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars(
  day TEXT, symbol TEXT, slot INTEGER, o REAL, h REAL, l REAL, c REAL, n INTEGER, src TEXT,
  PRIMARY KEY(day, symbol, slot, src));
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, symbol TEXT, slot INTEGER, side TEXT,
  status TEXT, reasons TEXT, entry REAL, stop REAL, target REAL, rules_version TEXT, gap REAL, dist REAL,
  UNIQUE(day, symbol, slot));
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER UNIQUE, mode TEXT, qty INTEGER,
  entry_t TEXT, entry_px REAL, exit_t TEXT, exit_px REAL, exit_reason TEXT, r_mult REAL, pnl REAL);
CREATE TABLE IF NOT EXISTS events(ts TEXT, level TEXT, kind TEXT, msg TEXT);
CREATE TABLE IF NOT EXISTS health(ts TEXT, last_tick_ts TEXT, bars_built INTEGER, lag_ms INTEGER);
CREATE TABLE IF NOT EXISTS recon(day TEXT, symbol TEXT, slot INTEGER, live_c REAL, hist_c REAL, diff REAL);
"""

def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")

class Store(object):
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def put_bar(self, day, symbol, slot, o, h, l, c, n=0, src="live"):
        self.db.execute("INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?)", (day, symbol, slot, o, h, l, c, n, src))
        self.db.commit()

    def get_bars(self, day, symbol, src="live"):
        cur = self.db.execute("SELECT * FROM bars WHERE day=? AND symbol=? AND src=? ORDER BY slot", (day, symbol, src))
        return [dict(r) for r in cur.fetchall()]

    def add_signal(self, day, symbol, slot, side, status, reasons="", entry=None, stop=None, target=None,
                   rules_version="v3.0", gap=None, dist=None):
        """Idempotent: a (day,symbol,slot) signal is stored once. Returns (id, created)."""
        cur = self.db.execute("SELECT id FROM signals WHERE day=? AND symbol=? AND slot=?", (day, symbol, slot))
        row = cur.fetchone()
        if row: return row["id"], False
        cur = self.db.execute("INSERT INTO signals(day,symbol,slot,side,status,reasons,entry,stop,target,rules_version,gap,dist)"
                              " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                              (day, symbol, slot, side, status, reasons, entry, stop, target, rules_version, gap, dist))
        self.db.commit()
        return cur.lastrowid, True

    def add_trade(self, signal_id, mode, qty, entry_t, entry_px):
        """Idempotent per signal. Returns (trade_id, created)."""
        row = self.db.execute("SELECT id FROM trades WHERE signal_id=?", (signal_id,)).fetchone()
        if row: return row["id"], False
        cur = self.db.execute("INSERT INTO trades(signal_id,mode,qty,entry_t,entry_px) VALUES(?,?,?,?,?)",
                              (signal_id, mode, qty, entry_t, entry_px))
        self.db.commit()
        return cur.lastrowid, True

    def close_trade(self, trade_id, exit_t, exit_px, reason, r_mult, pnl=None):
        self.db.execute("UPDATE trades SET exit_t=?,exit_px=?,exit_reason=?,r_mult=?,pnl=? WHERE id=?",
                        (exit_t, exit_px, reason, r_mult, pnl, trade_id))
        self.db.commit()

    def open_trades(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM trades WHERE exit_t IS NULL")]

    def event(self, level, kind, msg):
        self.db.execute("INSERT INTO events VALUES(?,?,?,?)", (now_s(), level, kind, msg)); self.db.commit()

    def close(self):
        self.db.close()
