"""NSE trading holidays (weekday closures). Weekends are skipped separately by the daemon.
2026 list VERIFIED on 17 Nov 2026 against the NSE circulars (equity derivatives segment, 15 weekday closures; the 4
weekend holidays need no entry). Muhurat session on Sun 8 Nov is ignored (weekend). 2027: NOT known yet (NSE publishes in
December); a reminder on 20 Dec asks for it. Add days any time with /holiday YYYY-MM-DD, one-off with /skip."""
NSE_HOLIDAYS = {
    "2026-01-26": "Republic Day", "2026-03-03": "Holi", "2026-03-26": "Ram Navami", "2026-03-31": "Mahavir Jayanti",
    "2026-04-03": "Good Friday", "2026-04-14": "Ambedkar Jayanti", "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id", "2026-06-26": "Muharram", "2026-09-14": "Ganesh Chaturthi", "2026-10-02": "Gandhi Jayanti",
    "2026-10-20": "Dussehra", "2026-11-10": "Diwali Balipratipada", "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}
