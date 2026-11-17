"""ALL Kite Connect calls live in this one file (design rule C1). Everything else is testable in the lab.

KiteProvider  implements the Daemon's provider interface:
    token_ok()            True if a Kite access token for TODAY is saved (and the API still accepts it)
    morning(day)          {"indexes": [(IndexSpec, prev_close, seeds)], "backfill": [...], "feed": KiteFeed}
    history(day, symbols) {symbol: [{"slot","O","H","L","C"}]}   (end-of-day reconciliation)
    exchange_token(x)     /token hook: request_token (or the whole redirect URL) -> access token, saved 0600
    config_text()         /config hook: shows the Kite login link
KiteFeed      wraps KiteTicker (full mode) and calls on_tick(Tick) from the ticker thread.

Symbols are exchange:tradingsymbol keys ("NFO:NIFTY26N1725250CE", "NSE:NIFTY 50"), never bare tokens.
Python 3.6 compatible; kiteconnect is imported lazily so the lab (no kiteconnect) can run the tests with fakes.
"""
import datetime
import json
import logging
import os
import re
import time
import urllib.parse

from trader import instruments as I
from trader.clock import ist_now
from trader.engine import IndexSpec, OptionSpec
from trader.feed import Feed, Tick

log = logging.getLogger("kite")

IST = datetime.timedelta(hours=5, minutes=30)
OPEN_MIN = 9 * 60 + 15
LAST_SLOT = 74
STRIKE_WIDTH = 5            # ATM +/- 5 strikes: rules only trade within 1.5 steps of the signal-time index price,
                            # the extra strikes cover the index drifting away from the morning reference price.
HIST_PAUSE_S = 0.4          # Kite historical API limit: 3 requests/second
HIST_LOOKBACK_DAYS = 8      # enough calendar days to contain the previous trading session


# ---------------------------------------------------------------------------------------------- helpers
def to_ist_naive(dt):
    """Any datetime from kiteconnect -> naive IST. tz-aware: converted. Naive: assumed to be IST already."""
    if dt.tzinfo is None:
        return dt
    off = dt.utcoffset()
    return (dt - off + IST).replace(tzinfo=None)


