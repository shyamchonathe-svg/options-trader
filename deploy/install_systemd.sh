#!/bin/bash
# Installs/updates the systemd units for the CURRENT user. Run from ~/trader/current:  bash deploy/install_systemd.sh
# Does not start the trader; it prints what to do next. Safe to run again after each release.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
U=$(id -un); H=$HOME
for n in trader.service trader-watchdog.service trader-watchdog.timer trader-backup.service trader-backup.timer trader-eod.service trader-eod.timer; do
  sed -e "s#@USER@#$U#g" -e "s#@HOME@#$H#g" "$HERE/systemd/$n.tpl" | sudo tee /etc/systemd/system/$n >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable trader.service trader-watchdog.timer trader-backup.timer trader-eod.timer
echo "units installed. Next:"
echo "  1) ~/trader/venv/bin/python -m trader.setup_telegram   (once)"
echo "  2) sudo systemctl start trader.service trader-watchdog.timer trader-backup.timer trader-eod.timer"
echo "  3) journalctl -u trader -n 30 --no-pager"
