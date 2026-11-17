import csv, gzip, io, os, sqlite3, tempfile, unittest

from trader.store import Store
from trader import backup


class Backup(unittest.TestCase):
    def test_export_excludes_kv_and_is_idempotent(self):
        d = tempfile.mkdtemp()
        db = os.path.join(d, "t.db")
        s = Store(db)
        s.kv_set("access_token", "SECRET-TOKEN")
        s.put_bar("2026-11-18", "NIFTY", 0, 1, 2, 0.5, 1.5, 3, "live")
        s.put_bar("2026-11-17", "NIFTY", 0, 9, 9, 9, 9, 3, "live")
        s.add_signal("2026-11-18", "NIFTY25300CE", 5, "CE", "traded")
        s.db.commit()
        out = os.path.join(d, "out")
        c = backup.export_day(db, out, "2026-11-18")
        self.assertEqual((c["bars"], c["signals"]), (1, 1))
        names = os.listdir(os.path.join(out, "2026-11-18"))
        self.assertNotIn("kv.csv.gz", names)
        blob = b"".join(open(os.path.join(out, "2026-11-18", n), "rb").read() for n in names)
        self.assertNotIn(b"SECRET", b"".join(gzip.decompress(open(os.path.join(out, "2026-11-18", n), "rb").read()) for n in names))
        p = os.path.join(out, "2026-11-18", "bars.csv.gz")
        first = open(p, "rb").read()
        backup.export_day(db, out, "2026-11-18")
        self.assertEqual(first, open(p, "rb").read())
        rows = list(csv.reader(io.StringIO(gzip.decompress(first).decode())))
        self.assertEqual(rows[0][:3], ["day", "symbol", "slot"])
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
