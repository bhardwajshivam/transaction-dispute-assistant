from tests.support import prepare_reference
from pathlib import Path
import tempfile
import unittest
from conversation import start, submit, OPTIONS
from concerns import save_note, get_concern, list_concerns, summary
from scripts.generate_data import generate
from scripts.load_database import load_database


class ConcernTests(unittest.TestCase):
    def test_history_retry_access_and_stale_update(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            generate(root)
            db = root / 'test.sqlite'
            load_database(root / 'runtime', db)
            state = start()
            submit(state, OPTIONS[0])
            cid, rev = save_note(state, 'issue', OPTIONS[0], event_id='event-1', database=db)
            self.assertEqual(save_note(state, 'issue', OPTIONS[0], event_id='event-1', database=db), (cid, rev))
            with self.assertRaises(PermissionError):
                get_concern(cid, customer_id='C-002', database=db)
            self.assertEqual(list_concerns('C-002', db), [])
            submit(state, 'CARD-001')
            submit(state, 'I do not recognise this payment.')
            prepare_reference(state, 'TX-1001')
            submit(state, 'TX-1001')
            _, rev2 = save_note(state, 'transaction', 'TX-1001', cid, rev, database=db)
            self.assertEqual(rev2, 2)
            with self.assertRaises(ValueError):
                save_note(state, 'transaction', 'TX-1001', cid, rev, database=db)
            row, events = get_concern(cid, database=db)
            self.assertEqual(len(events), 2)
            self.assertLess(events[0]['recorded_at'], events[1]['recorded_at'])
            self.assertEqual(row['revision'], 2)
            self.assertIn('Customer statements (unverified', summary(cid, database=db))
            self.assertIn('Current demo bank facts', summary(cid, database=db))
            with self.assertRaises(ValueError):
                save_note(state, 'issue', 'changed payload', event_id='event-1', database=db)
            state['answers']['transaction'] = 'TX-1031'
            with self.assertRaises(PermissionError):
                save_note(state, 'transaction', 'TX-1031', database=db)

    def test_handoff_summary_confirmation_duplicates_and_rollback(self):
        import sqlite3
        import json
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            generate(root)
            db = root / 'test.sqlite'
            load_database(root / 'runtime', db)
            state = start()
            for text in [OPTIONS[0], 'CARD-001', 'I do not recognise this payment.', 'TX-1001', 'No', 'No', 'Yes', 'No']:
                if text.startswith("TX-"):
                    prepare_reference(state, text)
                submit(state, text)
            self.assertEqual(state['step'], 'handoff_confirm')
            cid, rev = save_note(state, 'permission', 'Yes', database=db)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM handoff_requests').fetchone()[0], 0)
                conn.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON handoff_requests BEGIN SELECT RAISE(ABORT, 'tool failure'); END")
            submit(state, 'Yes, request human assistance')
            pending = deepcopy(state)
            with self.assertRaises(sqlite3.IntegrityError):
                save_note(deepcopy(pending), 'handoff_confirm', 'Yes, request human assistance', cid, rev, database=db)
            self.assertEqual(get_concern(cid, database=db)[0]['revision'], rev)
            with sqlite3.connect(db) as conn:
                conn.execute('DROP TRIGGER fail_queue')
            cid, rev = save_note(state, 'handoff_confirm', 'Yes, request human assistance', cid, rev, database=db)
            self.assertEqual(state['handoff']['status'], 'SIMULATED_QUEUED')
            self.assertEqual(state['step'], 'done')
            with sqlite3.connect(db) as conn:
                from secure_storage import Codec
                package = json.loads(Codec(db, encrypted_exists=True).open(conn.execute('SELECT summary_json FROM handoff_requests').fetchone()[0]))
                self.assertEqual(package['demo_bank_facts']['transaction_id'], 'TX-1001')
                self.assertIn('customer_statements_unverified', package)
            # A separate repeat request for this concern reuses the existing queue entry.
            state['step'] = 'handoff_confirm'
            submit(state, 'Yes, request human assistance')
            save_note(state, 'handoff_confirm', 'Yes, request human assistance', cid, rev, database=db)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM handoff_requests').fetchone()[0], 1)

    def test_uncertain_and_declined_handoff(self):
        state = start()
        state['step'] = 'satisfaction'
        submit(state, 'I’m not sure')
        self.assertEqual(state['step'], 'handoff_confirm')
        submit(state, 'Not now')
        self.assertEqual(state['step'], 'done')
        self.assertNotIn('handoff', state)
