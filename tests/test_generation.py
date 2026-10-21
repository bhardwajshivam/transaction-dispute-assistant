import json
from pathlib import Path
import tempfile
import unittest
from scripts.generate_data import generate, validate
from domain import load_transactions


class GenerationTests(unittest.TestCase):
    def test_reproducible_and_seed_sensitive(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root) / 'a', Path(root) / 'b'
            generate(a, seed=42)
            generate(b, seed=42)
            self.assertEqual((a / 'manifest.json').read_bytes(), (b / 'manifest.json').read_bytes())
            # Unrelated evaluation artefacts must not contaminate source hashes.
            (b / 'unrelated_report.json').write_text('{"result": "not generator owned"}')
            generate(b, seed=42)
            self.assertEqual((a / 'manifest.json').read_bytes(), (b / 'manifest.json').read_bytes())
            generate(b, seed=43)
            self.assertNotEqual((a / 'runtime/transactions.json').read_bytes(), (b / 'runtime/transactions.json').read_bytes())

    def test_labels_separated_and_references_valid(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            report = generate(output)
            self.assertEqual(report['errors'], [])
            runtime = ''.join(p.read_text() for p in (output / 'runtime').glob('*.json'))
            self.assertNotIn('expected_next_question', runtime)
            dev = json.loads((output / 'development/expected_outcomes.json').read_text())
            evaluation = json.loads((output / 'evaluation/expected_outcomes.json').read_text())
            self.assertFalse({r['transaction_id'] for r in dev} & {r['transaction_id'] for r in evaluation})
            data = {p.stem: json.loads(p.read_text()) for p in (output / 'runtime').glob('*.json')}
            data['transactions'][0]['account_id'] = 'MISSING'
            self.assertIn('Broken transaction reference', validate(data)['errors'])

    def test_account_scope(self):
        a = {t.reference for t in load_transactions('A-001')}
        b = {t.reference for t in load_transactions('A-002', customer_id='C-002')}
        self.assertTrue(a and b)
        self.assertFalse(a & b)
        self.assertEqual(load_transactions('NO-ACCESS'), ())
