# Architecture (as built, Phase 1)

One Python process (`python -m trader.main`, systemd `trader.service`) on a GCP e2-micro. SQLite is the spine.
Every loop: `daemon.step(now)` + a 1-second Telegram long-poll. Kite ticks arrive from a feed thread via a queue.
Python 3.6-compatible syntax (lab) and 3.10 (VM). Dependencies: stdlib + kiteconnect + requests. No pandas.

## Data flow
Kite ticks -> `feed.TradeFilter` -> `candles.BarBuilder` (5-min bars, slot 0 = 09:15 ... slot 74 = 15:25)
-> `store` (bars, signals, trades, events, kv) and `engine.Engine` -> `rules_v3` -> paper trade -> `notify` -> Telegram.

## Modules (trader/)
| Module | Role |
|---|---|
| `rules_v3.py` | PURE and FROZEN strategy: hammer pattern, EMA10/20 direction, ATM filter, gap filter, midday block, stop, 3R target, 12-bar time exit. Changing behaviour = a new version (v4), never an edit. |
| `engine.py` | Paper engine: entries at next-bar open, one position per index, stop/target/time exit, `accepting` flag and `block_reason`. |
| `compare.py` | Replays stored trades under alternative exits (A..E) for the v4 evidence. Read-only, never trades. |
| `candles.py`, `feed.py`, `pipeline.py` | Tick filtering and exact 5-min bar building. |
| `instruments.py` | Daily instrument dump -> today's contracts (weekly expiry, ATM +/- strikes; NFO for Nifty, BFO for Sensex). |
| `store.py` | SQLite (WAL): bars, signals (rejected/missed/traded/dropped), trades, events, kv. |
| `state.py` | Mode, armed/paused/stopped flags, risk limits, `trading_blocked`. |
| `risk.py`, `pin.py` | Risk limits; PIN hash and lockout for live commands. |
| `daemon.py` | Daily schedule: login prompts 08:30/08:40/08:50/09:05/09:12, ready 09:10, engine, EOD 15:31, report 16:00, post-close recovery, VIX capture, holidays/skip, reminders. |
| `login.py`, `main.py` | Hands-free Kite login: Telegram link -> Caddy -> local receiver 127.0.0.1:8001 -> token. No login by 09:15 => DATA_ONLY day. |
| `control.py` | Telegram command parser (pure: text in, replies out). Dangerous commands need a one-time code; live also needs PIN. |
| `bot.py`, `tg_api.py` | Polling loop, inline button menu (read-only commands only), Telegram client. |
| `notify.py` | Message formatting, day report (trades, entry/stop/target/exit/R, run-up peak, no-trade reasons). |
| `holidays.py`, `reminders.py` | NSE holiday list (2026 verified) and dated reminders. |
| `watchdog.py`, `recon.py`, `export.py`, `replay.py` | External watchdog, end-of-day reconciliation, CSV export, replay. |
| `adapters/kite_adapter.py` | ALL Kite calls live here only (cannot be run from the lab). |

## Daily timeline (IST)
08:30 login prompts -> 09:15 cutoff (no login = DATA_ONLY) -> 09:15-15:25 bars/signals/paper trades ->
15:31 EOD reconcile + export -> 15:50 reminders -> 16:00 day report. A late login triggers post-close recovery
(`late-sim` trades, clearly labelled, excluded from real results).

## Safety model
- Live trading is OFF: needs `LIVE_ENABLED=1`, a PIN, a confirmation code and `/arm live` every day; auto-disarm 15:45 and on restart.
- Strategy rules are not editable from Telegram; `/set` changes only whitelisted risk limits.
- Only the whitelisted chat id is answered. Secrets are never logged or committed.
- Stale/gapped data => no new entries, alert, keep managing open positions.

## Data
`~/trader/state/trader.db` (SQLite), `exports/`, `instruments/`, `holidays.txt`, `reminders.txt`. Kept: candles, signals, trades
(derived data). Raw ticks are not retained.

## Tests
`python3 -m unittest discover -s tests -t .` (126 tests; 7 fixture-dependent tests skip on the VM). `tests/lab_replay_check.py`
(lab only) must print PASS: it guards that rules_v3 reproduces the known research trades.
