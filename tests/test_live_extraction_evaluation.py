import json
from pathlib import Path
import tempfile
import unittest
from ollama_backend import BackendError
from scripts.evaluate_live_extraction import metrics, run


class LiveEvaluationTests(unittest.TestCase):
    def test_wrong_values_are_not_correct_and_empty_precision_is_undefined(self):
        result = metrics({'charged_amount':'8.00'}, {'charged_amount':'10.00'})
        self.assertFalse(result['exact_match'])
        self.assertEqual(result['correct_fields'], 0)
        self.assertTrue(result['unsupported_or_wrong_fields'])

    def test_outage_is_not_scored_as_model_success(self):
        def offline(*_):
            raise BackendError('OLLAMA_UNAVAILABLE')
        with tempfile.TemporaryDirectory() as root:
            summary = run(root, offline)
            self.assertEqual(summary['status'], 'UNAVAILABLE_OR_INVALID')
            self.assertEqual(summary['model']['exact_matches'], 0)
            self.assertEqual(summary['valid_model_responses'], 0)
            rows = json.loads((Path(root)/'results.json').read_text())
            self.assertTrue(all(r['error_code']=='OLLAMA_UNAVAILABLE' for r in rows))

    def test_empty_model_cannot_take_credit_for_parser_success(self):
        def empty(*_):
            return {'done':True, 'done_reason':'stop', 'message':{'role':'assistant','content':'{"entities":[]}'}}
        with tempfile.TemporaryDirectory() as root:
            summary = run(root, empty)
            self.assertEqual(summary['status'], 'MEASURED')
            self.assertEqual(summary['model']['field_recall'], 0)
            self.assertGreater(summary['combined']['exact_matches'], summary['model']['exact_matches'])
            self.assertEqual(summary['parser']['exact_matches'], summary['combined']['exact_matches'])
            self.assertIn('transaction_date', summary['field_role_breakdown'])
            self.assertIn('prompt_version', summary['extraction_contract'])
            rows = json.loads((Path(root)/'results.json').read_text())
            reference = next(r for r in rows if r['id']=='reference')
            self.assertEqual(reference['model_only'], {})
            self.assertEqual(reference['combined'], {'transaction_reference':'TX-1023'})
