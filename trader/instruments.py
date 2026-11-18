"""Daily instrument selection: nearest weekly expiry + ATM +/- N strikes.

Symbols and tokens always come from the Kite instrument dump, never built by hand.
Pure functions (no network): the Kite adapter downloads the dump, this module reads it.
Python 3.6 compatible.
"""
import csv
import datetime
import os
from collections import namedtuple

# exchange/name = where the options live; step = strike spacing;
# spot_key = quote key for the index; index_symbol/index_exchange = index tick symbol
IndexCfg = namedtuple("IndexCfg", "name exchange step spot_key index_exchange index_symbol")

INDEXES = {
    "NIFTY": IndexCfg("NIFTY", "NFO", 50, "NSE:NIFTY 50", "NSE", "NIFTY 50"),
    "SENSEX": IndexCfg("SENSEX", "BFO", 100, "BSE:SENSEX", "BSE", "SENSEX"),
}

Contract = namedtuple("Contract", "key symbol token exchange name strike opt expiry lot_size")


class InstrumentError(Exception):
    pass


def _d(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d").date()


def load_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def option_contracts(rows, name):
    """All CE/PE contracts for an index name (exact match; NIFTYNXT50 etc. excluded)."""
    out = []
    for r in rows:
        if r.get("name") != name or r.get("instrument_type") not in ("CE", "PE"):
            continue
        if not r.get("expiry"):
            continue
        out.append(Contract(
            key="%s:%s" % (r["exchange"], r["tradingsymbol"]),
            symbol=r["tradingsymbol"], token=int(r["instrument_token"]),
            exchange=r["exchange"], name=name, strike=float(r["strike"]),
            opt=r["instrument_type"], expiry=_d(r["expiry"]),
            lot_size=int(r["lot_size"])))
    return out


def pick_expiry(contracts, today):
    """Nearest expiry on or after today (expiry day itself still counts)."""
    exps = sorted(set(c.expiry for c in contracts if c.expiry >= today))
    if not exps:
        raise InstrumentError("no expiry on/after %s" % today)
    return exps[0]


def atm_strike(spot, step):
    return int(round(spot / float(step))) * step


def select_strikes(contracts, expiry, spot, step, width=1):
    """Contracts for ATM-width..ATM+width, both CE and PE. Raises if any is missing."""
    atm = atm_strike(spot, step)
    idx = dict(((c.strike, c.opt), c) for c in contracts if c.expiry == expiry)
    sel, missing = [], []
    for k in range(-width, width + 1):
        s = atm + k * step
        for opt in ("CE", "PE"):
            c = idx.get((float(s), opt))
            if c is None:
                if abs(k) <= 2:                 # the strikes that matter must exist; far wings may be unlisted
                    missing.append("%s%s" % (s, opt))
            else:
                sel.append(c)
    if missing:
        raise InstrumentError("missing in dump for expiry %s: %s" % (expiry, ",".join(missing)))
    return atm, sel


def plan(rows, index_name, today, spot, width=1):
    """One-call helper: (expiry, atm, [Contract...]) for an index."""
    cfg = INDEXES[index_name]
    cs = option_contracts(rows, cfg.name)
    expiry = pick_expiry(cs, today)
    atm, sel = select_strikes(cs, expiry, spot, cfg.step, width)
    return expiry, atm, sel


def cache_dump(rows, cache_dir, day):
    """Save only the option rows we may need later, dated, so expired tokens stay resolvable.
    Returns the path written (one file per day per exchange)."""
    keep = [r for r in rows if r.get("name") in INDEXES and r.get("instrument_type") in ("CE", "PE")]
    if not keep:
        raise InstrumentError("dump has no NIFTY/SENSEX options; not caching")
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir)
    exch = keep[0]["exchange"]
    path = os.path.join(cache_dir, "%s_%s.csv" % (day.isoformat(), exch))
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(keep[0].keys()))
        w.writeheader()
        w.writerows(keep)
    os.replace(tmp, path)
    return path
