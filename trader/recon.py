"""End-of-day reconciliation: live-built bars vs the exchange's historical bars. Differences mean the tick path
missed or mis-ordered trades; they never change a trade after the fact, they only raise an alert."""
TOL = 0.051    # one tick of 0.05 (+rounding)


def reconcile(store, day, hist):
    """hist: {symbol: [{"slot","O","H","L","C"}...]}. Returns (compared, bad, max_diff)."""
    n = bad = 0
    mx = 0.0
    for sym in sorted(hist):
        live = dict((b["slot"], b) for b in store.get_bars(day, sym))
        for h in hist[sym]:
            store.put_bar(day, sym, h["slot"], h["O"], h["H"], h["L"], h["C"], 0, "hist")
            lb = live.get(h["slot"])
            if lb is None or lb.get("n", 0) == 0 and lb.get("src") == "flat":
                continue
            d = abs(lb["c"] - h["C"])
            n += 1
            store.db.execute("INSERT INTO recon VALUES(?,?,?,?,?,?)", (day, sym, h["slot"], lb["c"], h["C"], d))
            mx = max(mx, d)
            if d > TOL:
                bad += 1
    store.db.commit()
    return n, bad, mx
