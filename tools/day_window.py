#!/usr/bin/env python3
"""Candle-by-candle option + index details and the failed v3 conditions for one research day and time window.
Usage: python3 tools/day_window.py 20261027 13:00 14:30"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from trader import rules_v3 as R  # noqa: E402
from trader import analyze as A  # noqa: E402


class Ser(object):
    def __init__(self, by, e10, e20):
        self.by = by
        self.e10 = dict(enumerate(e10)) if isinstance(e10, list) else e10
        self.e20 = dict(enumerate(e20)) if isinstance(e20, list) else e20


class FakeStore(object):
    def trades_for_day(self, day):
        return []


class FakeDay(object):
    def __init__(self, ds):
        self.day, self.store, self.source = ds["day"], FakeStore(), "hist"
        self.series, self.prev_close = {}, {}

        def feats(s):
            seq = list(s["seed"])
            npre = len(seq)
            by = {}
            for k in range(s["n"]):
                b = s["bars"].get(str(k))
                if b is not None:
                    by[k] = {"O": b[0], "H": b[1], "L": b[2], "C": b[3]}
                seq.append(b[3] if b is not None else (seq[-1] if seq else 0))
            return Ser(by, R.ema(seq, 10)[npre:], R.ema(seq, 20)[npre:])
        self.name = ds["index"]
        self.series[A.INDEX_KEY[ds["index"]]] = feats(ds["idx"])
        if ds["prev_close"]:
            self.prev_close[A.INDEX_KEY[ds["index"]]] = ds["prev_close"]
        self.opts = {}
        for n, o in ds["opts"].items():
            sym = "X:%s%s%s" % (ds["index"], n.split("_")[1][:5], n[-2:])      # NIFTY22700PE
            self.series[sym] = feats(o)
            self.opts[sym] = n


def main(key, t0, t1):
    ds = json.load(open(os.path.join(HERE, "..", "tests", "fixtures", "replay_days.json")))[key]
    d = FakeDay(ds)
    a, b = A.slot_of(t0), A.slot_of(t1)
    ix = d.series[A.INDEX_KEY[d.name]]
    print("%s %s   gap/prev close: %s   candles %s-%s" % (ds["day"], d.name, ds["prev_close"] or "not recorded", t0, t1))
    for sym in sorted(d.opts):
        s = d.series[sym]
        print("\n" + "=" * 118)
        print("%s   (index = %s)" % (d.opts[sym], d.name))
        print("time  | OPTION  open     high      low    close   EMA10   EMA20 | INDEX close   EMA10    EMA20  trend | result")
        for i in range(a, b + 1):
            if i not in s.by:
                print("%s | no option candle stored" % R.tstr(i))
                continue
            x = s.by[i]
            c = A.check(d, sym, i)
            ic = ix.by.get(i)
            dirn = R.index_direction(ic["C"], ix.e10[i], ix.e20[i]) if ic else None
            bad = [it["label"] for it in c["items"] if not it["ok"]]
            if c["signal_ok"] and c["sig"]:
                fb = [f["label"] for f in c["filters"] if not f["ok"]]
                res = "SIGNAL; " + ("filters ok -> TRADE" if not fb else "blocked: " + ", ".join(fb))
            else:
                res = "no: " + "; ".join(bad[:3])
            print("%s | %8.2f %8.2f %8.2f %8.2f %7.2f %7.2f | %9.2f %8.2f %8.2f %5s | %s" % (
                R.tstr(i), x["O"], x["H"], x["L"], x["C"], s.e10[i], s.e20[i],
                ic["C"] if ic else 0, ix.e10[i], ix.e20[i], dirn, res))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
