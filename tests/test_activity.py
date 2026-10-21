from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activity import evaluate, assess, review_decision, attach
from scripts.evaluate_activity import transaction, history, scenarios, run
from scripts.generate_data import generate
from scripts.load_database import load_database


class ActivityRulesTests(unittest.TestCase):
    def test_constructed_counterfactuals(self):
        for case in scenarios():
            with self.subTest(case=case['scenario_id']):
                result = evaluate(case['transaction'], case['history'])
                actual = {'reason_codes': sorted(s['reason_code'] for s in result['signals']), 'status': result['status'], 'route': review_decision(result)['route']}
                self.assertEqual(actual, case['expected'])

    def test_minimum_amount_floor(self):
        result = evaluate(transaction(amount=4999), history(amount=100))
        self.assertEqual(result['signals'], [])
        result = evaluate(transaction(amount=5000), history(amount=100))
        self.assertEqual(result['signals'][0]['reason_code'], 'AMOUNT_ABOVE_HISTORICAL_BASELINE')

    def test_pending_other_card_and_old_rows_excluded(self):
        extra = [transaction('PENDING',1,'2026-10-19',status='Pending',posted_date=None),
                 transaction('OTHER',1,'2026-10-19',card_id='CARD-002'), transaction('OLD',1,'2025-01-01')]
        a = evaluate(transaction(), history())
        b = evaluate(transaction(), history()+extra)
        self.assertEqual(a['history_evidence'], b['history_evidence'])
        self.assertEqual(a['evidence_id'], b['evidence_id'])

    def test_duplicate_history_rows_abstain(self):
        rows = history()
        result = evaluate(transaction(), rows+[rows[0]])
        self.assertEqual(result['invalid_history_count'], 1)
        self.assertEqual(result['checks']['amount']['status'], 'INSUFFICIENT_DATA')

    def test_fractional_median_boundary(self):
        rows = history(2000)
        for row in rows[5:]:
            row['amount_minor'] = 2001
        self.assertEqual(evaluate(transaction(amount=6001), rows)['signals'], [])
        self.assertEqual(evaluate(transaction(amount=6002), rows)['signals'][0]['baseline_median_minor'], 2000.5)

    def test_invalid_target_never_clean(self):
        for changes in ({'purchase_date':'invalid'}, {'amount_minor':True}, {'currency':'gbp'}, {'posted_date':None}):
            result = evaluate(transaction(**changes), history())
            self.assertEqual(result['status'], 'INSUFFICIENT_DATA')

    def test_reproducible_evaluation_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            a = run(Path(root)/'a'); b = run(Path(root)/'b')
            self.assertEqual(a, b)
            self.assertEqual(a['passed'], 16)
            self.assertEqual(a['false_review_flags'], 0)
            self.assertEqual(a['missed_constructed_review_flags'], 0)
            self.assertEqual(a['data_quality']['duplicate_input_cases'], 0)


class ActivityAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        generate(root)
        self.db = root/'test.sqlite'
        load_database(root/'runtime', self.db)

    def test_ownership_and_card_checked(self):
        self.assertEqual(assess('TX-1003','CARD-002',database=self.db)['status'], 'FORBIDDEN_OR_NOT_FOUND')
        self.assertEqual(assess('TX-1003','CARD-001','C-002',self.db)['status'], 'FORBIDDEN_OR_NOT_FOUND')
        self.assertIn(assess('TX-1003','CARD-001',database=self.db)['status'], ('ASSESSED','PARTIAL'))

    def test_service_unavailable_not_no_match(self):
        result = assess('TX-1003','CARD-001',database=Path(self.tmp.name)/'missing.sqlite')
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertEqual(result['reason_code'], 'ACTIVITY_HISTORY_UNAVAILABLE')

    def test_bad_configuration_abstains(self):
        with patch('activity.RULES_PATH', Path(self.tmp.name)/'missing.json'):
            self.assertEqual(assess('TX-1003','CARD-001',database=self.db)['reason_code'], 'ACTIVITY_RULES_UNAVAILABLE')

    def test_signal_recommends_review_without_action(self):
        from review import update_review
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE transactions SET amount_minor=1000 WHERE card_id='CARD-001'")
            db.execute("UPDATE transactions SET purchase_date='2026-10-20',posted_date='2026-10-20',amount_minor=100000 WHERE transaction_id='TX-1003'")
        state = {'answers': {'transaction':'TX-1003','card_id':'CARD-001'}}
        attach(state,database=self.db)
        update_review(state)
        self.assertEqual(state['activity_review']['route'], 'RECOMMEND_SPECIALIST_REVIEW')
        self.assertEqual(state['review_requirement'], 'REQUIRED')
        self.assertNotIn('decision',state)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM cases').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM actions').fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
