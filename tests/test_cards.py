from tests.support import prepare_reference
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from domain import list_cards, selected_transactions
from conversation import start, submit, choices, OPTIONS
from concerns import save_note
from evidence_agent import read_tool
from scripts.generate_data import generate
from scripts.load_database import load_database


class CardScopeTests(unittest.TestCase):
    def test_multiple_cards_filter_selection_tools_and_storage(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            generate(root, cards_per_customer=2)
            db = root / 'test.sqlite'
            load_database(root / 'runtime', db)
            with patch.dict('os.environ', {'CONCERNS_DATABASE': str(db)}):
                cards = list_cards()
                self.assertEqual({c['card_id'] for c in cards}, {'CARD-001', 'CARD-001-2'})
                s = start(); submit(s, OPTIONS[0])
                self.assertEqual(s['step'], 'card')
                submit(s, 'CARD-002')
                self.assertEqual(s['step'], 'card')
                submit(s, 'CARD-001-2')
                submit(s, 'I do not recognise a payment.')
                candidates = selected_transactions(s)
                self.assertTrue(candidates)
                self.assertNotIn('TX-1001', {t.reference for t in candidates})
                prepare_reference(s, candidates[0].reference)
                submit(s, 'TX-1001')
                self.assertEqual(s['step'], 'transaction')
                self.assertNotIn('transaction', s['answers'])
                submit(s, candidates[0].reference)
                self.assertEqual(s['step'], 'recognise')
                wrong = {'tool': 'verify_selected_transaction', 'gap': 'transaction', 'transaction_id': 'TX-1001'}
                self.assertEqual(read_tool(wrong, database=db, card_id='CARD-001-2')['status'], 'FORBIDDEN_OR_NOT_FOUND')
                s['answers']['transaction'] = 'TX-1001'
                with self.assertRaises(PermissionError):
                    save_note(s, 'transaction', 'TX-1001', database=db)
