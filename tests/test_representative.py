from tests.support import demo_staff
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from conversation import start, submit
from concerns import save_note, list_handoffs
from scripts.generate_data import generate
from scripts.load_database import load_database


class RepresentativeTests(unittest.TestCase):
    def test_confirmed_queue_is_visible_with_later_notes_and_callback_disclaimer(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); generate(root)
            db = root / 'test.sqlite'; load_database(root / 'runtime', db)
            state = start(); state['answers']['elaborate'] = 'The merchant charged me twice.'
            state['step'] = 'satisfaction'
            submit(state, 'No, I need more help')
            submit(state, 'Yes, request human assistance')
            cid, revision = save_note(state, 'handoff_confirm', 'Yes, request human assistance', database=db)
            self.assertIn('registered mobile number shortly', state['messages'][-1][1])
            self.assertIn('no callback has been scheduled', state['messages'][-1][1])
            self.assertEqual(list_handoffs('C-002', db, principal=demo_staff()), [])
            original = list_handoffs(database=db, principal=demo_staff())[0]['summary_json']
            save_note(state, 'follow_up_update', 'I now have the receipt.', cid, revision, database=db)
            self.assertEqual(original, list_handoffs(database=db, principal=demo_staff())[0]['summary_json'])
            with patch.dict('os.environ', {'CONCERNS_DATABASE': str(db), 'CONCERN_EXTRACTION_MODE': 'deterministic', 'EVIDENCE_PROPOSER_MODE': 'deterministic'}):
                app = AppTest.from_file('app.py', default_timeout=15).run()
                app.session_state['staff_principal'] = demo_staff()
                app.radio[0].set_value('Representative workspace').run()
                self.assertEqual(app.title[0].value, 'Representative workspace')
                self.assertTrue(any('I now have the receipt.' in x.value for x in app.markdown))
                self.assertTrue(any('The merchant charged me twice.' in x.value for x in app.markdown))
                self.assertFalse(app.exception)

    def test_empty_queue_is_explained(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); generate(root)
            db = root / 'test.sqlite'; load_database(root / 'runtime', db)
            with patch.dict('os.environ', {'CONCERNS_DATABASE': str(db)}):
                app = AppTest.from_file('app.py', default_timeout=15).run()
                app.session_state['staff_principal'] = demo_staff()
                app.radio[0].set_value('Representative workspace').run()
                self.assertTrue(any('No confirmed assistance requests' in x.value for x in app.info))
                self.assertFalse(app.exception)

    def test_staff_login_is_required_and_password_is_cleared(self):
        import hashlib
        token = 'synthetic-staff-token-for-ui-testing-0001'
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); generate(root)
            db = root / 'test.sqlite'; load_database(root / 'runtime', db)
            env = {'CONCERNS_DATABASE': str(db), 'STAFF_ACCESS_TOKEN_SHA256': hashlib.sha256(token.encode()).hexdigest(), 'STAFF_ALLOWED_CUSTOMERS': 'C-001', 'CONCERN_EXTRACTION_MODE': 'deterministic'}
            with patch.dict('os.environ', env):
                app = AppTest.from_file('app.py', default_timeout=15).run()
                app.radio[0].set_value('Representative workspace').run()
                self.assertTrue(any(t.label == 'Staff access token' for t in app.text_input))
                self.assertFalse(any('No confirmed assistance requests' in i.value for i in app.info))
                app.text_input[0].set_value(token)
                next(b for b in app.button if b.label == 'Sign in').click().run()
                self.assertTrue(any('No confirmed assistance requests' in i.value for i in app.info))
                self.assertNotIn(token, str(app.session_state))
                next(b for b in app.button if b.label == 'Sign out').click().run()
                self.assertTrue(any(t.label == 'Staff access token' for t in app.text_input))
                self.assertFalse(app.exception)
