from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from conversation import start, submit, choices, OPTIONS
from concern_extraction import extract
from intake import normalise, missing_field
from domain import search_transactions
from scripts.generate_data import generate
from scripts.load_database import load_database


def begin(option, description):
    s = start()
    for text in [OPTIONS[option], 'CARD-001', description]:
        submit(s, text)
    return s


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); generate(root, cards_per_customer=2)
        self.db = root / 'test.sqlite'; load_database(root / 'runtime', self.db)
        self.env = patch.dict('os.environ', {'CONCERNS_DATABASE': str(self.db), 'CONCERN_EXTRACTION_MODE': 'deterministic'})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_wrong_amount_missing_only_date_and_confirmation_before_query(self):
        s = begin(3, 'I was charged £10 instead of £8')
        self.assertEqual(s['intake']['charged_amount'], '10.00')
        self.assertEqual(s['intake']['expected_amount'], '8.00')
        self.assertEqual(s['pending_search_field'], 'transaction_date')
        with patch('sqlite3.connect') as connect:
            self.assertEqual(search_transactions(s), ())
            connect.assert_not_called()
        submit(s, '18-10-2026')
        self.assertEqual(s['step'], 'search_confirm')
        self.assertIn('18-10-2026', s['messages'][-1][1])
        self.assertEqual(search_transactions(s), ())
        submit(s, 'Confirm and search')
        self.assertEqual(s['step'], 'transaction')
        self.assertEqual(search_transactions(s), ())
        self.assertIn('Change search details', choices(s))

    def test_two_matching_transactions_and_skip_already_supplied_expected_amount(self):
        s = begin(3, 'I was charged INR 42 instead of INR 40 on 15-10-2026')
        self.assertEqual(s['step'], 'search_confirm')
        submit(s, 'Confirm and search')
        self.assertEqual({t.reference for t in search_transactions(s)}, {'TX-1003', 'TX-1004'})
        submit(s, 'TX-1003')
        self.assertEqual(s['step'], 'receipt')
        self.assertEqual(s['answers']['expected_amount'], 'INR 40.00')

    def test_model_date_mislabelled_as_merchant_does_not_hide_matches(self):
        text = 'I was charged INR 42 instead of INR 40 on 15-10-2026'
        for span in ('15-10-2026', 'on 15-10-2026', 'INR 42'):
            with self.subTest(span=span), patch.dict('os.environ', {'CONCERN_EXTRACTION_MODE': 'ollama'}):
                response = {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({'entities': [{'field': 'merchant', 'span': span}]})}}
                with patch('concern_extraction.local_chat', return_value=response):
                    s = start()
                    for message in (OPTIONS[3], 'CARD-001'):
                        submit(s, message)
                    submit(s, text, extractor=extract)
                self.assertNotIn('merchant', s['intake'])
                self.assertIn('merchant', s['extraction_trace'][-1]['rejected_fields'])
                submit(s, 'Confirm and search')
                self.assertEqual({t.reference for t in search_transactions(s)}, {'TX-1003', 'TX-1004'})

    def test_edit_invalidates_confirmation_and_amount_not_expected_used_for_search(self):
        s = begin(3, 'charged INR 42 instead of INR 8 on 15-10-2026')
        submit(s, 'Edit details')
        self.assertEqual(s['step'], 'elaborate')
        self.assertFalse(s['search_confirmed'])
        self.assertEqual(search_transactions(s), ())
        submit(s, 'charged INR 8.50 instead of INR 8 on 17-10-2026')
        submit(s, 'Confirm and search')
        self.assertEqual([t.reference for t in search_transactions(s)], ['TX-1001'])
        s['intake']['charged_amount'] = '42.00'
        self.assertEqual(search_transactions(s), ())

    def test_cancellation_and_refund_dates_are_not_purchase_dates(self):
        s = begin(1, 'I cancelled on 01-10-2026 but was charged INR 12.99')
        self.assertEqual(s['intake']['cancellation_date'], '2026-10-01')
        self.assertEqual(s['pending_search_field'], 'transaction_date')
        s = begin(4, 'My refund of INR 20 was processed on 18-10-2026')
        self.assertEqual(s['intake']['refund_date'], '2026-10-18')
        self.assertEqual(s['intake']['refund_amount'], '20.00')
        self.assertNotIn('original_amount', s['intake'])
        self.assertEqual(s['pending_search_field'], 'original_date')

    def test_partial_refund_uses_original_purchase(self):
        s = begin(4, 'My refund of INR 20 was processed on 18-10-2026. My original purchase was INR 42 on 15-10-2026')
        self.assertEqual(s['step'], 'search_confirm')
        submit(s, 'Confirm and search')
        self.assertEqual({t.reference for t in search_transactions(s)}, {'TX-1003', 'TX-1004'})

    def test_merchant_is_context_only_and_cannot_filter_or_replace_amount(self):
        s = begin(0, 'Payment on 15-10-2026')
        s['intake']['merchant'] = 'An unrelated merchant'
        self.assertEqual(missing_field(s), 'identifier')
        submit(s, 'Another merchant')
        self.assertEqual(s['step'], 'search_details')
        submit(s, 'INR 42')
        self.assertNotIn('An unrelated merchant', s['messages'][-1][1])
        submit(s, 'Confirm and search')
        self.assertEqual({t.reference for t in search_transactions(s)}, {'TX-1003', 'TX-1004'})

    def test_date_validation_and_range(self):
        s = begin(0, 'I do not recognise this payment')
        submit(s, '31-02-2026'); self.assertEqual(s['step'], 'search_details')
        submit(s, '21-10-2026'); self.assertEqual(s['step'], 'search_details')
        submit(s, '18-10-2026 to 15-10-2026'); self.assertNotIn('transaction_date', s['intake'])
        submit(s, '15-10-2026 to 17-10-2026')
        self.assertEqual(s['pending_search_field'], 'identifier')
        submit(s, 'INR 42')
        self.assertEqual(s['step'], 'search_confirm')
        submit(s, 'Confirm and search')
        self.assertEqual(len(search_transactions(s)), 2)

    def test_ambiguous_currency_and_unknown_details(self):
        s = begin(3, 'I was charged $10 instead of $8 on 18-10-2026')
        self.assertEqual(s['step'], 'search_confirm')
        self.assertNotIn('charged_currency', s['intake'])
        self.assertIn('across currencies', s['messages'][-1][1])
        s = begin(0, 'I am unsure')
        submit(s, 'I don’t know / need help')
        self.assertEqual(s['step'], 'handoff_confirm')

    def test_unknown_currency_matches_multiple_currencies_and_known_currency_filters(self):
        import sqlite3
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE transactions SET currency='USD' WHERE transaction_id='TX-1004'")
        for option in (0, 1, 2, 3, 4):
            with self.subTest(option=option):
                text = 'Original purchase was 42 on 15-10-2026' if option == 4 else 'Charged 42 on 15-10-2026'
                s = begin(option, text)
                self.assertEqual(s['step'], 'search_confirm')
                submit(s, 'Confirm and search')
                results = search_transactions(s)
                self.assertEqual({t.reference for t in results}, {'TX-1003', 'TX-1004'})
                self.assertEqual({t.amount for t in results}, {'INR 42.00', 'USD 42.00'})
        s = begin(3, 'Charged INR 42 on 15-10-2026')
        submit(s, 'Confirm and search')
        self.assertEqual([t.reference for t in search_transactions(s)], ['TX-1003'])

    def test_saved_currency_question_can_be_skipped(self):
        s = begin(3, 'Charged 42 on 15-10-2026')
        s['step'] = 'search_details'
        s['pending_search_field'] = 'charged_currency'
        submit(s, 'I don’t know / need help')
        self.assertEqual(s['step'], 'search_confirm')
        submit(s, 'Confirm and search')
        self.assertEqual(len(search_transactions(s)), 2)

    def test_other_issue_avoids_unnecessary_search(self):
        s = begin(5, 'I need help with my address')
        self.assertEqual(s['step'], 'other_transaction')
        with patch('sqlite3.connect') as connect:
            submit(s, 'No')
            connect.assert_not_called()
        self.assertEqual(s['decision']['reason'], 'OUTSIDE_DEMO_SCOPE')

    def test_search_failure_is_not_no_match(self):
        import sqlite3
        s = begin(0, 'Payment reference TX-1001')
        submit(s, 'Confirm and search')
        with patch('domain.search_transactions', side_effect=sqlite3.OperationalError('test')), patch('conversation.search_transactions', side_effect=sqlite3.OperationalError('test')):
            choices(s)
            self.assertEqual(s['search_status'], 'UNAVAILABLE')
            submit(s, 'TX-1001')
            self.assertNotIn('transaction', s['answers'])

    def test_streamlit_requires_confirmation_before_any_search(self):
        from streamlit.testing.v1 import AppTest
        import conversation
        with patch('conversation.search_transactions', wraps=conversation.search_transactions) as conversation_search, patch('domain.search_transactions', wraps=search_transactions) as ui_search:
            app = AppTest.from_file('app.py').run()
            next(b for b in app.button if b.label == OPTIONS[3]).click().run()
            next(b for b in app.button if b.label.startswith('Demo card CARD-001 ')).click().run()
            app.chat_input[0].set_value('I was charged INR 42 instead of INR 40 on 15-10-2026').run()
            self.assertEqual(app.session_state.conversation['step'], 'search_confirm')
            self.assertEqual(conversation_search.call_count, 0)
            self.assertEqual(ui_search.call_count, 0)
            self.assertFalse(any(b.label.startswith('TX-') for b in app.button))
            next(b for b in app.button if b.label == 'Confirm and search').click().run()
            self.assertTrue(any(b.label.startswith('TX-1003') for b in app.button))
            next(b for b in app.button if b.label.startswith('TX-1003')).click().run()
            self.assertEqual(app.session_state.conversation['step'], 'receipt')
            self.assertFalse(app.exception)


