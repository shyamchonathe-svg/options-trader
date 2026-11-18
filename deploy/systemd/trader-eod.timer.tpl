[Unit]
Description=Trader end-of-day job Mon-Fri 18:35 and 21:00 (IST)

[Timer]
OnCalendar=Mon..Fri 18:35
OnCalendar=Mon..Fri 21:00
Persistent=true

[Install]
WantedBy=timers.target
