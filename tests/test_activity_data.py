import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.generate_activity_data import generate,quality
from scripts.evaluate_activity_corpus import run
from scripts.load_database import load_database


class RichActivityDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'corpus'
        self.report=generate(self.root,customers=4,history_size=80)

    def read(self,path):
        return json.loads((self.root/path).read_text())

    def test_reproducible_source_manifest_independent_of_results(self):
        before=(self.root/'manifest.json').read_bytes()
        run(self.root)
        generate(self.root,customers=4,history_size=80)
        self.assertEqual(before,(self.root/'manifest.json').read_bytes())
        other=Path(self.tmp.name)/'other'
        generate(other,seed=1,customers=4,history_size=80)
        self.assertNotEqual(self.read('runtime/transactions.json'),json.loads((other/'runtime/transactions.json').read_text()))

    def test_customer_disjoint_and_labels_outside_runtime(self):
        dev=self.read('development/activity_cases.json'); evaluation=self.read('evaluation/activity_cases.json')
        self.assertFalse({c['customer_id'] for c in dev}&{c['customer_id'] for c in evaluation})
        runtime=''.join(p.read_text() for p in (self.root/'runtime').glob('*.json'))
        for forbidden in ('authorisation_truth','expected','legitimate_large_purchase','spending_scale','profile'):
            self.assertNotIn(forbidden,runtime)
        self.assertEqual(self.report['errors'],[])
        self.assertEqual(set(self.report['currency_balance']),{'INR'})
        for table in ('accounts','transactions','receipts','refunds','credits'):
            self.assertEqual({row['currency'] for row in self.read('runtime/'+table+'.json')},{'INR'})
        self.assertGreater(self.report['missing_receipt_count'],0)
        self.assertGreater(self.report['missing_order_references'],0)
        self.assertGreater(self.report['delayed_presentment_count'],0)

    def test_known_legitimate_exceptions_have_matching_receipts(self):
        tx={t['transaction_id']:t for t in self.read('runtime/transactions.json')}
        receipts={r['transaction_id']:r for r in self.read('runtime/receipts.json')}
        for spec in self.read('design/runtime_exceptions.json'):
            row=tx[spec['transaction_id']]
            if spec['construction']=='legitimate_large_purchase':
                self.assertEqual(receipts[row['transaction_id']]['agreed_amount_minor'],row['amount_minor'])
            elif spec['construction']=='repeated_same_order':
                self.assertTrue(row['order_reference'])
                self.assertEqual(sum(t['order_reference']==row['order_reference'] for t in tx.values()),2)

    def test_runtime_sql_import_and_timestamp_preservation(self):
        database=Path(self.tmp.name)/'rich.sqlite'
        load_database(self.root/'runtime',database)
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            record=json.loads(db.execute('SELECT evidence_json FROM transactions LIMIT 1').fetchone()[0])
            self.assertIn('occurred_at',record)
            self.assertIn('merchant_category',record)
            self.assertEqual(db.execute('SELECT count(*) FROM transactions').fetchone()[0],self.report['transaction_count'])

    def test_eval_exposes_non_identifiability_not_fraud_accuracy(self):
        for split in ('development','evaluation'):
            result=run(self.root,split)
            self.assertEqual(result['case_count'],26)
            self.assertEqual(result['passed'],26)
            self.assertEqual(result['authorisation_vs_anomaly']['authorised:flagged'],2)
            self.assertEqual(result['authorisation_vs_anomaly']['unauthorised:not_flagged'],2)

    def test_quality_catches_scope_and_timestamp_defects(self):
        data={p.stem:json.loads(p.read_text()) for p in (self.root/'runtime').glob('*.json')}
        splits={s:self.read(s+'/activity_cases.json') for s in ('development','evaluation')}
        data['transactions'][0]['card_id']='WRONG'
        data['transactions'][0]['occurred_at']='2000-01-01T00:00:00+00:00'
        errors=quality(data,splits)['errors']
        self.assertIn('Card/account mismatch',errors)
        self.assertIn('Timestamp/date mismatch',errors)

    def test_generator_refuses_operational_database_directory(self):
        (self.root/'active.sqlite').touch()
        with self.assertRaises(ValueError):
            generate(self.root,customers=4,history_size=80)


if __name__=='__main__':
    unittest.main()
