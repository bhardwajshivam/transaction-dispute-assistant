from copy import deepcopy
from datetime import date,timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from clustering import config,evaluate,fit,assess,review_decision,attach
from scripts.generate_activity_data import generate
from scripts.load_database import load_database


def target(amount=2000,**changes):
    return dict(dict(transaction_id='T',account_id='A',card_id='CARD',purchase_date='2026-10-20',posted_date='2026-10-20',
                     status='Posted',amount_minor=amount,currency='INR',channel='Online',recurring=False,merchant_category='5311'),**changes)


def history():
    rows=[]
    for i in range(65):
        day=(date(2026,10,19)-timedelta(days=i)).isoformat()
        rows.append(target(amount=[1800,2000,2200,5000,5500][i%5],transaction_id=f'H-{i}',purchase_date=day,posted_date=day))
    return rows


class ClusterTests(unittest.TestCase):
    def test_lloyd_centres_and_convergence(self):
        centres,converged,_=fit([[0.],[1.],[9.],[10.]],2,40)
        self.assertTrue(converged)
        self.assertEqual(sorted(c[0] for c in centres),[.5,9.5])

    def test_ordinary_and_extreme_scores(self):
        ordinary=evaluate(target(),history())
        extreme=evaluate(target(1000000),history())
        self.assertEqual(ordinary['status'],'ASSESSED')
        self.assertFalse(ordinary['flagged'])
        self.assertTrue(extreme['flagged'])
        self.assertGreater(extreme['anomaly_score'],1)
        self.assertEqual(ordinary['model_id'],extreme['model_id'])
        self.assertEqual(ordinary['model'],extreme['model'])

    def test_fit_and_calibration_strictly_separated(self):
        r=evaluate(target(),history())
        train=r['model']['training_records']; calibration=r['model']['calibration_records']
        self.assertLess(max(t['posted_date'] for t in train),min(t['purchase_date'] for t in calibration))
        self.assertFalse({t['transaction_id'] for t in train}&{t['transaction_id'] for t in calibration})
        self.assertNotIn('T',{t['transaction_id'] for t in train+calibration})

    def test_future_same_day_other_currency_and_card_do_not_fit(self):
        expected=evaluate(target(),history())
        extras=[target(1000000,transaction_id='FUTURE',purchase_date='2026-10-21',posted_date='2026-10-21'),
                target(1000000,transaction_id='SAME'),target(1000000,transaction_id='OTHER',card_id='OTHER'),
                target(1000000,transaction_id='FX',purchase_date='2026-10-18',posted_date='2026-10-18',currency='GBP')]
        actual=evaluate(target(),history()+extras)
        self.assertEqual(expected['model'],actual['model'])

    def test_delayed_posting_does_not_leak_into_training(self):
        rows=history()
        cutoff=evaluate(target(),rows)['model']['training_before']
        rows[-1]['posted_date']='2026-10-19'
        r=evaluate(target(),rows)
        self.assertNotIn(rows[-1]['transaction_id'],{t['transaction_id'] for t in r['model']['training_records']})

    def test_calibration_does_not_fit_scaler_or_categories(self):
        rows=history(); before=evaluate(target(),rows)
        calibration_ids={r['transaction_id'] for r in before['model']['calibration_records']}
        for row in rows:
            if row['transaction_id'] in calibration_ids:
                row['amount_minor']=999999; row['merchant_category']='NEW'
        after=evaluate(target(),rows)
        for field in ('features','log_amount_mean','log_amount_scale','centres'):
            self.assertEqual(before['model'][field],after['model'][field])
        self.assertGreater(after['threshold'],before['threshold'])

    def test_insufficient_and_invalid_abstain(self):
        self.assertEqual(evaluate(target(),history()[:20])['reason_code'],'CLUSTER_HISTORY_TOO_SMALL')
        rows=history(); rows[0]['amount_minor']='wrong'
        self.assertEqual(evaluate(target(),rows)['status'],'INSUFFICIENT_DATA')
        self.assertEqual(evaluate(target(status='Pending',posted_date=None),history())['status'],'INSUFFICIENT_DATA')
        rows=history(); rows.append(deepcopy(rows[0]))
        self.assertEqual(evaluate(target(),rows)['reason_code'],'CLUSTER_FEATURES_INVALID')

    def test_same_date_history_cannot_fake_temporal_split(self):
        rows=history()
        for row in rows: row['purchase_date']=row['posted_date']='2026-10-18'
        self.assertEqual(evaluate(target(),rows)['reason_code'],'CLUSTER_TEMPORAL_SPLIT_TOO_SMALL')

    def test_deterministic_under_history_order(self):
        self.assertEqual(evaluate(target(),history()),evaluate(target(),list(reversed(history()))))

    def test_constant_history_and_unseen_category(self):
        rows=history()
        for row in rows: row['amount_minor']=2000
        result=evaluate(target(),rows)
        self.assertEqual(result['status'],'ASSESSED')
        self.assertEqual(len(result['model']['centres']),1)
        self.assertFalse(result['flagged'])
        different=evaluate(target(1000000,merchant_category='NEW'),rows)
        self.assertTrue(different['flagged'])
        self.assertIn('unseen_category',different['model']['features'])

    def test_default_shadow_and_separate_review_control(self):
        result=evaluate(target(1000000),history())
        self.assertTrue(result['flagged'])
        self.assertEqual(review_decision(result)['route'],'NO_ADDITIONAL_ROUTE')
        enabled=dict(config(),mode='recommend_review')
        result=evaluate(target(1000000),history(),enabled)
        self.assertEqual(review_decision(result)['route'],'RECOMMEND_SPECIALIST_REVIEW')
        state={'answers':{'transaction':'T','card_id':'CARD'}}
        with patch('clustering.assess',return_value=result): attach(state)
        self.assertIn('CLUSTER_ACTIVITY_REVIEW',state['review_signals'])
        self.assertNotIn('decision',state)
        self.assertNotIn('case_command',state)

    def test_nonconvergence_is_explicit(self):
        with patch('clustering.fit',return_value=([[0.]],False,1)):
            self.assertEqual(evaluate(target(),history())['reason_code'],'CLUSTER_DID_NOT_CONVERGE')


