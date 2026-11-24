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
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS recon(day TEXT, symbol TEXT, slot INTEGER, live_c REAL, hist_c REAL, diff REAL);
"""

def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")

class Store(object):
    def __init__(self, path=":memory:"):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self):
        """Additive column migrations (v5): which setup produced a signal; the partial booking of a trade."""
        def cols(t):
            return set(r[1] for r in self.db.execute("PRAGMA table_info(%s)" % t))
        if "setup" not in cols("signals"):
            self.db.execute("ALTER TABLE signals ADD COLUMN setup TEXT")
        for c, typ in (("part_qty", "INTEGER"), ("part_px", "REAL"), ("part_t", "TEXT")):
            if c not in cols("trades"):
                self.db.execute("ALTER TABLE trades ADD COLUMN %s %s" % (c, typ))

    def put_bar(self, day, symbol, slot, o, h, l, c, n=0, src="live"):
        self.db.execute("INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?)", (day, symbol, slot, o, h, l, c, n, src))
        self.db.commit()

    def get_bars(self, day, symbol, src="live"):
        cur = self.db.execute("SELECT * FROM bars WHERE day=? AND symbol=? AND src=? ORDER BY slot", (day, symbol, src))
        return [dict(r) for r in cur.fetchall()]

    def add_signal(self, day, symbol, slot, side, status, reasons="", entry=None, stop=None, target=None,
                   rules_version="v3.0", gap=None, dist=None, setup=None):
        """Idempotent: a (day,symbol,slot) signal is stored once. Returns (id, created)."""
        cur = self.db.execute("SELECT id FROM signals WHERE day=? AND symbol=? AND slot=?", (day, symbol, slot))
        row = cur.fetchone()
        if row: return row["id"], False
        cur = self.db.execute("INSERT INTO signals(day,symbol,slot,side,status,reasons,entry,stop,target,rules_version,gap,dist,setup)"
                              " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (day, symbol, slot, side, status, reasons, entry, stop, target, rules_version, gap, dist, setup))
        self.db.commit()
        return cur.lastrowid, True

    def signal_id(self, day, symbol, slot):
        r = self.db.execute("SELECT id FROM signals WHERE day=? AND symbol=? AND slot=?", (day, symbol, slot)).fetchone()
        return r["id"] if r else None

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

    def book_partial(self, trade_id, t, px, qty):
        """Record the partial exit of a trade (once). Returns False when it was already recorded (restart / re-feed)."""
        r = self.db.execute("SELECT part_t FROM trades WHERE id=?", (trade_id,)).fetchone()
        if r is None or r["part_t"] is not None:
            return False
        self.db.execute("UPDATE trades SET part_t=?, part_px=?, part_qty=? WHERE id=?", (t, px, qty, trade_id))
        self.db.commit()
        return True

    def get_trade(self, trade_id):
        r = self.db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return dict(r) if r else None

    def trade_for_signal(self, signal_id):
        r = self.db.execute("SELECT * FROM trades WHERE signal_id=?", (signal_id,)).fetchone()
        return dict(r) if r else None

    def trade_is_open(self, trade_id):
        r = self.db.execute("SELECT exit_t FROM trades WHERE id=?", (trade_id,)).fetchone()
        return bool(r) and r["exit_t"] is None

    def signals_for_day(self, day):
        return [dict(r) for r in self.db.execute("SELECT * FROM signals WHERE day=? ORDER BY slot, symbol", (day,))]

    def trades_for_day(self, day):
        q = ("SELECT t.*, s.symbol, s.slot, s.entry, s.stop, s.target FROM trades t JOIN signals s ON s.id=t.signal_id "
             "WHERE s.day=? AND t.mode != 'late-sim' ORDER BY s.slot, s.symbol")
        return [dict(r) for r in self.db.execute(q, (day,))]

    def sim_trades_for_day(self, day):
        """Would-have trades on late-login days, rebuilt from bars. Never mixed into the real trade statistics."""
        q = ("SELECT t.*, s.symbol, s.slot, s.entry, s.stop, s.target FROM trades t JOIN signals s ON s.id=t.signal_id "
             "WHERE s.day=? AND t.mode = 'late-sim' ORDER BY s.slot, s.symbol")
        return [dict(r) for r in self.db.execute(q, (day,))]

    def open_trades(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM trades WHERE exit_t IS NULL")]

    def event(self, level, kind, msg):
        self.db.execute("INSERT INTO events VALUES(?,?,?,?)", (now_s(), level, kind, msg)); self.db.commit()

    def kv_get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def kv_set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v)))
        self.db.commit()

    def recent_events(self, n=10, kinds=None):
        rows = [dict(r) for r in self.db.execute("SELECT rowid AS id, * FROM events ORDER BY rowid DESC LIMIT ?", (int(n) * 5,))]
        if kinds:
            rows = [r for r in rows if r["kind"] in kinds]
        return list(reversed(rows[:int(n)]))

    def closed_trades_for_day(self, day):
        return [t for t in self.trades_for_day(day) if t["exit_t"] is not None]

    def close(self):
        self.db.close()
