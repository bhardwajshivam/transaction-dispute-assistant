import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.generate_data import generate
from scripts.load_database import load_database
from domain import load_transactions


class DatabaseTests(unittest.TestCase):
    def test_import_access_constraints_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            generate(output)
            database = output / 'test.sqlite'
            counts = load_database(output / 'runtime', database)
            self.assertEqual(counts['transactions'], 90)
            self.assertEqual(len(load_transactions(database=database)), 30)
            self.assertEqual(load_transactions('A-002', database=database), ())
            self.assertEqual(len(load_transactions('A-002', 'C-002', database)), 30)
            self.assertEqual(load_transactions("A-001' OR 1=1 --", database=database), ())
            with sqlite3.connect(database) as db:
                db.execute('PRAGMA foreign_keys=ON')
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE transactions SET amount_minor=-1 WHERE transaction_id='TX-1001'")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE transactions SET account_id='MISSING' WHERE transaction_id='TX-1001'")
            with self.assertRaises(FileExistsError):
                load_database(output / 'runtime', database)
            before = database.read_bytes()
            path = output / 'runtime/transactions.json'
            rows = json.loads(path.read_text())
            rows[0]['account_id'] = 'MISSING'
            path.write_text(json.dumps(rows))
            with self.assertRaises(sqlite3.IntegrityError):
                load_database(output / 'runtime', database, replace=True)
            self.assertEqual(before, database.read_bytes())