class ClusterAccessTests(unittest.TestCase):
    def test_database_scope_failures_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); generate(root/'corpus',customers=4,history_size=80)
            database=root/'test.sqlite'; load_database(root/'corpus/runtime',database)
            tx=json.loads((root/'corpus/runtime/transactions.json').read_text())[0]
            self.assertEqual(assess(tx['transaction_id'],tx['card_id'],'C-002',database)['status'],'FORBIDDEN_OR_NOT_FOUND')
            self.assertEqual(assess(tx['transaction_id'],'WRONG',database=database)['status'],'FORBIDDEN_OR_NOT_FOUND')
            self.assertEqual(assess('T','CARD',database=root/'absent.sqlite')['status'],'UNAVAILABLE')
            with patch('clustering.CONFIG_PATH',root/'absent.json'):
                self.assertEqual(assess('T','CARD',database=database)['reason_code'],'CLUSTER_CONFIG_UNAVAILABLE')
            from sqlite3 import connect
            with connect(database) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM actions').fetchone()[0],0)

    def test_chat_displays_score_and_shadow_boundary(self):
        from streamlit.testing.v1 import AppTest
        from conversation import start
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); generate(root/'corpus',customers=4,history_size=80)
            database=root/'test.sqlite'; load_database(root/'corpus/runtime',database)
            state=start(); state['clustering']=evaluate(target(1000000),history())
            with patch.dict(os.environ,{'CONCERNS_DATABASE':str(database),'CONCERN_EXTRACTION_MODE':'deterministic'}):
                app=AppTest.from_file('app.py'); app.session_state.conversation=state; app.run()
                self.assertFalse(app.exception)
                self.assertIn('Cluster-distance score',[m.label for m in app.metric])
                self.assertTrue(any('Observation mode' in m.value for m in app.markdown))

    def test_corpus_observations_reproducible_without_label_fitting(self):
        from scripts.evaluate_clustering import run
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); generate(root/'corpus',customers=4,history_size=120)
            first=run(root/'corpus'); second=run(root/'corpus')
            self.assertEqual(first,second)
            self.assertEqual(first['case_count'],26)
            self.assertEqual(len(first['separate_extreme_amount_probes']),2)
            self.assertTrue(all(r['flagged'] for r in first['separate_extreme_amount_probes']))


if __name__=='__main__': unittest.main()
