"""Consistent gzip copy of the SQLite DB, kept locally (last 14) and sent to Telegram after the daily summary."""
import gzip
import os
import shutil
import sqlite3
import time

KEEP = 14


def make_export(store, out_dir, day):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir, 0o700)
    tmp = os.path.join(out_dir, "tmp_%s.db" % day)
    if os.path.exists(tmp):
        os.remove(tmp)
    if hasattr(store.db, "backup"):                       # py3.7+
        dst = sqlite3.connect(tmp)
        store.db.backup(dst)
        dst.close()
    else:
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copyfile(store.path, tmp)
    out = os.path.join(out_dir, "trader_%s.db.gz" % day)
    with open(tmp, "rb") as f, gzip.open(out, "wb") as g:
        shutil.copyfileobj(f, g)
    os.remove(tmp)
    old = sorted(x for x in os.listdir(out_dir) if x.startswith("trader_") and x.endswith(".db.gz"))
    for x in old[:-KEEP]:
        os.remove(os.path.join(out_dir, x))
    return out
