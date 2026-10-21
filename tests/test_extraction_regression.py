import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from concern_extraction import extract
from privacy import protect


class ExtractionRegressionTests(unittest.TestCase):
    def test_iso_date_after_amount_does_not_become_an_amount_fragment(self):
        fields, _, trace = extract('Charged INR 85 on 2026-10-07, expected INR 75.', 'wrong_amount', False)
        self.assertEqual(fields, {'charged_amount':'85.00', 'charged_currency':'INR',
                                 'transaction_date':'2026-10-07', 'expected_amount':'75.00', 'expected_currency':'INR'})
        self.assertEqual(trace['conflicting_fields'], [])

    def test_date_formats_and_amount_counterfactuals(self):
        for date in ('2026-10-07', '07-10-2026', '7 October 2026', '7 Oct 2026'):
            for amount in (85, 86):
                with self.subTest(date=date, amount=amount):
                    fields, _, _ = extract(f'Charged INR {amount} on {date}.', 'wrong_amount', False)
                    self.assertEqual(fields['charged_amount'], f'{amount}.00')
                    self.assertEqual(fields['transaction_date'], '2026-10-07')

    def test_only_date_digits_do_not_supply_an_amount(self):
        for date in ('2026-10-07', '07-10-2026', '7 October 2026'):
            fields, _, _ = extract(f'Payment on {date}.', 'unrecognised', False)
            self.assertEqual(fields, {'transaction_date':'2026-10-07'})

    def test_privacy_keeps_iso_date_and_amount_but_removes_identifiers(self):
        text = 'Email alex@example.com card 4111111111111111 phone +91 9876543210. Charged INR 85 on 2026-10-07.'
        protected = protect(text)
        for pii in ('alex@example.com', '4111111111111111', '9876543210'):
            self.assertNotIn(pii, protected.text)
        fields, _, _ = extract(text, 'wrong_amount', False)
        self.assertEqual(fields, {'charged_amount':'85.00', 'charged_currency':'INR', 'transaction_date':'2026-10-07'})

    def test_deterministic_and_invalid_mode_never_contact_model(self):
        for mode in ('deterministic', 'invalid'):
            with patch.dict(os.environ):
                os.environ.pop('CONCERN_EXTRACTION_MODE', None)
                if mode: os.environ['CONCERN_EXTRACTION_MODE'] = mode
                with patch('concern_extraction.local_chat') as transport:
                    fields, _, trace = extract('Charged INR 85 on 2026-10-07.', 'wrong_amount')
                    transport.assert_not_called()
                    self.assertEqual(trace['status'], 'DETERMINISTIC')
                    self.assertIsNone(trace['model'])
                    self.assertEqual(fields['charged_amount'], '85.00')

    def test_all_fixed_extraction_probes_without_model(self):
        cases = json.loads((Path(__file__).resolve().parents[1]/'evaluation/extraction_cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']):
                fields, _, _ = extract(case['text'], case['kind'], False)
                self.assertEqual(fields, case['expected'])

    def test_default_attempts_local_model_and_validates_customer_spans(self):
        with patch.dict(os.environ):
            os.environ.pop('CONCERN_EXTRACTION_MODE', None)
            response = {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({'entities': [{'field': 'merchant', 'span': 'Northstar'}]})}}
            with patch('concern_extraction.local_chat', return_value=response) as transport:
                fields, _, trace = extract('Northstar charged INR 85 on 07-10-2026.', 'unrecognised')
                transport.assert_called_once()
                self.assertEqual(fields['merchant'], 'Northstar')
                self.assertEqual(trace['field_sources']['merchant'], ['ollama'])
                self.assertEqual(trace['status'], 'OLLAMA_EXTRACTED')
