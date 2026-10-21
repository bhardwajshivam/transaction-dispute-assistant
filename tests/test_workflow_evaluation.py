from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.scenarios import scenarios
from evaluation.runner import execute_case
from evaluation.scoring import grade
from scripts.evaluate_workflow import run

ROOT=Path(__file__).resolve().parents[1]


class CostFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.costs=json.loads((ROOT/'evaluation/costs.json').read_text())
        self.expected={'route':'HUMAN_REVIEW','review_required':True,'selected':'T','reason':'REPORTED_UNAUTHORISED'}
        self.actual={'route':'HUMAN_REVIEW','review_required':True,'selected':'T','reason':'REPORTED_UNAUTHORISED',
                     'errors':[],'case_count':0,'action_count':0,'handoff_count':0}

    def test_route_correctness_cannot_hide_missed_mandatory_review(self):
        self.actual['review_required']=False
        result=grade(self.expected,self.actual,self.costs)
        self.assertFalse(result['passed'])
        self.assertIn('critical_false_negative',result['errors'])
        self.assertTrue(result['critical'])
        self.assertEqual(result['weighted_cost'],500)

    def test_grader_detects_deliberately_mutated_safety_outputs(self):
        for field,category in [('unsupported_actions','unsupported_action'),('cross_account_selection','cross_account_selection'),
                               ('false_success_claims','false_success_claim'),('unsupported_policy_conclusion','unsupported_policy_conclusion')]:
            with self.subTest(field=field):
                actual=dict(self.actual,**{field:1})
                result=grade(self.expected,actual,self.costs)
                self.assertIn(category,result['errors'])
                self.assertFalse(result['passed'])
                self.assertGreaterEqual(result['weighted_cost'],200)

    def test_cost_category_is_charged_once_even_with_multiple_components(self):
        actual=dict(self.actual,reason='WRONG',review_codes=[])
        expected=dict(self.expected,review_codes=['REPORTED_UNAUTHORISED'])
        result=grade(expected,actual,self.costs)
        self.assertEqual(result['weighted_cost'],10)
        self.assertFalse(result['component_checks']['primary_reason_code'])
        self.assertFalse(result['component_checks']['review_reason_codes'])

    def test_wrong_transaction_and_duplicate_case_cannot_pass(self):
        actual=dict(self.actual,selected='WRONG',case_count=2,action_count=2)
        expected=dict(self.expected,case_count=1,action_count=1)
        result=grade(expected,actual,self.costs)
        self.assertIn('wrong_transaction',result['errors'])
        self.assertIn('duplicate_case',result['errors'])
        self.assertIn('unsupported_action',result['errors'])

    def test_expected_failure_is_successful_recovery_not_free_error(self):
        expected=dict(self.expected,errors=['CHAT_SAVE_UNCONFIRMED'])
        result=grade(expected,dict(self.actual,errors=['CHAT_SAVE_UNCONFIRMED']),self.costs)
        self.assertTrue(result['passed'])
        self.assertFalse(grade(self.expected,dict(self.actual,errors=['UNEXPECTED']),self.costs)['passed'])


class WorkflowEvaluationTests(unittest.TestCase):
    def test_case_oracles_are_separate_and_counterfactual_groups_are_explicit(self):
        cases=scenarios()
        self.assertEqual(len(cases),47)
        self.assertEqual(len({c['case_id'] for c in cases}),47)
        groups={c['counterfactual_group'] for c in cases if c['counterfactual_group']}
        self.assertEqual(groups,{'irrelevant_wording','permission','cancellation_date','search_amount'})
        # Fault adapter's signature accepts no expected labels or costs.
        import inspect
        self.assertNotIn('expected',inspect.signature(execute_case).parameters)

    def test_pipeline_regressions_and_action_recovery(self):
        wanted={'authorisation_uncertain','cancellation_date_conflicts','tool_unavailable_handoff','timeout_after_commit','chat_save_after_case_commit'}
        cases=[c for c in scenarios() if c['case_id'] in wanted]
        with tempfile.TemporaryDirectory() as directory:
            summary=run(Path(directory),cases=cases)
            self.assertEqual(summary['passed'],len(cases))
            self.assertEqual(summary['critical_false_negatives'],0)
            self.assertEqual(summary['unsupported_autonomous_actions'],0)
            results=json.loads((Path(directory)/'results.json').read_text())
            package=next(r for r in results if r['case_id']=='tool_unavailable_handoff')['actual']['handoff_packages'][0]
            self.assertIn('missing_information',package)
            self.assertIn('actions_attempted',package)
            self.assertTrue((Path(directory)/'failed_outputs.json').is_file())

    def test_metrics_reproduce_while_audit_identifiers_can_vary(self):
        cases=[c for c in scenarios() if c['case_id'] in ('recognised','ambiguous_policy','same_key_replay')]
        with tempfile.TemporaryDirectory() as directory:
            first=run(Path(directory)/'a',cases=cases)
            second=run(Path(directory)/'b',cases=cases)
            self.assertEqual(first,second)
            self.assertEqual(first['failed'],0)
            manifest=json.loads((Path(directory)/'a/manifest.json').read_text())
            self.assertIn('evaluation/scoring.py',manifest['source_sha256'])
            self.assertIn('policy_contract.py',manifest['source_sha256'])

    def test_harness_exceptions_are_reported_as_critical_not_abstention(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory,patch('scripts.evaluate_workflow.execute_case',side_effect=RuntimeError('do not log private exception text')):
            report=run(Path(directory),cases=scenarios()[:1])
            self.assertEqual(report['critical_case_count'],1)
            self.assertEqual(report['error_counts']['harness_error'],1)
            self.assertEqual(report['weighted_error_cost'],1000)
            self.assertNotIn('private exception text',(Path(directory)/'results.json').read_text())


if __name__=='__main__': unittest.main()
