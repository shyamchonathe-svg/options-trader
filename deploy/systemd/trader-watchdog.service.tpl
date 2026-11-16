[Unit]
Description=Trader heartbeat watchdog

[Service]
Type=oneshot
Environment=TRADER_HOME=@HOME@/trader
WorkingDirectory=@HOME@/trader/current
ExecStart=@HOME@/trader/venv/bin/python -m trader.watchdog
