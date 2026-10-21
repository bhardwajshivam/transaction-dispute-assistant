import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from privacy import protect, sanitise, customer_export
from secure_storage import Codec, StorageSecurityError
from access import authenticate_staff, require_staff, StaffPrincipal
from concerns import save_note, get_concern, connection, list_handoffs, record_export
from conversation import start, submit, OPTIONS
from concern_extraction import extract
from retention import purge_expired, set_hold
from scripts.generate_data import generate
from scripts.load_database import load_database


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); generate(root)
        self.db = root / 'test.sqlite'; load_database(root / 'runtime', self.db)

    def test_redacts_identifiers_but_keeps_dispute_details(self):
        original = 'Email alex@example.com phone +91 9876543210 card 4111 1111 1111 1111. Charged INR 200 on 19-10-2026 instead of INR 180. TX-999001'
        result = protect(original)
        for value in ('alex@example.com', '+91 9876543210', '4111 1111 1111 1111'):
            self.assertNotIn(value, result.text)
        for value in ('INR 200', '19-10-2026', 'INR 180', 'TX-999001'):
            self.assertIn(value, result.text)
        self.assertFalse(result.contains_secrets)
        self.assertEqual(protect(result.text).text, result.text)

    def test_secrets_are_rejected_before_model_or_database(self):
        for secret in ('OTP 123456', 'PIN: 1234', 'CVV 123', 'password is Hunter2', 'password Hunter2', 'Bearer synthetic.token.value123'):
            with self.subTest(secret=secret):
                s = start(); s['step'] = 'elaborate'; s['answers']['issue'] = OPTIONS[3]
                submit(s, secret)
                self.assertNotIn(secret, json.dumps(s))
                with self.assertRaises(ValueError): save_note(s, 'elaborate', secret, database=self.db)
                with patch('concern_extraction.local_chat') as model:
                    fields, _, trace = extract(secret, 'wrong_amount')
                    model.assert_not_called()
                    self.assertEqual(trace['status'], 'BLOCKED_SENSITIVE_SECRET')

    def test_only_sanitised_text_reaches_ollama(self):
        text = 'Email alex@example.com card 4111111111111111 charged INR 200 on 19-10-2026'
        calls = []
        def transport(payload, timeout):
            calls.append(json.dumps(payload))
            return {'done': True, 'done_reason': 'stop', 'message': {'content': '{"entities":[]}'}}
        with patch.dict(os.environ, {'CONCERN_EXTRACTION_MODE': 'ollama'}):
            fields, _, _ = extract(text, 'wrong_amount', transport=transport)
        self.assertNotIn('alex@example.com', calls[0])
        self.assertNotIn('4111111111111111', calls[0])
        self.assertEqual(fields['charged_amount'], '200.00')

    def test_encrypted_storage_redacted_history_and_minimal_events(self):
        s = start()
        raw = 'Email alex@example.com. I was charged INR 200 on 19-10-2026'
        s['messages'].append(('user', raw)); s['answers']['elaborate'] = raw
        cid, _ = save_note(s, 'elaborate', raw, database=self.db)
        with sqlite3.connect(self.db) as db:
            encrypted = db.execute('SELECT state_json FROM concerns').fetchone()[0]
            self.assertTrue(encrypted.startswith('enc:v1:'))
            self.assertNotIn('charged', encrypted)
            self.assertNotIn('alex@example.com', self.db.read_bytes().decode('latin1'))
        row, events = get_concern(cid, database=self.db)
        self.assertNotIn('alex@example.com', row['state_json'])
        self.assertNotIn('messages', json.loads(events[0]['state_json']))
        export = customer_export(json.loads(row['state_json']), cid, events)
        self.assertNotIn('agent_trace', export)
        self.assertNotIn('evidence', export)
        self.assertNotIn('alex@example.com', json.dumps(export))
        self.assertEqual((self.db.stat().st_mode & 0o777), 0o600)
        self.assertEqual(((self.db.parent / '.private/concerns.key').stat().st_mode & 0o777), 0o600)

    def test_missing_or_wrong_key_fails_closed(self):
        cid, _ = save_note(start(), 'issue', 'New concern', database=self.db)
        with patch.dict(os.environ, {'CONCERN_ENCRYPTION_KEY': 'invalid'}):
            with self.assertRaises(StorageSecurityError): get_concern(cid, database=self.db)
        key = self.db.parent / '.private/concerns.key'
        original = key.read_bytes(); key.unlink()
        with self.assertRaises(StorageSecurityError): get_concern(cid, database=self.db)
        self.assertFalse(key.exists())
        key.write_bytes(original)
        self.assertEqual(get_concern(cid, database=self.db)[0]['concern_id'], cid)

    def test_staff_auth_scope_expiry_and_metadata_audit(self):
        cid, _ = save_note(start(), 'issue', 'New concern', database=self.db)
        with self.assertRaises(PermissionError): list_handoffs(database=self.db)
        token = 'synthetic-high-entropy-staff-token'
        with patch.dict(os.environ, {'STAFF_ACCESS_TOKEN_SHA256': hashlib.sha256(token.encode()).hexdigest(), 'STAFF_ALLOWED_CUSTOMERS': 'C-001'}):
            with self.assertRaises(PermissionError): authenticate_staff('wrong')
            staff = authenticate_staff(token)
            self.assertEqual(list_handoffs(database=self.db, principal=staff), [])
            with self.assertRaises(PermissionError): list_handoffs('C-002', self.db, principal=staff)
            with self.assertRaises(PermissionError): require_staff(StaffPrincipal('staff', ('C-001',), 0), 'C-001')
            record_export(cid, database=self.db, principal=staff)
        with sqlite3.connect(self.db) as db:
            audit = db.execute('SELECT operation,actor_id FROM privacy_audit').fetchall()
            self.assertIn(('EXPORT_REQUESTED','staff-demo'), audit)
            self.assertNotIn(token, str(audit))

    def test_retention_dry_run_holds_and_deletion(self):
        a, _ = save_note(start(), 'issue', 'Old concern', database=self.db)
        b, _ = save_note(start(), 'issue', 'Held concern', database=self.db)
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        with connection(self.db) as db: db.execute('UPDATE concerns SET updated_at=?', (old,))
        set_hold(b, 'LEGAL_HOLD', self.db)
        self.assertEqual(purge_expired(30, self.db)['eligible_concerns'], 1)
        self.assertEqual(get_concern(a, database=self.db)[0]['concern_id'], a)
        self.assertEqual(purge_expired(30, self.db, execute=True)['eligible_concerns'], 1)
        with self.assertRaises(PermissionError): get_concern(a, database=self.db)
        self.assertEqual(get_concern(b, database=self.db)[0]['concern_id'], b)
        with connection(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM concern_events WHERE concern_id=?', (a,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM concern_review WHERE concern_id=?', (a,)).fetchone()[0], 0)

    def test_legacy_payload_migration_redacts_and_encrypts(self):
        # Manually construct a legacy plaintext concern after schema setup.
        with connection(self.db) as db:
            s = start(); s['answers']['elaborate'] = 'Email legacy@example.com'
            db.execute('INSERT INTO concerns VALUES (?,?,?,?,?,?)', ('CON-LEGACY', 'C-001', '2026-01-01', '2026-01-01', 1, json.dumps(s)))
        row, _ = get_concern('CON-LEGACY', database=self.db)
        self.assertNotIn('legacy@example.com', row['state_json'])
        with sqlite3.connect(self.db) as db:
            self.assertTrue(db.execute('SELECT state_json FROM concerns').fetchone()[0].startswith('enc:v1:'))

    def test_streamlit_blocks_secrets_and_redacts_model_and_export_input(self):
        from streamlit.testing.v1 import AppTest
        env = {'CONCERNS_DATABASE': str(self.db), 'CONCERN_EXTRACTION_MODE': 'deterministic', 'EVIDENCE_PROPOSER_MODE': 'deterministic'}
        with patch.dict(os.environ, env):
            app = AppTest.from_file('app.py').run()
            next(b for b in app.button if b.label == OPTIONS[3]).click().run()
            next(b for b in app.button if b.label.startswith('Demo card CARD-001 ')).click().run()
            app.chat_input[0].set_value('My OTP is 123456').run()
            self.assertTrue(any('not been saved' in e.value for e in app.error))
            self.assertNotIn('123456', json.dumps(app.session_state.conversation))
            app.chat_input[0].set_value('Email alex@example.com. Charged INR 200 instead of INR 180 on 19-10-2026').run()
            s = app.session_state.conversation
            self.assertEqual(s['step'], 'search_confirm')
            self.assertNotIn('alex@example.com', json.dumps(s))
            cid = app.session_state.concern_id
            row, events = get_concern(cid, database=self.db)
            self.assertNotIn('123456', json.dumps(events))
            self.assertNotIn('alex@example.com', row['state_json'])
            data = customer_export(json.loads(row['state_json']), cid, events)
            self.assertEqual(data['confirmed_search_details'], None)
            self.assertNotIn('controller_trace', json.dumps(data))
            self.assertFalse(app.exception)
