[Unit]
Description=Run the trader watchdog every minute

[Timer]
OnCalendar=*-*-* *:*:00
AccuracySec=5s

[Install]
WantedBy=timers.target
