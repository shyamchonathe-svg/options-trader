[Unit]
Description=Options trader (shadow/live) - control plane and engine
After=network-online.target
Wants=network-online.target

[Service]
User=@USER@
Environment=TRADER_HOME=@HOME@/trader
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=@HOME@/trader/current
ExecStart=@HOME@/trader/venv/bin/python -m trader.main
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
