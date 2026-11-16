import datetime

IST = datetime.timedelta(hours=5, minutes=30)


def ist_now():
    """Naive IST wall-clock time, independent of the VM's timezone (the VM runs UTC)."""
    return datetime.datetime.utcnow() + IST
