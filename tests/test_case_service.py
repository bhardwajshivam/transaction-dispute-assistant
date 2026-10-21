import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import case_service as service
from concerns import save_note, get_concern, connection
from conversation import start, submit, OPTIONS
from scripts.generate_data import generate
from scripts.load_database import load_database
from tests.support import prepare_reference, demo_staff


class CaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        generate(root)
        self.db = root / 'cases.sqlite'
        load_database(root / 'runtime', self.db)
        env = patch.dict(os.environ, {'CONCERNS_DATABASE': str(self.db), 'CONCERN_EXTRACTION_MODE': 'deterministic'})
        env.start()
        self.addCleanup(env.stop)
        self.principal = service.demo_customer()
        self.state = self.concern_state()
        self.cid, self.rev = save_note(self.state, 'adjustment', 'No', database=self.db)

    def concern_state(self):
        state = start()
        for text in (OPTIONS[3], 'CARD-001', 'The agreed amount was INR 30, but I was billed more.', 'TX-1003', 'INR 30', 'Yes', 'No'):
            if text.startswith('TX-'):
                prepare_reference(state, text)
            submit(state, text)
        self.assertEqual(state['decision']['route'], 'HUMAN_REVIEW')
        return state

    def prepare(self, cid=None):
        return service.prepare(cid or self.cid, self.principal, self.db)

    def execute(self, command, **kwargs):
        return service.execute(command['command_id'], self.principal, service.CONFIRM, self.db, **kwargs)

    def count(self, table):
        with sqlite3.connect(self.db) as db:
            return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def test_confirmation_and_replay(self):
        command = self.prepare()
        self.assertEqual(self.count('cases'), 0)
        with self.assertRaisesRegex(service.CaseDenied, 'EXPLICIT_CONFIRMATION_REQUIRED'):
            service.execute(command['command_id'], self.principal, 'Yes', self.db)
        self.assertEqual(self.count('cases'), 0)
        result = self.execute(command)
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(self.execute(command)['case_id'], result['case_id'])
        self.assertEqual(self.count('cases'), 1)
        self.assertEqual(self.count('actions'), 1)
        self.assertEqual(self.count('audit_events'), 1)
        with sqlite3.connect(self.db) as db:
            operations = [r[0] for r in db.execute('SELECT operation FROM privacy_audit')]
        self.assertIn('CASE_CONFIRMED', operations)
        self.assertIn('CASE_CREATED', operations)
        self.assertIn('CASE_STATUS_VERIFIED', operations)

    def test_decline_and_expiry(self):
        command = self.prepare()
        service.cancel(command['command_id'], self.principal, self.db)
        with self.assertRaisesRegex(service.CaseDenied, 'COMMAND_NOT_EXECUTABLE'):
            self.execute(command)
        command = self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE case_commands SET expires_at=0')
        with self.assertRaisesRegex(service.CaseDenied, 'CONFIRMATION_EXPIRED'):
            self.execute(command)
        self.assertEqual(service.status(command['command_id'], self.principal, self.db)['status'], 'REJECTED')
        self.assertEqual(self.count('cases'), 0)

    def test_permission_scope_and_revocation(self):
        command = self.prepare()
        bad = [None, service.CustomerPrincipal('C-001', (), time()+900), service.CustomerPrincipal('C-001', ('case:create',), 0), service.CustomerPrincipal('C-002', ('case:create',), time()+900)]
        for principal in bad:
            with self.assertRaises(PermissionError):
                service.execute(command['command_id'], principal, service.CONFIRM, self.db)
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE case_permissions SET can_create=0 WHERE customer_id='C-001'")
        with self.assertRaises(PermissionError):
            self.execute(command)
        self.assertEqual(self.count('cases'), 0)

    def test_ownership_rechecked(self):
        command = self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM account_access WHERE customer_id='C-001'")
        with self.assertRaisesRegex(service.CaseDenied, 'TRANSACTION_NOT_VERIFIED'):
            self.execute(command)
        self.assertEqual(self.count('cases'), 0)

    def test_transaction_changes_need_reconfirmation(self):
        command = self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE transactions SET amount_minor=amount_minor+1 WHERE transaction_id='TX-1003'")
        with self.assertRaisesRegex(service.CaseDenied, 'EVIDENCE_CHANGED_RECONFIRM'):
            self.execute(command)
        self.assertEqual(self.count('cases'), 0)
        self.assertEqual(self.execute(self.prepare())['status'], 'SUCCEEDED')

    def test_assertion_change_needs_reconfirmation(self):
        command = self.prepare()
        self.state['answers']['follow_up_updates'] = ['The receipt amount was different.']
        save_note(self.state, 'follow_up_update', 'The receipt amount was different.', self.cid, self.rev, database=self.db)
        with self.assertRaisesRegex(service.CaseDenied, 'EVIDENCE_CHANGED_RECONFIRM'):
            self.execute(command)

    def test_policy_unavailable_and_version_change(self):
        command = self.prepare()
        policy = json.loads(service.POLICY_PATH.read_text())
        path = Path(self.tmp.name) / 'policy.json'
        policy['notice'] += ' Revised intake terms.'
        path.write_text(json.dumps(policy))
        with patch.object(service, 'POLICY_PATH', path):
            with self.assertRaisesRegex(service.CaseDenied, 'EVIDENCE_CHANGED_RECONFIRM'):
                self.execute(command)
            policy['effective_to'] = '2020-01-01'
            path.write_text(json.dumps(policy))
            with self.assertRaisesRegex(service.CaseDenied, 'CASE_POLICY_UNAVAILABLE'):
                self.prepare()

    def test_pending_and_incomplete_cases_abstain(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE transactions SET status='Pending',posted_date=NULL WHERE transaction_id='TX-1003'")
        with self.assertRaisesRegex(service.CaseDenied, 'PENDING_TRANSACTION_REQUIRES_HUMAN'):
            self.prepare()
        self.assertEqual(self.count('cases'), 0)

    def test_conflicting_evidence_abstains(self):
        self.state['review_reason_codes'] = ['MATERIAL_EVIDENCE_CONFLICT']
        save_note(self.state, 'follow_up_update', 'Conflicting evidence noted.', self.cid, self.rev, database=self.db)
        with self.assertRaisesRegex(service.CaseDenied, 'UNRESOLVED_EVIDENCE_REQUIRES_HUMAN'):
            self.prepare()

    def test_timeout_before_commit_retry_same_key(self):
        command = self.prepare()
        result = self.execute(command, fault='timeout_before_commit')
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(self.count('cases'), 0)
        self.assertEqual(service.reconcile(command['command_id'], self.principal, self.db)['status'], 'UNKNOWN')
        self.assertEqual(self.prepare()['command_id'], command['command_id'])
        self.assertEqual(self.execute(command)['status'], 'SUCCEEDED')
        self.assertEqual(self.count('cases'), 1)

    def test_timeout_after_commit_and_malformed_response(self):
        for fault in ('timeout_after_commit', 'malformed'):
            with self.subTest(fault=fault):
                command = self.prepare()
                self.assertEqual(self.execute(command, fault=fault)['status'], 'UNKNOWN')
                self.assertEqual(service.reconcile(command['command_id'], self.principal, self.db)['status'], 'SUCCEEDED')
                self.assertEqual(self.count('cases'), 1)

    def test_unknown_blocks_new_concern_submission(self):
        command = self.prepare()
        self.execute(command, fault='unavailable')
        cid, _ = save_note(self.concern_state(), 'adjustment', 'No', database=self.db)
        with self.assertRaisesRegex(service.CaseDenied, 'EARLIER_SUBMISSION_UNRESOLVED'):
            self.prepare(cid)

    def test_business_duplicate_and_parallel_requests(self):
        cid, _ = save_note(self.concern_state(), 'adjustment', 'No', database=self.db)
        commands = [self.prepare(), self.prepare(cid)]
        def submit_or_deny(command):
            try:
                return self.execute(command)
            except service.CaseDenied as error:
                self.assertEqual(error.code, 'EARLIER_SUBMISSION_UNRESOLVED')
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit_or_deny, commands))
        # A concurrent unresolved command may safely block its neighbour. Once
        # its outcome is established, a fresh confirmed preview links the case.
        results = [result or self.execute(self.prepare(command['concern_id'])) for result, command in zip(results, commands)]
        self.assertEqual(results[0]['case_id'], results[1]['case_id'])
        self.assertEqual(self.count('cases'), 1)
        self.assertEqual(self.count('case_links'), 2)
        self.assertEqual(self.count('actions'), 2)

    def test_already_prepared_request_cannot_bypass_unknown_guard(self):
        first, second = self.prepare(), self.prepare()
        self.execute(first, fault='timeout_before_commit')
        with self.assertRaisesRegex(service.CaseDenied, 'EARLIER_SUBMISSION_UNRESOLVED'):
            self.execute(second)
        self.assertEqual(self.count('cases'), 0)
        self.assertEqual(self.execute(first)['status'], 'SUCCEEDED')

    def test_parallel_same_command_replays_safely(self):
        command = self.prepare()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.execute, [command]*3))
        self.assertEqual({r['status'] for r in results}, {'SUCCEEDED'})
        self.assertEqual(len({r['case_id'] for r in results}), 1)
        self.assertEqual(self.count('actions'), 1)
        self.assertEqual(service.status(command['command_id'], self.principal, self.db)['status'], 'SUCCEEDED')

    def test_atomic_gateway_failure_is_not_success(self):
        command = self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_action BEFORE INSERT ON actions BEGIN SELECT RAISE(ABORT,'unavailable'); END")
        self.assertEqual(self.execute(command)['status'], 'UNKNOWN')
        self.assertEqual(self.count('cases'), 0)
        self.assertEqual(self.count('case_links'), 0)
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER fail_action')
        self.assertEqual(self.execute(command)['status'], 'SUCCEEDED')

    def test_encryption_staff_scope_and_retention(self):
        command = self.prepare()
        self.execute(command)
        for table, column in [('cases','record_json'), ('case_commands','payload_json'), ('actions','record_json'), ('audit_events','record_json')]:
            with sqlite3.connect(self.db) as db:
                self.assertTrue(db.execute(f'SELECT {column} FROM {table}').fetchone()[0].startswith('enc:v1:'))
        with self.assertRaises(PermissionError):
            service.staff_cases(None, database=self.db)
        cases, pending = service.staff_cases(demo_staff(), database=self.db)
        self.assertEqual(cases[0]['concern_ids'], [self.cid])
        self.assertEqual(pending, [])
        from retention import purge_expired
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE concerns SET updated_at='2000-01-01'")
        self.assertEqual(purge_expired(1, self.db, execute=True)['eligible_concerns'], 0)

    def test_chat_confirmation_does_not_clear_specialist_review(self):
        from case_chat import handle, OPEN
        self.state['review_requirement'] = 'REQUIRED'
        self.state['review_reason_codes'] = ['REPORTED_UNAUTHORISED']
        self.rev = save_note(self.state, 'permission', 'Yes', self.cid, self.rev, database=self.db)[1]
        self.assertTrue(handle(self.state, OPEN, self.cid, self.db))
        self.assertEqual(self.count('cases'), 0)
        self.assertTrue(handle(self.state, service.CONFIRM, self.cid, self.db))
        self.assertEqual(self.state['case_command']['status'], 'SUCCEEDED')
        self.assertEqual(self.state['review_requirement'], 'REQUIRED')

    def test_unconfirmed_gateway_is_denied(self):
        command = self.prepare()
        with self.assertRaisesRegex(service.CaseDenied, 'CONFIRMED_INTENT_REQUIRED'):
            service._gateway(command['command_id'], 'C-001', self.db)
        self.assertEqual(self.count('cases'), 0)

    def test_streamlit_create_and_reopen(self):
        from streamlit.testing.v1 import AppTest
        from case_chat import OPEN
        app = AppTest.from_file('app.py')
        app.session_state.conversation = self.state
        app.session_state.concern_id = self.cid
        app.session_state.concern_revision = self.rev
        app.run()
        next(b for b in app.button if b.label == OPEN).click().run()
        self.assertEqual(self.count('cases'), 0)
        self.assertIn(service.CONFIRM, [b.label for b in app.chat_message[-1].button])
        next(b for b in app.button if b.label == service.CONFIRM).click().run()
        self.assertEqual(app.session_state.conversation['case_command']['status'], 'SUCCEEDED')
        next(b for b in app.button if b.label == 'Open selected concern').click().run()
        self.assertEqual(app.session_state.conversation['case_command']['status'], 'SUCCEEDED')
        self.assertEqual(self.count('cases'), 1)
        self.assertFalse(app.exception)

    def test_unknown_chat_signal_does_not_break_retry(self):
        from case_chat import handle, OPEN, RETRY
        handle(self.state, OPEN, self.cid, self.db)
        def unavailable(command, principal, confirmation, database):
            return service.execute(command, principal, confirmation, database, fault='timeout_before_commit')
        with patch('case_chat.execute', side_effect=unavailable):
            handle(self.state, service.CONFIRM, self.cid, self.db)
        self.assertEqual(self.state['case_command']['status'], 'UNKNOWN')
        self.assertIn('ACTION_OUTCOME_UNKNOWN', self.state['review_reason_codes'])
        save_note(self.state, 'case_control', service.CONFIRM, self.cid, self.rev, database=self.db)
        handle(self.state, RETRY, self.cid, self.db)
        self.assertEqual(self.state['case_command']['status'], 'SUCCEEDED')
        self.assertEqual(self.count('cases'), 1)

    def test_process_interruption_recovers_from_ledger(self):
        command = self.prepare()
        with patch('case_service.reconcile', side_effect=RuntimeError('process interrupted')):
            with self.assertRaises(RuntimeError):
                self.execute(command)
        saved = service.latest(self.cid, self.principal, self.db)
        self.assertEqual(saved['status'], 'SUBMITTING')
        self.assertEqual(service.reconcile(saved['command_id'], self.principal, self.db)['status'], 'SUCCEEDED')
        self.assertEqual(self.count('cases'), 1)


if __name__ == '__main__':
    unittest.main()
