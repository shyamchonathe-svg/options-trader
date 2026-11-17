"""Date reminders sent to Telegram at 10:00 on the day (weekends included). Add your own, one per line, in
state/reminders.txt as:  YYYY-MM-DD some text   (no restart needed)."""
import os

BUILTIN = [
    ("2026-11-23", "Tomorrow (Tue 24 Nov) the built-in list treats NSE as CLOSED (Guru Nanak Jayanti). Verify against the NSE circular; /holiday or edit holidays.py if wrong."),
    ("2026-11-30", "Paper-trading window ends today. Send me the exports for the month-end review; order-layer work starts in December."),
    ("2026-12-14", "Kite Connect renews on 18 Dec (500 credits). Check the balance in the Kite console."),
    ("2026-12-18", "Kite Connect renewal day today. Confirm credits so the data feed does not stop."),
    ("2026-12-20", "Add the 2027 NSE trading holidays to trader/holidays.py (NSE publishes the list in December). Until then 2027 holidays are NOT known to the bot."),
    ("2027-02-01", "GCP free trial ends around 13 Feb 2027 (confirm the exact date: console > Billing). Upgrade to a paid account before then or the VM stops."),
    ("2027-02-08", "GCP trial ends in about 5 days: upgrade in Billing now."),
]


def due(day, extra_path=None):
    out = [t for d, t in BUILTIN if d == day]
    if extra_path and os.path.exists(extra_path):
        with open(extra_path) as f:
            for line in f:
                d, _, t = line.strip().partition(" ")
                if d == day and t:
                    out.append(t)
    return out
