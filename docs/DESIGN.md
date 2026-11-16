# Hands-free weekly-options system (Nifty + Sensex) - DESIGN v0.1  (plan only, no code yet)

## 0. Why the first attempt failed (from its file list) -> rule for this one
- many *_bk.py / .broken / backup_code copies  -> git is the backup; one file per responsibility; no copies.
- debug_token_*.txt, latest_token.txt, kite_tokens/ in repo -> secrets NEVER in the repo (.env on VM only, chmod 600).
- "production-ready" docs written before anything was validated -> every layer has an acceptance test BEFORE the next starts.
- strategy, data, broker, risk and Telegram mixed together -> strategy is a pure module (rules_v3.py, done); everything else is an adapter around it.

## 1. Goal and non-goals
Goal: on the VM, every trading day with no manual work except one login:
  record bars -> evaluate v3 rules -> paper-trade signals -> report -> (later) place 1-lot orders with hard limits.
Non-goals now: changing the rules, optimising exits, multiple strategies, a UI, ML, other brokers.
Strategy changes are a separate track; infrastructure work must never alter rules_v3 behaviour (replay_check guards this).

## 2. Requirements
Functional
 F1 Build today's instrument list: current weekly expiry, ATM+-1 strikes (3 strikes x CE+PE = 6 contracts per index, 12 total + 2 index tokens). Re-centred on the index every bar close; a newly-ATM strike is back-filled from the historical API so its EMA is valid before it can signal.
 F2 Receive live ticks for the 2 indices + 12 option contracts.
 F3 Build exact 5-minute bars (09:15 slot 0 ... 15:25 slot 74) from exchange timestamps.
 F4 Seed EMA10/20 with the previous session's bars (research code did this) - needs historical API per contract.
 F5 At each bar close evaluate rules_v3 on every active option chart; store EVERY signal incl. rejected ones + reason.
 F6 Paper engine: entry = first price in next bar, stop/target/time-exit exactly as v3; one position per index.
 F7 Daily login by phone -> /token on Telegram -> access token stored; alert if missing by 08:45.
 F8 Telegram: /status /summary /stop /resume /token; push alerts (signal, entry, exit, error, feed down).
 F9 End of day: re-fetch the day's bars from the historical API, diff against live-built bars, log differences, export CSV, backup DB.
 F10 (phase 2) Live order layer behind the same interface as the paper engine.
Non-functional
 N1 1 GB RAM, e2-micro: stdlib + kiteconnect + requests only. No pandas.  SQLite (WAL).
 N2 Survives restarts mid-day: rebuilds today's bars from historical API + DB, no duplicate trades.
 N3 Fail-safe default: if data is stale/gapped/uncertain -> no new entries, alert, keep managing open positions.
 N4 Deterministic: same bars in => same signals out (replay == live).
 N5 Outbound HTTPS only (no inbound ports needed except SSH). Python 3.6-compatible syntax while dev is on the lab box.
Constraints
 C1 Kite code cannot run on the lab machine -> ALL Kite calls live in ONE file (kite_adapter.py); the rest is testable here.
 C2 Data terms: keep derived candles/signals/trades; keep raw ticks only in a short rolling buffer (get Zerodha written OK).
 C3 Static IP only matters for order placement; register VM IP only when going live (changeable once per week).
 C4 Kite subscription ~30 Nov; until then everything runs on replay.

## 3. Architecture (one process, small modules, SQLite as the spine)
 instruments.py  : daily instrument dump -> today's contract list (pure, testable with a saved dump)
 feed.py         : Feed interface { subscribe(tokens), on_tick(cb) }  impls: ReplayFeed (here), KiteFeed (kite_adapter)
 candles.py      : tick -> 5m bar builder; closes a bar when first tick of next slot arrives OR timer passes slot end +2s
 history.py      : backfill / seed / EOD reconcile via historical API (impl in kite_adapter; fake impl for tests)
 rules_v3.py     : DONE. signal_at / select_day_trades / simulate_exit (pure)
 engine.py       : on_bar_close -> rules_v3 -> signals; manages positions via Broker interface; enforces day limits
 broker.py       : Broker interface {enter, set_stop, exit, positions}; PaperBroker now, KiteBroker in phase 2
 store.py        : SQLite schema + tiny DAO (single writer)
 notify.py       : Telegram control plane (section 11): long-poll commands + push, outbound only
 auth.py         : token exchange from request_token, token file, expiry check
 runner.py       : wires the above; modes: replay | shadow | live ; the ONLY place mode is decided
 eod.py          : reconcile, export, backup, summary
 deploy/         : systemd unit(s), .env.example, install notes
