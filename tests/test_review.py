from tests.support import prepare_reference
import json
from pathlib import Path
import tempfile
import unittest
from conversation import start, submit, OPTIONS, finish, prompt, QUESTIONS
from review import update_review, REASONS
from concerns import save_note, get_concern, connection, summary
from scripts.generate_data import generate
from scripts.load_database import load_database


class ReviewTests(unittest.TestCase):
    def test_new_review_signal_removes_only_pending_recognition_prompt(self):
        from review import offer_review
        s = start()
        question = QUESTIONS['recognise'][0]
        s['messages'] += [('assistant', question), ('user', 'No'), ('assistant', 'Earlier exchange preserved.')]
        historical = list(s['messages'])
        s['step'] = 'recognise'
        prompt(s)
        s['review_signals'] = ['UNUSUAL_ACTIVITY_REVIEW']
        offer_review(s)
        prompt(s)
        self.assertEqual(s['step'], 'handoff_confirm')
        self.assertEqual(s['messages'][:len(historical)], historical)
        self.assertNotIn(question, [text for _, text in s['messages'][len(historical):]])

    def test_required_review_skips_recognition_and_ignores_stale_reply(self):
        for entry in ('prompt', 'submit'):
            with self.subTest(entry=entry):
                s = start()
                s['step'] = 'recognise'
                s['review_signals'] = ['UNUSUAL_ACTIVITY_REVIEW']
                if entry == 'prompt':
                    prompt(s)
                else:
                    submit(s, 'Yes')
                self.assertEqual(s['step'], 'handoff_confirm')
                self.assertNotIn('recognise', s['answers'])
                self.assertNotIn(QUESTIONS['recognise'][0], [text for _, text in s['messages']])

    def test_required_cannot_be_resolved_or_cleared_by_decline(self):
        s = start()
        for text in [OPTIONS[0], 'CARD-001', 'I do not recognise this payment.', 'TX-1001', 'No', 'No', 'Yes']:
            if text.startswith("TX-"):
                prepare_reference(s, text)
            submit(s, text)
        self.assertEqual(s['step'], 'handoff_confirm')
        self.assertEqual(s['review_requirement'], 'REQUIRED')
        submit(s, 'Yes, my concern is resolved')
        self.assertEqual(s['step'], 'handoff_confirm')
        self.assertNotEqual(s['customer_resolution'], 'RESOLVED')
        submit(s, 'Not now')
        self.assertEqual(s['handoff_status'], 'DECLINED')
        self.assertEqual(s['review_requirement'], 'REQUIRED')
        self.assertEqual(s['concern_status'], 'review_required')

    def test_signals_and_irrelevant_text(self):
        for signal in REASONS:
            with self.subTest(signal=signal):
                s = start()
                s['review_signals'] = [signal]
                finish(s, 'TEST', 'Test adapter result')
                self.assertEqual(s['step'], 'handoff_confirm')
                self.assertIn(signal, s['review_reason_codes'])
        s = start()
        s['answers']['additional_statements'] = ['POLICY_CONFLICT']
        update_review(s)
        self.assertEqual(s['review_requirement'], 'NOT_REQUIRED')

    def test_optional_assistance_does_not_imply_required_review(self):
        s = start()
        finish(s, 'BILLING_REVIEW', 'Review suggested')
        submit(s, 'No, I need more help')
        self.assertEqual(s['customer_resolution'], 'NOT_RESOLVED')
        self.assertEqual(s['review_requirement'], 'NOT_REQUIRED')
        self.assertEqual(s['handoff_status'], 'AWAITING_CONFIRMATION')

    def test_sticky_storage_and_migration(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            generate(root)
            db = root / 'test.sqlite'
            load_database(root / 'runtime', db)
            s = start()
            s['reported_card_risk'] = True
            update_review(s)
            cid, rev = save_note(s, 'urgent_card_risk', 'Card missing', database=db)
            # Later state attempts to omit all triggering evidence and clear the requirement.
            replacement = start()
            replacement['step'] = 'satisfaction'
            save_note(replacement, 'follow_up', 'Looks fine now', cid, rev, database=db)
            row, _ = get_concern(cid, database=db)
            stored = json.loads(row['state_json'])
            self.assertEqual(stored['review_requirement'], 'REQUIRED')
            self.assertEqual(stored['step'], 'handoff_confirm')
            with connection(db) as conn:
                flag = conn.execute('SELECT * FROM concern_review WHERE concern_id=?', (cid,)).fetchone()
                self.assertEqual(flag['review_requirement'], 'REQUIRED')
            self.assertIn('Specialist review: REQUIRED', summary(cid, database=db))