class ExtractionTests(unittest.TestCase):
    def test_ollama_receives_description_and_validates_source_spans(self):
        text = 'I was charged 10 instead of 8 on 18-10-2026'
        def transport(payload, timeout):
            self.assertEqual(payload['model'], 'smollm2:135m')
            self.assertFalse(payload['stream'])
            self.assertIn(text, payload['messages'][1]['content'])
            return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({'entities': [
                {'field': 'charged_currency', 'span': 'GBP'},  # invented: reject
                {'field': 'charged_amount', 'span': '8'},  # wrong role: reject
                {'field': 'merchant', 'span': 'Northstar'},  # invented: reject
            ]})}}
        with patch.dict('os.environ', {'CONCERN_EXTRACTION_MODE': 'ollama'}):
            fields, _, trace = extract(text, 'wrong_amount', transport=transport)
        self.assertEqual(fields['charged_amount'], '10.00')
        self.assertEqual(fields['expected_amount'], '8.00')
        self.assertNotIn('charged_currency', fields)
        self.assertEqual(trace['status'], 'OLLAMA_EXTRACTED')
        self.assertIn('charged_amount', trace['rejected_fields'])

    def test_failure_and_relative_dates_do_not_invent_values(self):
        def failed(*_): raise TimeoutError('private details')
        with patch.dict('os.environ', {'CONCERN_EXTRACTION_MODE': 'ollama'}):
            fields, _, trace = extract('I was charged GBP 10 yesterday', 'wrong_amount', transport=failed)
        self.assertEqual(fields['charged_amount'], '10.00')
        self.assertNotIn('transaction_date', fields)
        self.assertEqual(trace['status'], 'EXTRACTION_UNAVAILABLE_GUIDED_FALLBACK')
        self.assertNotIn('private', json.dumps(trace))

    def test_conflicting_explicit_amounts_require_clarification(self):
        fields, _, _ = extract('I was charged GBP 10. I was charged GBP 12.', 'wrong_amount', use_ollama=False)
        self.assertNotIn('charged_amount', fields)

    def test_date_fragments_cannot_be_invented_as_amounts(self):
        text = 'My payment was on 18-10-2026'
        def transport(*_):
            return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({'entities': [{'field': 'charged_amount', 'span': '10'}]})}}
        with patch.dict('os.environ', {'CONCERN_EXTRACTION_MODE': 'ollama'}):
            fields, _, _ = extract(text, 'wrong_amount', transport=transport)
        self.assertNotIn('charged_amount', fields)

    def test_uncertain_explicit_date_is_asked_again(self):
        fields, _, trace = extract('I was charged GBP 10 around 18-10-2026', 'wrong_amount', use_ollama=False)
        self.assertNotIn('transaction_date', fields)
        self.assertIn('transaction_date', trace['uncertain_fields'])