def tick_time_to_ist(dt):
    """Timestamps inside KiteTicker packets are built with datetime.fromtimestamp() = NAIVE machine-local time.
    mktime() is its exact inverse, so this is correct whatever timezone the VM runs in."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return to_ist_naive(dt)
    epoch = time.mktime(dt.timetuple())
    return datetime.datetime.utcfromtimestamp(epoch) + IST


def slot_of_time(dt):
    m = dt.hour * 60 + dt.minute
    s = (m - OPEN_MIN) // 5
    return s if 0 <= s <= LAST_SLOT else None


def norm_row(r):
    """kiteconnect returns typed dicts; instruments.py reads CSV-style strings."""
    return dict((k, "" if v is None else str(v)) for k, v in r.items())


def parse_request_token(text):
    """Accept the bare token or the whole redirect URL (...?request_token=XXXX&action=login&status=success)."""
    text = text.strip()
    m = re.search(r"request_token=([A-Za-z0-9]+)", text)
    return m.group(1) if m else text


# ---------------------------------------------------------------------------------------------- feed
class KiteFeed(Feed):
    """Thread-safe by construction: on_tick is the daemon's queue.put."""
    needs_restart = True        # Twisted's reactor cannot be restarted -> the daemon restarts the process after EOD

    def __init__(self, api_key, access_token, token_to_key, index_tokens, ticker_factory=None):
        self.api_key, self.access_token = api_key, access_token
        self.token_to_key = dict(token_to_key)
        self.index_tokens = set(index_tokens)
        self.handler = None
        self.ticker = None
        self.ticker_factory = ticker_factory
        self.sample_logged = set()
        self.packets = 0
        self.errors = 0

    # Feed interface (symbols are ignored: tokens were fixed at construction from the same plan)
    def subscribe(self, symbols):
        self.symbols = list(symbols)

    def set_handler(self, on_tick):
        self.handler = on_tick

    def start(self):
        if self.ticker_factory is not None:
            t = self.ticker_factory(self.api_key, self.access_token)
        else:
            from kiteconnect import KiteTicker
            t = KiteTicker(self.api_key, self.access_token)
        self.ticker = t
        tokens = sorted(self.token_to_key)

        def on_connect(ws, response):
            log.info("kite ticker connected, subscribing %d tokens in full mode", len(tokens))
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)

        def on_ticks(ws, ticks):
            self.handle_ticks(ticks)

        def on_close(ws, code, reason):
            log.warning("kite ticker closed: %s %s", code, reason)

        def on_error(ws, code, reason):
            self.errors += 1
            log.error("kite ticker error: %s %s", code, reason)

        t.on_connect, t.on_ticks, t.on_close, t.on_error = on_connect, on_ticks, on_close, on_error
        t.connect(threaded=True)

    def stop(self):
        if self.ticker is not None:
            try:
                self.ticker.close()
            except Exception as e:
                log.warning("ticker close: %r", e)
        self.ticker = None

    # Packet -> Tick
    def handle_ticks(self, ticks):
        for t in ticks:
            self.packets += 1
            tk = self.convert(t)
            if tk is not None and self.handler is not None:
                self.handler(tk)

    def convert(self, t):
        token = t.get("instrument_token")
        key = self.token_to_key.get(token)
        if key is None:
            return None
        kind = "index" if token in self.index_tokens else "option"
        if kind not in self.sample_logged:                 # one line per kind -> verify real tick keys on day 1
            self.sample_logged.add(kind)
            log.info("first %s tick: keys=%s sample=%s", kind, sorted(t.keys()), dict((k, t[k]) for k in sorted(t) if k != "depth"))
        price = t.get("last_price")
        if price is None:
            return None
        if kind == "index":
            ts = t.get("exchange_timestamp")
            vol = None
        else:
            ts = t.get("last_trade_time") or t.get("exchange_timestamp")
            vol = t.get("volume_traded", t.get("volume"))
            if vol is None:
                return None
        ts = tick_time_to_ist(ts) if ts is not None else ist_now()
        return Tick(key, ts, float(price), vol)