Dependency direction: runner -> engine -> (rules_v3, broker, store). Nothing imports kite_adapter except runner.

## 4. Data model (SQLite)
 bars(day, symbol, slot, o,h,l,c, src['live'|'hist'], PRIMARY KEY(day,symbol,slot,src))
 signals(id, day, symbol, slot, side, status['taken'|'rejected'|'skipped'], reasons, entry,stop,target, rules_version, gap, dist)
 trades(id, signal_id, mode['paper'|'live'], qty, entry_t, entry_px, exit_t, exit_px, exit_reason, r_mult, pnl)
 events(ts, level, kind, msg)            -- feed up/down, reconnects, token, halts, commands
 health(ts, last_tick_ts, bars_built, lag_ms)
 recon(day, symbol, slot, live_c, hist_c, diff)  -- live vs historical bar differences
rules_version (e.g. 'v3.0') is stamped on every signal so the frozen test is auditable.

## 5. Daily timeline (IST)
 08:15 service starts (systemd), checks token -> if invalid, Telegram "send /token <request_token>"
 08:45 hard alert if still no token;  09:00 instruments + previous-session seed
 09:14 subscribe;  09:15-15:30 bars/signals/paper;  14:45 last entry;  15:25 last bar; 15:30 flat all open paper/live
 15:35 EOD: reconcile vs historical, export, backup, summary to Telegram; 15:45 stop feed

## 6. Failure modes -> behaviour
 websocket drops        : auto-reconnect w/ backoff; >30 s without ticks during market -> 'DATA_STALE': block entries, alert
 gap in a bar           : fill from historical API at next close; if cannot -> mark bar 'unsure', block signals using it
 process restarts       : reload today's bars from DB+API; open positions from DB (paper) / broker (live); never re-enter an existing signal id
 token expired mid-day  : alert; live mode: keep exchange-side SL, no new entries
 Telegram down          : system continues; alerts queue in events
 VM clock wrong         : NTP check at start; refuse to trade if skew > 2 s
 duplicate order risk   : idempotency key = day+symbol+slot; live: one order per key
 (live) daily loss cap, 1-lot cap, max trades/day, kill switch (/stop), exchange-side SL placed with entry, auto-halt on any mismatch

## 7. Test strategy (each layer has an acceptance test)
 T1 rules: replay_check.py reproduces the 11 known trades (DONE, must stay green).
 T2 candles: feed a synthetic tick stream -> bars equal expected; late/out-of-order ticks; slot boundaries; missing slot.
 T3 engine: replay saved days through ReplayFeed -> same signals as select_day_trades (live path == batch path).
 T4 store/restart: kill mid-day, restart, no duplicate trades/signals.
 T5 notify/auth: dry-run with a test bot and a fake token endpoint.
 T6 on VM after subscribing: record-only days, then compare live bars vs historical API (recon table) - target: zero close diffs on >99% of bars.
 T7 shadow (paper) for the rest of December; daily review of signals vs your own eye.
 Gate to live: >=50 shadow signals reviewed, recon clean, limits tested, you approve.

## 8. Phases
 P0 (16-22 Nov, lab)   instruments, candles, store, ReplayFeed, engine+PaperBroker, tests T1-T4
 P1 (23-29 Nov, lab)   notify/auth (against fakes), runner, eod, deploy files; end-to-end replay of all saved days
 P2 (30 Nov-)          subscribe; copy to VM by paste; KiteFeed/history impl; record-only; T6
 P3 (Dec)              shadow signals + paper trades + daily review (no money)
 P4 (late Dec)         KiteBroker + risk manager + exchange SL + kill switch; 1-lot test days
 P5                    go/no-go on live size after enough trades

