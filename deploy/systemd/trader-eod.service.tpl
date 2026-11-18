[Unit]
Description=Trader end-of-day job: exchange files, snapshot, shadow research, backup (never trades)

[Service]
Type=oneshot
Nice=19
Environment=TRADER_HOME=@HOME@/trader
Environment=PYTHONPATH=@HOME@/trader/current
WorkingDirectory=@HOME@/trader/current
ExecStart=/bin/bash @HOME@/trader/current/tools/eod_research.sh
