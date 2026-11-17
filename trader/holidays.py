"""NSE trading holidays (weekday closures). Weekends are skipped separately by the daemon.
2026 list as published by NSE - CHECK it against the NSE circular before relying on it; you can add days at any
time from Telegram with /holiday YYYY-MM-DD (and /skip for a one-off). Muhurat session on Sun 8 Nov is ignored (weekend)."""
NSE_HOLIDAYS = {
    "2026-01-26": "Republic Day", "2026-03-03": "Holi", "2026-03-26": "Ram Navami", "2026-03-31": "Mahavir Jayanti",
    "2026-04-03": "Good Friday", "2026-04-14": "Ambedkar Jayanti", "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id", "2026-06-26": "Muharram", "2026-09-14": "Ganesh Chaturthi", "2026-10-02": "Gandhi Jayanti",
    "2026-10-20": "Dussehra", "2026-11-10": "Diwali Balipratipada", "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}
