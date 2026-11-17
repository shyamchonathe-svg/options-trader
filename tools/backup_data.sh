#!/bin/bash
# Daily trade-data backup to the PRIVATE GitHub repo, branch `data-backup` (separate, orphan history; never mixed with code).
# Runs on the VM from a systemd timer (16:30 Mon-Fri) or by hand:  bash ~/trader/current/tools/backup_data.sh [YYYY-MM-DD]
# Exports bars/signals/trades/events (NOT kv: it holds the access token) from the live DB, read-only.
set -e
DAY="${1:-$(date +%F)}"
CODE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$CODE"
CLONE="$HOME/trader/databackup"
REMOTE="git@github.com:shyamchonathe-svg/options-trader.git"
if [ ! -d "$CLONE/.git" ]; then
  git clone --quiet "$REMOTE" "$CLONE"
fi
cd "$CLONE"
git fetch --quiet origin
if git rev-parse -q --verify origin/data-backup >/dev/null; then
  git checkout -q -B data-backup origin/data-backup
else
  git checkout -q --orphan data-backup
  git rm -rfq . 2>/dev/null || true
  printf '# Trade data backup (derived data only: bars, signals, trades, events). One folder per day.\n' > README.md
  git add README.md
fi
"$HOME/trader/venv/bin/python" -m trader.backup --out "$CLONE/data" --day "$DAY"
git add data README.md
if git diff --cached --quiet; then echo "nothing new to back up"; exit 0; fi
git -c user.name="trader-1" -c user.email="trader-1@localhost" commit -q -m "data $DAY"
git push -q origin data-backup
echo "pushed data-backup $DAY"
