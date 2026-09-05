import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from journal import Journal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "journal.sqlite3"
        self.journal = Journal(self.path)
        self.fields = dict(symbol=" aapl ", side="买入", currency="USD", price="12.34000001", quantity="0.125", traded_on="2026-09-05", note="长期观察\n第二行")

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def test_persistence_edit_and_delete(self):
        identity = self.journal.save(**self.fields)
        self.journal.close()
        self.journal = Journal(self.path)
        row = self.journal.all()[0]
        self.assertEqual(row['symbol'], "AAPL")
        self.assertEqual(row['price'], "12.34000001")
        self.assertEqual(row['note'], self.fields['note'])
        self.journal.save(trade_id=identity, **{**self.fields, "side": "卖出"})
        self.assertEqual(len(self.journal.all()), 1)
        self.assertEqual(self.journal.all()[0]['side'], "卖出")
        self.journal.delete(identity)
        self.assertEqual(self.journal.all(), [])

    def test_invalid_inputs_never_write(self):
        for key, values in {"price": ["NaN", "Infinity", "-1", "0", "bad", "1e12", "0.000000001"], "quantity": ["0", "-2", "NaN"], "traded_on": ["2026-02-30", "20260905", "no"], "symbol": ["", "x' OR 1=1", "a" * 25], "currency": ["??"], "side": ["other"]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.journal.save(**{**self.fields, key: value})
        self.assertEqual(self.journal.all(), [])

    def test_backup_is_independent_and_search_handles_text(self):
        identity = self.journal.save(**self.fields)
        self.assertEqual(len(self.journal.all("aapl")), 1)
        self.assertEqual(len(self.journal.all("长期")), 1)
        self.assertEqual(len(self.journal.all("%")), 0)
        target = Path(self.tmp.name) / "backup.sqlite3"
        self.journal.backup(target)
        self.journal.delete(identity)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM trades").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.journal.backup(self.path)

    def test_missing_update_does_not_create_record(self):
        with self.assertRaises(ValueError):
            self.journal.save(trade_id=999, **self.fields)
        self.assertEqual(self.journal.all(), [])


if __name__ == "__main__":
    unittest.main()
