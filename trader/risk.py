"""Entry guard consulted by the Engine just before a trade is taken.
Shadow mode: only pause/stop apply (so the strategy is measured unchanged).
Live mode: pause/stop plus max trades, daily loss cap and halt after consecutive stop-outs."""


class RiskGuard(object):
    def __init__(self, store, state):
        self.store = store
        self.state = state

    def allow_entry(self, day, mode):
        st = self.state
        if st.stopped:
            return False, "stopped"
        if st.paused:
            return False, "paused"
        if mode != "live":
            return True, ""
        r = st.risk
        closed = self.store.closed_trades_for_day(day)
        n_today = len(self.store.trades_for_day(day))
        if n_today >= r["max_trades_per_day"]:
            return False, "max-trades"
        if sum(t["r_mult"] or 0.0 for t in closed) <= -float(r["daily_loss_R"]):
            return False, "daily-loss"
        k = int(r["halt_after_stops"])
        if len(closed) >= k and all(t["exit_reason"] == "stop" for t in closed[-k:]):
            return False, "halt-after-stops"
        return True, ""
