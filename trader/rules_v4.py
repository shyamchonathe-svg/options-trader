"""Strategy v4 = v3 entry rules (rules_v3, unchanged) + a VIX regime that sets target, maximum hold and trades per day.
Pure functions.  Python 3.6 compatible.

India VIX at the 09:15 open fixes the regime for the whole day (the journal convention, 19 Nov 2026 decision):
  below 12          no trades (poor R:R)
  12 to 15           target 4R, hold up to 12 candles (60 min), up to 2 trades per index
  above 15          target 2R, hold up to 6 candles (30 min), up to 2 trades per index (a new one only after the previous exits)
  unknown / late    v3 settings (3R, 12 candles, 1 trade) - a VIX data failure never blocks trading
Extra day filter: VIX down more than 5% from its open by 09:30 -> no trades that day.
Entry, stop, midday and gap filters are exactly rules_v3; the strike must be the nearest one (ATM_MAX_STEPS, v3 allowed 1.5 steps).
"""
RULES_VERSION = "v4.0"
VIX_LOW = 12.0
VIX_HIGH = 15.0
VIX_FALL = 0.05
ATM_MAX_STEPS = 0.5      # v4: only the nearest strike (within half a strike step of the index at the entry candle's open)

V3_DEFAULT = dict(name="unknown", trade=True, rr=3.0, hold=12, max_trades=1, version="v3.0")


def regime(vix_open):
    if not vix_open:
        return dict(V3_DEFAULT)
    if vix_open < VIX_LOW:
        return dict(name="low", trade=False, rr=3.0, hold=12, max_trades=0, version=RULES_VERSION)
    if vix_open <= VIX_HIGH:
        return dict(name="mid", trade=True, rr=4.0, hold=12, max_trades=2, version=RULES_VERSION)
    return dict(name="high", trade=True, rr=2.0, hold=6, max_trades=2, version=RULES_VERSION)


def vix_fell(vix_open, vix_0930):
    """True when VIX is more than 5% below its open at 09:30."""
    return bool(vix_open and vix_0930 and (vix_0930 / float(vix_open) - 1.0) < -VIX_FALL)


def describe(reg, vix_open, fell=False):
    """Plain-English one-liner for the day (sent once)."""
    if reg["name"] == "unknown":
        return "VIX not available this morning: using the standard settings (3R target, 60 min hold, 1 trade per index)."
    head = "India VIX opened at %.2f. " % vix_open
    if not reg["trade"]:
        return head + "Below 12 is a poor-reward zone: NO trades today."
    if fell:
        return head + "VIX then fell more than 5%% by 09:30: NO trades today."
    kind = "High-volatility day" if reg["name"] == "high" else "Normal-volatility day"
    return head + "%s: target %gR, hold at most %d min, up to %d trade(s) per index." % (
        kind, reg["rr"], reg["hold"] * 5, reg["max_trades"])
