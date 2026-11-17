[Unit]
Description=Daily trader data backup at 16:30 Mon-Fri (IST)

[Timer]
OnCalendar=Mon..Fri 16:30
Persistent=true

[Install]
WantedBy=timers.target