## 9. Open decisions / unknowns (need answers before the relevant phase)
 Q1 Nifty expiry day (Mon vs Tue) - affects F1 + "expiry-day" behaviour.
 Q2 DECIDED: ATM+-1, re-centred every bar (v3 allows <=1.5 steps).
 Q3 Zerodha: derived-data storage / simulation on live feed OK?  SL vs SL-M for index options?  expired-contract history?
 Q4 Paper fill rule: first tick of next bar (default) vs bar open from historical -> pick one, keep both in DB.
 Q5 Max loss per day and per trade for the live phase (suggest 1 lot, 2R/day).
 Q6 Where does the repo live? (new PRIVATE repo, personal account, never the company GitHub)

## 10. Carried over from the first attempt's intent (added 15 Nov)
 - Telegram replay: /replay list, /replay <date> -> signals, trades, R for that day (runs the same engine on stored bars).
 - Daily archive: bars + signals + trades per day exported to CSV and kept (derived data only), so any day can be replayed later.
 - Risk manager (live phase, defaults to confirm): max trades/day, halt after 2 consecutive stop-outs, daily loss cap, auto-flat at 15:25.
 - Sizing: fixed 1 lot first; balance-based sizing only after the live gate is passed.
 - /risk command: shows today's counters and limits.
 - Secrets: .env on the VM only (chmod 600); .env.example in the repo.

## 11. Telegram control plane (added 15 Nov) - the bot is the operator console
Security
 - Only the whitelisted chat_id(s) are obeyed; everything else is ignored and logged.
 - Dangerous commands (/stop, /flat, /arm live, /set loosen, /restart) need a confirm step (inline button + 6-digit code shown in the bot).
 - Every command and its result is written to the events table (audit trail). Rate-limited.
 - Strategy rules (v3) are NOT editable from Telegram. Only risk/operations parameters, from a whitelist, with min/max bounds.
Read-only (always safe)
 /status    mode, armed/paused, feed state, token valid, last tick age, open positions, today P&L(R)
 /health    feed lag, bar gaps, clock skew, disk, memory, DB size, last reconcile result
 /positions open positions with entry, stop, target, bars held
 /signals [day]   every signal today incl. rejected + reason;   /why <HH:MM> [symbol]  why there was NO signal at that bar
 /trades [n]  /summary [day|week|all]  /risk (counters + limits)  /bars <symbol> [n] (last bars + EMA10/20)
 /config    current limits + rules_version;  /logs [n];  /replay list | <date>;  /export <day>
Control
 /pause     no NEW entries, keep managing open ones          /resume
 /stop      halt: no entries, close all positions, stay up (needs confirm)
 /flat      close all open positions now (needs confirm)
 /mode shadow|live   switch paper/live (live needs prior /arm live + confirm; only allowed after the P4 gate)
 /arm live | /disarm   explicit two-step arming; auto-disarms at 15:45 every day (live is never "left on")
 /token <request_token>   daily login;   /restart   restart the service (confirm)
 /set <param> <value>     whitelist only: max_trades_day, max_consec_sl, daily_loss_r, lots (<= hard cap in code), entry_cutoff
        tightening applies immediately; loosening needs confirm and applies from next session
 /note <text>   append to the day journal;   /ack   silence a repeating alert
Push alerts
 09:10 ready check (token ok, instruments ok, feed ok) | signal taken/rejected | entry | exit | stop hit | halt | feed stale | token missing
 15:45 daily summary | any ERROR | reconciliation differences | disk/memory low
Dead-man's switch
 If the VM or process dies, Telegram cannot tell you. Add a free external heartbeat (e.g. healthchecks.io ping every minute 09:00-15:40) that messages you if pings stop.

