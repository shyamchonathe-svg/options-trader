# Runbook

## Where things are
- VM `trader-1` (GCP e2-micro, Ubuntu 22.04), user `shyamchonathe`. Static IP 34.70.191.30, DuckDNS `shyam-trader.duckdns.org`.
- Code: `~/trader/releases/<version>/`, symlink `~/trader/current`. Venv `~/trader/venv`.
- Secrets: `~/trader/secrets/trader.env` (mode 0600; Telegram, Kite key/secret/user id). NEVER in git or chat.
- State: `~/trader/state/` (trader.db, exports, instruments).
- Service: `trader.service` (+ `trader-watchdog` timer). Caddy proxies the login callback to 127.0.0.1:8001.

## Daily routine
1. 08:30-09:12 tap the Kite login link sent on Telegram. Done before 09:15 = live paper day; else DATA_ONLY.
2. 16:00 read the day report. Fridays also include `/compare`.
3. Anything odd: `/status`, `/health`, `/logs 20`.

## Telegram commands
Read-only: /status /health /positions /signals /why /trades /summary /compare /risk /bars /config /logs /replay /export /menu.
Control: /pause /resume /stop /flat /restart /note /ack. Risk: /set. Live (code + PIN): /mode /arm /disarm.
Login: /login /token /recover. Days: /skip /unskip /holiday YYYY-MM-DD.

## Deploying a release
Preferred once the VM has the git clone: `cd ~/trader/repo && git pull && bash tools/release.sh vX.Y.Z` (see docs/NEW_VM_SETUP.md).
Fallback (no git access) - chunk paste:
Lab: `cd live && BUNDLE_CHUNK=1900 python3 tools/bundle.py HEAD` -> `deploy/out/<version>/`.
VM: paste `00_prepare.txt`, all `chunk_NN.txt` in order, then `99_install.txt` (verifies sha256, unpacks, runs tests),
then `sudo systemctl restart trader.service`. Roll back: `ln -sfn ~/trader/releases/<old> ~/trader/current` and restart.

## Operations
- Logs: `journalctl -u trader.service -n 50 --no-pager`. Status: `sudo systemctl status trader.service`.
- Data backup: `trader-backup.timer` runs `tools/backup_data.sh` at 16:30 Mon-Fri. It exports each day's bars/signals/trades/events (never `kv`, which holds the token) as CSV.gz to branch `data-backup` of the private GitHub repo. Manual run / re-run a day: `bash ~/trader/current/tools/backup_data.sh 2026-11-18`. Restore = read the CSVs; `trader.db` itself is not stored in git. Secrets (`trader.env`, PIN) are NOT backed up: keep them in a password manager.
- End-of-day job (`trader-eod.timer`, Mon-Fri 18:35 and 21:00, separate from trading, low priority, never trades): downloads the exchange files to `~/trader/data/raw/<day>/` (`tools/bhavcopy.py`), snapshots the live DB read-only (token removed), runs the shadow research (`tools/research_run.py --grid`) to `~/trader/reports/research_<day>.txt` (+ `research_latest.txt`), re-exports the day, and pushes the report to branch `data-backup` under `research/`. Manual run: `bash ~/trader/current/tools/eod_research.sh [YYYY-MM-DD]`; check: `systemctl list-timers | grep trader`, `journalctl -u trader-eod -n 40 --no-pager`.
- Research rule: formulas are discovered on the research days and only trusted if they also hold on the live (exact) days; nothing enters `rules_v3.py` without that. A new rule set is a new version (v4).
- Rotate Kite secret: Kite developer console, then `python -m trader.setup_kite` on the VM.
- Kite Connect plan renews 18 Dec (credits). Orders will need the static IP registered with Kite (December).
- Reminders live in `state/reminders.txt` as `YYYY-MM-DD text`. Holidays add via `/holiday` or `state/holidays.txt`.
- Yearly: add the next year's NSE holidays in `trader/holidays.py` (reminder fires 20 Dec).

## Recovery
- Service down: `sudo systemctl restart trader.service`; the daemon rebuilds the day from the DB and history.
- Login missed: `/login`; late login backfills bars and simulates missed trades as `late-sim`.
- Lost the VM: rebuild from the repo, restore `trader.db`, recreate `trader.env`, rerun `setup_telegram`/`setup_kite`.

## Pending (Phase 2, December)
Order layer (SL and target placed at the broker, order polling, restart reconciliation, static IP), UI 2.0, trailing exit as v4 only after ~50 paper trades.
