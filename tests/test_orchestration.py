from tests.support import prepare_reference
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from conversation import start, submit, OPTIONS
from orchestration import gather
from concerns import save_note, get_concern

from scripts.generate_data import generate
from scripts.load_database import load_database


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        generate(root)
        self.db = root / 'test.sqlite'
        load_database(root / 'runtime', self.db)

    def state(self):
        s = start()
        submit(s, OPTIONS[1])
        submit(s, "CARD-001")
        submit(s, "I cancelled but was charged again.")
        prepare_reference(s, 'TX-1002')
        submit(s, 'TX-1002')
        return s

    def test_model_loop_reorders_allowed_gaps_and_preserves_workflow(self):
        s = self.state()
        calls = []
        def backend(context, schema, instructions):
            calls.append(context)
            self.assertIn('transaction', context['evidence_statuses'])
            self.assertEqual(context['evidence_statuses']['transaction']['status'], 'SUCCESS')
            return json.dumps(context['allowed_proposals'][-1])
        gather(s, database=self.db, mode='ollama', backend=backend)
        self.assertEqual(len(calls), 3)
        self.assertEqual(s['step'], 'cancel_type')
        self.assertEqual(s['evidence_runtime']['effective_mode'], 'model_assisted')
        self.assertEqual(set(s['evidence']), {'transaction', 'policy', 'merchant', 'cancellations'})
        self.assertTrue(all(t['validation'] == 'VALIDATED' for t in s['agent_trace']))
        cid, _ = save_note(s, 'transaction', 'TX-1002', database=self.db)
        persisted = json.loads(get_concern(cid, database=self.db)[0]['state_json'])
        self.assertEqual(persisted['proposer_trace'], s['proposer_trace'])

    def test_invalid_or_unavailable_model_falls_back_once(self):
        for invalid in (True, False):
            with self.subTest(invalid=invalid):
                calls = []
                def backend(*args):
                    calls.append(1)
                    if invalid:
                        return '{"tool":"create_case","gap":"policy","transaction_id":"OTHER"}'
                    raise TimeoutError('secret provider body')
                s = self.state()
                gather(s, database=self.db, mode='ollama', backend=backend)
                self.assertEqual(len(calls), 1)
                self.assertTrue(s['model_circuit_open'])
                self.assertEqual(s['evidence_runtime']['effective_mode'], 'deterministic_fallback')
                self.assertEqual(len(s['evidence']), 4)
                self.assertEqual(s['step'], 'cancel_type')
                self.assertNotIn('secret provider body', json.dumps(s))
                self.assertEqual(s['handoff_status'], 'NOT_REQUESTED')

    def test_cross_account_selection_never_sent_to_model(self):
        s = self.state()
        s['answers']['transaction'] = 'TX-1031'
        gather(s, database=self.db, mode='ollama', backend=lambda *_: self.fail('Must not send inaccessible reference'))
        self.assertEqual(s['agent_stop_reason'], 'TRANSACTION_NOT_VERIFIED')
        self.assertEqual(s['review_requirement'], 'REQUIRED')

    def test_missing_configuration_and_default_do_not_call_provider(self):
        with patch.dict('os.environ', {}, clear=True):
            s = self.state()
            gather(s, database=self.db)
            self.assertEqual(s['evidence_runtime']['effective_mode'], 'deterministic')
            s = self.state()
            with patch.dict('os.environ', {'OLLAMA_TIMEOUT_SECONDS': 'invalid'}):
                gather(s, database=self.db, mode='ollama')
            self.assertEqual(s['evidence_runtime']['status'], 'INVALID_CONFIGURATION')
            self.assertEqual(len(s['evidence']), 4)

    def test_policy_failure_and_required_review_survive_model(self):
        with sqlite3.connect(self.db) as db:
            db.execute('DELETE FROM policies')
        s = self.state()
        s['reported_card_risk'] = True
        gather(s, database=self.db, mode='ollama', backend=lambda ctx, *_: json.dumps(ctx['allowed_proposals'][0]))
        self.assertIn('ONGOING_CARD_RISK', s['review_reason_codes'])
        self.assertIn('POLICY_UNAVAILABLE', s['review_reason_codes'])
        self.assertEqual(s['review_requirement'], 'REQUIRED')
        self.assertNotIn('handoff', s)

    def test_streamlit_uses_configured_model_boundary_without_live_api(self):
        from streamlit.testing.v1 import AppTest
        calls = []
        def backend(context, *_):
            calls.append(context)
            return json.dumps(context['allowed_proposals'][0])
        with patch.dict('os.environ', {'CONCERNS_DATABASE': str(self.db), 'EVIDENCE_PROPOSER_MODE': 'ollama', 'CONCERN_EXTRACTION_MODE': 'deterministic'}), patch('ollama_backend.backend_from_env', return_value=backend):
            app = AppTest.from_file('app.py').run()
            self.assertEqual(calls, [])
            next(b for b in app.button if b.label == OPTIONS[1]).click().run()
            next(b for b in app.button if b.label.startswith('Demo card CARD-001 ')).click().run()
            app.chat_input[0].set_value('I cancelled but was charged again, reference TX-1002').run()
            next(b for b in app.button if b.label == 'Confirm and search').click().run()
            next(b for b in app.button if b.label.startswith('TX-1002')).click().run()
            self.assertEqual(len(calls), 3)
            saved = app.session_state.conversation
            self.assertEqual(saved['evidence_runtime']['effective_mode'], 'model_assisted')
            self.assertEqual(saved['step'], 'cancel_type')
            self.assertFalse(app.exception)