## 12. Decisions confirmed 15 Nov
 - Strikes: ATM+-1, re-centred each bar.   - Telegram control plane as section 11.
 - Crash recovery: small always-on helper service (separate from the trading process) so /restart works even if the main process is dead.
 - Live safety: /arm live and /mode live need confirm code AND a user-chosen PIN (stored hashed on the VM, never shown); 3 wrong PINs lock live commands until next day; live auto-disarms at 15:45 daily.
 - Build starts 16 Nov (P0). Daily chart/checklist routine continues in parallel.

## 13. Kite facts taken from the old repo's working code (verified in its saved dumps, 16 Nov)
 - kite.instruments("BFO") columns: instrument_token, exchange_token, tradingsymbol, name, last_price, expiry, strike, tick_size, lot_size, instrument_type(CE/PE/FUT), segment('BFO-OPT'), exchange.
 - Sensex weekly option symbol example: SENSEX2591180300CE = SENSEX + YY(25) + M(9) + DD(11) + strike(80300) + CE. Month is 1 digit for Jan-Sep and a letter for Oct/Nov/Dec (O/N/D) - DO NOT build symbols by hand: always look up name/expiry/strike/type in the dump.
 - Sensex index: exchange BSE, tradingsymbol SENSEX, instrument_token 265 (segment INDICES). Nifty options live in NFO (name NIFTY); Nifty index token to be read from the NSE dump (INDICES), not hardcoded.
 - Lot size in the Sept-2025 dump was 20 for Sensex; it changes -> always read lot_size from the dump each morning.
 - Old fetcher used kite.historical_data(token, from, to, interval) with "3minute"; we need "5minute". Old code downloaded the full instrument list per call; we cache it once per morning.
 - Old repo only did Sensex; Nifty (NFO) is new work here.

## 14. Kite API contract (from kite.trade docs, read 16 Nov) - what the code must respect
 WebSocket (wss://ws.kite.trade, python lib KiteTicker):
  - <=3000 instruments/connection, <=3 connections/key. We need 14 -> one connection.
  - Modes: ltp (price only) / quote (no time) / full (adds last_trade_time + exchange_timestamp + depth). Exchange
    time exists ONLY in 'full' -> subscribe in full. (Implemented: trader/feed.py)
  - A full packet arrives on any change incl. depth. Bars must be built from TRADES only: accept an option tick only
    when day volume increases; time-stamp with last_trade_time. Indices: no volume; use exchange_timestamp.
  - Prices come as paise integers on the wire; the python lib already converts to rupees.
  - Postbacks/order updates arrive as text frames (type order/error/message) on the same socket (use in P4).
  - Reconnect: re-subscribe and re-set mode in on_connect; first packet after reconnect only primes volume.
 Historical (GET /instruments/historical/:token/:interval):
  - interval '5minute'; candle label = bar START (09:15 = slot 0); record = [timestamp, o, h, l, c, volume].
  - Timestamps look like 2017-12-15T09:15:00+0530. Rate limit 3 req/s (we need ~14 per morning + back-fills).
  - Only LIVE contracts' tokens are returned by the instrument API; expired tokens cannot be looked up later ->
    CACHE the daily dump (filtered to NIFTY/SENSEX options) every morning, dated.
 Instruments (GET /instruments[/:exchange]):
  - Gzipped CSV regenerated once a day; fetch ~08:30; last_price in it is NOT live.
  - Tokens are reused by the exchange after expiry -> store/key by exchange:tradingsymbol, never by token alone.
 Quotes: /quote (500), /quote/ohlc and /quote/ltp (1000 each), 1 req/s. Keys are 'EXCHANGE:TRADINGSYMBOL'
  (e.g. BSE:SENSEX, NSE:NIFTY 50). Missing key = no data/expired -> always check key presence.
 Consequences already applied: feed.py TradeFilter; Tick(symbol=exchange:tradingsymbol); history back-fill repairs gaps.
 Still to verify ON THE VM (cannot test from the lab): real tick dict keys from KiteTicker in full mode, the NSE index
 tradingsymbol/token for Nifty, historical_data for a just-expired option token.
