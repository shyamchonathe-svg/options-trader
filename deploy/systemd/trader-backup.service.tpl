[Unit]
Description=Trader daily data backup to git (branch data-backup)

[Service]
Type=oneshot
Environment=TRADER_HOME=@HOME@/trader
Environment=PYTHONPATH=@HOME@/trader/current
WorkingDirectory=@HOME@/trader/current
ExecStart=/bin/bash @HOME@/trader/current/tools/backup_data.sh
