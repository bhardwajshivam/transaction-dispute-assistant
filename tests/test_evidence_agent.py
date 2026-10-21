from tests.support import prepare_reference
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from conversation import start, submit, OPTIONS
from evidence_agent import run, propose, read_tool, validate_proposal
from scripts.generate_data import generate
from scripts.load_database import load_database


class EvidenceControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        generate(root)
        self.db = root / 'demo.sqlite'
        load_database(root / 'runtime', self.db)

    def selected(self, issue=0, transaction='TX-1001'):
        state = start()
        submit(state, OPTIONS[issue])
        submit(state, "CARD-001")
        submit(state, "Please investigate this payment.")
        prepare_reference(state, transaction)
        submit(state, transaction)
        return state

    def test_scoped_evidence_and_no_repeat_calls(self):
        state = self.selected(1, 'TX-1002')
        before = self.db.read_bytes()
        run(state, database=self.db)
        self.assertEqual(set(state['evidence']), {'transaction', 'merchant', 'policy', 'cancellations'})
        self.assertTrue(all(e['status'] == 'SUCCESS' for e in state['evidence'].values()))
        trace = deepcopy(state['agent_trace'])
        run(state, database=self.db)
        self.assertEqual(state['agent_trace'], trace)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(state['step'], 'cancel_type')

    def test_permission_and_reference_validation(self):
        state = self.selected()
        malicious = {'tool': 'verify_selected_transaction', 'gap': 'transaction', 'transaction_id': 'TX-1031'}
        self.assertEqual(validate_proposal(state, malicious)[1], 'REFERENCE_MISMATCH')
        self.assertEqual(read_tool(malicious, database=self.db)['status'], 'FORBIDDEN_OR_NOT_FOUND')
        self.assertEqual(validate_proposal(state, {'tool': 'create_case'})[1], 'INVALID_SCHEMA')
        proposal = propose(state)
        proposal['tool'] = 'execute_sql'
        run(state, proposer=lambda _: proposal, database=self.db)
        self.assertEqual(state['agent_stop_reason'], 'TOOL_NOT_ALLOWED')
        self.assertEqual(state['evidence'], {})

    def test_missing_policy_and_conflicting_versions(self):
        for conflict in (True, False):
            with self.subTest(conflict=conflict):
                with sqlite3.connect(self.db) as db:
                    if conflict:
                        db.execute("INSERT INTO policies SELECT policy_id,'99',effective_from,effective_to,scope,record_json FROM policies LIMIT 1")
                    else:
                        db.execute('DELETE FROM policies')
                state = self.selected()
                run(state, database=self.db)
                self.assertIn('POLICY_CONFLICT' if conflict else 'POLICY_UNAVAILABLE', state['review_signals'])

    def test_tool_unavailable_and_malformed_record(self):
        state = self.selected()
        run(state, database=Path(self.temporary.name) / 'missing.sqlite')
        self.assertEqual(state['agent_stop_reason'], 'TRANSACTION_NOT_VERIFIED')
        self.assertIn('EVIDENCE_VERIFICATION_UNAVAILABLE', state['review_signals'])
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE transactions SET evidence_json='invalid' WHERE transaction_id='TX-1001'")
        state = self.selected()
        run(state, database=self.db)
        self.assertEqual(state['evidence']['transaction']['status'], 'MALFORMED')

    def test_no_record_is_not_claimed_as_proof(self):
        state = self.selected(4, 'TX-1003')
        run(state, database=self.db)
        self.assertEqual(state['evidence']['refunds']['status'], 'NOT_FOUND')
        for answer in ['They agreed to issue a refund', '2026-10-18', 'GBP 42.00', 'This card', 'No']:
            submit(state, answer)
        self.assertEqual(state['decision']['reason'], 'REFUND_RECORDS_REVIEW')
        self.assertIn('does not prove', state['decision']['explanation'])
        self.assertTrue(state['decision']['evidence_ids'])

    def test_budget_and_proposer_failure_fallback(self):
        state = self.selected()
        state['agent_trace'] = [{} for _ in range(8)]
        run(state, database=self.db)
        self.assertEqual(state['agent_stop_reason'], 'BUDGET_EXHAUSTED')
        self.assertNotIn('evidence', state['agent_trace'][0])
        state = self.selected()
        def broken(_):
            raise ValueError('Malformed model result')
        run(state, proposer=broken, database=self.db)
        self.assertEqual(state['agent_stop_reason'], 'PROPOSER_FAILED')
        self.assertEqual(state['step'], 'recognise')
