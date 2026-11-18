#!/bin/bash
# End-of-day job, SEPARATE from trading (own systemd service, low priority, read-only on the live DB).
# Runs Mon-Fri 18:35 and again 21:00 (safe to repeat). By hand:  bash ~/trader/current/tools/eod_research.sh [YYYY-MM-DD]
#  1. download the day's exchange files (bhavcopy, index closes)           -> ~/trader/data/raw/<day>/
#  2. take a read-only snapshot of the live DB                              -> ~/trader/data/research/snapshot.db
#  3. run the shadow research (hammer / inside-candle grids) on snapshot    -> ~/trader/reports/research_<day>.txt
#  4. re-export the full day to the data-backup branch + push the report there (so it can be read from the lab)
# Nothing here can place or change a trade.
DAY="${1:-$(date +%F)}"
CODE="$(cd "$(dirname "$0")/.." && pwd)"
HOME_T="${TRADER_HOME:-$HOME/trader}"
PY="$HOME_T/venv/bin/python"
export PYTHONPATH="$CODE"
mkdir -p "$HOME_T/data/raw" "$HOME_T/data/research" "$HOME_T/reports"

echo "== 1. exchange files for $DAY (and the day before) =="
YDAY=$(date -d "$DAY -1 day" +%F)
for d in "$YDAY" "$DAY"; do
  "$PY" "$CODE/tools/bhavcopy.py" "$d" --dest "$HOME_T/data/raw" || echo "bhavcopy $d: some files not available yet (will retry at 21:00 / next run)"
done

echo "== 2. snapshot of the live DB (read-only) =="
"$PY" - "$HOME_T/state/trader.db" "$HOME_T/data/research/snapshot.db" <<'PYEOF' || { echo "snapshot FAILED"; exit 0; }
import sqlite3, sys, os
src = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
if os.path.exists(sys.argv[2]): os.remove(sys.argv[2])
dst = sqlite3.connect(sys.argv[2])
if hasattr(src, "backup"): src.backup(dst)
else: dst.executescript("\n".join(src.iterdump()))   # python < 3.7
dst.execute("DELETE FROM kv"); dst.commit(); dst.close(); src.close()   # never keep the access token in a copy
print("snapshot ok")
PYEOF

echo "== 3. shadow research =="
REP="$HOME_T/reports/research_$DAY.txt"
nice -n 19 "$PY" "$CODE/tools/research_run.py" --grid --out "$HOME_T/reports/research_rows" "$HOME_T/data/research/snapshot.db" > "$REP" 2>&1 \
  && { cp "$REP" "$HOME_T/reports/research_latest.txt"; echo "report: $REP"; } || { echo "research FAILED, see $REP"; tail -5 "$REP"; }

echo "== 4. backup + publish report =="
bash "$CODE/tools/backup_data.sh" "$DAY" || echo "backup step failed (non-fatal)"
CLONE="$HOME/trader/databackup"
if [ -d "$CLONE/.git" ] && [ -s "$REP" ]; then
  mkdir -p "$CLONE/research"; cp "$REP" "$CLONE/research/research_$DAY.txt"
  ( cd "$CLONE" && git add research && { git diff --cached --quiet || { git -c user.name="trader-1" -c user.email="trader-1@localhost" commit -q -m "research $DAY" && git push -q origin data-backup && echo "pushed research $DAY"; }; } ) || echo "publish failed (non-fatal)"
fi
echo "done"