# ---------------------------------------------------------------------------------------------- provider
class KiteProvider(object):
    def __init__(self, cfg, kite=None, ticker_factory=None, clock=ist_now, sleep=time.sleep, width=STRIKE_WIDTH):
        self.cfg = cfg
        self.api_key = cfg.env.get("KITE_API_KEY", "")
        self.api_secret = cfg.env.get("KITE_API_SECRET", "")
        self._kite = kite
        self.ticker_factory = ticker_factory
        self.clock = clock
        self.sleep = sleep
        self.width = width
        self.token_path = os.path.join(cfg.state, "kite_token.json")
        self.tokens = {}            # symbol key -> instrument_token (set in morning, used by history)
        self.verified_day = None

    # ---------------------------------------------------------------- kite client
    def kite(self):
        if self._kite is None:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self.api_key)
        return self._kite

    # ---------------------------------------------------------------- token
    def _load_token(self):
        try:
            with open(self.token_path) as f:
                return json.load(f)
        except (IOError, ValueError):
            return None

    def _save_token(self, access_token, user, day):
        d = os.path.dirname(self.token_path)
        if not os.path.isdir(d):
            os.makedirs(d, 0o700)
        tmp = self.token_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"access_token": access_token, "user": user, "day": day}, f)
        os.replace(tmp, self.token_path)

    def token_ok(self):
        """Saved for today AND (once per day) accepted by the API. Kite tokens die ~06:00 IST next morning."""
        if not self.api_key:
            return False
        tok = self._load_token()
        today = self.clock().strftime("%Y-%m-%d")
        if not tok or tok.get("day") != today or not tok.get("access_token"):
            return False
        if self.verified_day == today:
            return True
        k = self.kite()
        k.set_access_token(tok["access_token"])
        try:
            k.profile()
        except Exception as e:
            log.warning("kite profile check failed: %r", e)
            return False
        self.verified_day = today
        return True

    def login(self, request_token):
        """Exchange a request_token. Returns (ok, message, user_id). The token is saved ONLY if the Zerodha user id
        matches KITE_USER_ID (when configured), so a stranger cannot log the bot into another account."""
        if not self.api_key or not self.api_secret:
            return False, "Kite API key/secret are not configured (run: python -m trader.setup_kite).", ""
        try:
            data = self.kite().generate_session(request_token, api_secret=self.api_secret)
        except Exception as e:
            return False, "Kite login failed: %s (each login link works once; use /login for a new one)." % type(e).__name__, ""
        user = str(data.get("user_id", ""))
        want = self.cfg.env.get("KITE_USER_ID", "").strip().upper()
        if want and user.upper() != want:
            log.warning("login rejected: unexpected user id")
            return False, "Login rejected: wrong Zerodha account (expected %s)." % want, user
        at = data["access_token"]
        self.kite().set_access_token(at)
        today = self.clock().strftime("%Y-%m-%d")
        self._save_token(at, user, today)
        self.verified_day = today
        return True, "Kite login OK for %s (valid until ~06:00 tomorrow)." % (user or "user"), user

    def exchange_token(self, text):
        """Controller hook for /token <request_token | redirect URL> (fallback when the web receiver is down)."""
        ok, msg, _ = self.login(parse_request_token(text))
        return msg

    def login_url(self, state=None):
        url = self.kite().login_url()
        if state:
            url += "&redirect_params=" + urllib.parse.quote("state=" + state, safe="")
        return url

    def config_text(self):
        if not self.api_key:
            return "kite: not configured"
        try:
            return "kite login: %s" % self.login_url()
        except Exception as e:
            return "kite login url unavailable: %r" % e

    def vix(self):
        """India VIX last price (data only, never used by the rules). None if unavailable."""
        k = self.kite()
        k.set_access_token(self._load_token()["access_token"])
        q = k.quote(["NSE:INDIA VIX"]).get("NSE:INDIA VIX") or {}
        px = q.get("last_price")
        return float(px) if px else None

    # ---------------------------------------------------------------- morning
    def morning(self, day):
        now = self.clock()
        k = self.kite()
        tok = self._load_token()
        k.set_access_token(tok["access_token"])
        today = datetime.datetime.strptime(day, "%Y-%m-%d").date()

        q = k.quote([I.INDEXES[n].spot_key for n in sorted(I.INDEXES)])
        specs, all_keys, index_tokens = [], {}, []
        hist_jobs = []                                  # (key, token)
        for name in sorted(I.INDEXES):
            cfg = I.INDEXES[name]
            qi = q.get(cfg.spot_key)
            if qi is None:
                raise RuntimeError("quote missing for %s" % cfg.spot_key)
            o = (qi.get("ohlc") or {})
            prev_close = float(o.get("close") or 0)
            ref = float(o.get("open") or 0) or float(qi.get("last_price") or 0) or prev_close
            if prev_close <= 0 or ref <= 0:
                raise RuntimeError("no price/close for %s" % cfg.spot_key)
            rows = [norm_row(r) for r in k.instruments(cfg.exchange)]
            I.cache_dump(rows, self.cfg.instruments, today)       # tokens of expired contracts stay resolvable
            expiry, atm, sel = I.plan(rows, name, today, ref, width=self.width)
            opts = [OptionSpec(c.key, c.strike, c.opt, c.lot_size) for c in sel]
            specs.append((IndexSpec(name, cfg.spot_key, cfg.step, opts), prev_close))
            all_keys[cfg.spot_key] = int(qi["instrument_token"])
            index_tokens.append(int(qi["instrument_token"]))
            for c in sel:
                all_keys[c.key] = c.token
            log.info("%s: ref %.2f prev_close %.2f expiry %s atm %s, %d options", name, ref, prev_close, expiry, atm, len(sel))
        self.tokens = dict(all_keys)

        hist = self._fetch_hist(sorted(all_keys), now, today)         # {key: (seed_closes, [(slot,o,h,l,c)])}
        indexes = []
        for spec, prev_close in specs:
            seeds = dict((s, hist[s][0]) for s in [spec.symbol] + [o.symbol for o in spec.options])
            indexes.append((spec, prev_close, seeds))
        backfill = self._backfill(hist, now)

        feed = KiteFeed(self.api_key, tok["access_token"], dict((v, kk) for kk, v in all_keys.items()),
                        index_tokens, self.ticker_factory)
        return {"indexes": indexes, "backfill": backfill, "feed": feed}

    # ---------------------------------------------------------------- historical
    def _candles(self, key, frm, to):
        rows = self.kite().historical_data(self.tokens[key], frm, to, "5minute")
        out = []
        for r in rows:
            d = to_ist_naive(r["date"])
            out.append((d, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
        return out

    def _fetch_hist(self, keys, now, today):
        """Per key: (closes of the previous session [seed], today's [(slot,o,h,l,c)] sorted)."""
        frm = datetime.datetime.combine(today - datetime.timedelta(days=HIST_LOOKBACK_DAYS), datetime.time(9, 15))
        to = datetime.datetime.combine(today, datetime.time(15, 30))
        res = {}
        for key in keys:
            cs = self._candles(key, frm, to)
            self.sleep(HIST_PAUSE_S)
            prev_days = sorted(set(d.date() for d, _, _, _, _ in cs if d.date() < today))
            seed = []
            if prev_days:
                last = prev_days[-1]
                seed = [c for d, _, _, _, c in cs if d.date() == last and slot_of_time(d) is not None]
            bars = {}
            for d, o, h, l, c in cs:
                if d.date() == today and slot_of_time(d) is not None:
                    bars[slot_of_time(d)] = (o, h, l, c)
            res[key] = (seed, sorted((s,) + b for s, b in bars.items()))
        return res

    def _backfill(self, hist, now):
        """Completed bars of today (slot end <= now - 3 s), holes filled flat like the live BarBuilder does,
        ordered by slot then symbol (the engine needs slot order within each symbol)."""
        base = datetime.datetime.combine(now.date(), datetime.time(9, 15))
        done = -1
        for s in range(LAST_SLOT + 1):
            if base + datetime.timedelta(minutes=5 * (s + 1)) <= now - datetime.timedelta(seconds=3):
                done = s
        rows = []
        if done < 0:
            return rows
        for key in sorted(hist):
            seed, bars = hist[key]
            by = dict((s, (o, h, l, c)) for s, o, h, l, c in bars)
            last_c = seed[-1] if seed else None
            for s in range(done + 1):
                b = by.get(s)
                if b is None:
                    if last_c is None:
                        continue
                    b = (last_c, last_c, last_c, last_c)
                last_c = b[3]
                rows.append((key, s, b[0], b[1], b[2], b[3]))
        rows.sort(key=lambda r: (r[1], r[0]))
        return rows

    def history(self, day, symbols):
        today = datetime.datetime.strptime(day, "%Y-%m-%d").date()
        frm = datetime.datetime.combine(today, datetime.time(9, 15))
        to = datetime.datetime.combine(today, datetime.time(15, 30))
        out = {}
        for sym in symbols:
            if sym not in self.tokens:
                continue
            bars = []
            for d, o, h, l, c in self._candles(sym, frm, to):
                s = slot_of_time(d)
                if s is not None:
                    bars.append({"slot": s, "O": o, "H": h, "L": l, "C": c})
            self.sleep(HIST_PAUSE_S)
            out[sym] = bars
        return out
