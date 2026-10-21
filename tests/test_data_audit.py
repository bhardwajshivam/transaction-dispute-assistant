"""Check the audit detects deliberately injected leakage and remains reproducible."""
import json
import unittest
from scripts.audit_data_quality import audit, canonical, similarities, token_associations, wording_baseline


class DataAuditTests(unittest.TestCase):
    def test_normalised_templates_detect_overlap_but_keep_pair_intent_visible(self):
        left = [{'id':'a','text':'Payment TX-1234 was 42 on 15-10-2026','label':'CLARIFY','pair':'amount'}]
        right = [{'id':'b','text':'Payment TX-8888 was 43 on 16-10-2026','label':'CLARIFY','pair':'amount'}]
        result = similarities(left,right)
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]['exact_normalised'])
        self.assertTrue(result[0]['intentional_counterfactual'])
        right[0]['pair'] = None
        self.assertFalse(similarities(left,right)[0]['intentional_counterfactual'])
        self.assertNotEqual(canonical('A payment was made'),canonical('No refund has arrived'))

    def test_word_baseline_detects_deliberate_shortcut_and_has_deterministic_ties(self):
        train = [{'id':str(i),'text':word,'label':label} for i,(word,label) in enumerate([('shortcutalpha','A'),('shortcutalpha','A'),('shortcutbeta','B'),('shortcutbeta','B')])]
        result = wording_baseline(train,train)
        self.assertEqual(result['accuracy'],1)
        self.assertEqual(result['majority_accuracy'],.5)
        self.assertEqual(result,wording_baseline(train,train))
        associations=token_associations(train+[train[0]])
        self.assertEqual(associations[0]['dominant_route_fraction'],1)

    def test_current_audit_is_reproducible_and_discloses_limits(self):
        first,second=audit(),audit()
        self.assertEqual(json.dumps(first,sort_keys=True),json.dumps(second,sort_keys=True))
        self.assertEqual(first['errors'],[])
        self.assertEqual(first['activity_quality']['exact_cross_split_inputs'],0)
        self.assertGreater(len(first['workflow_text']['pairs_at_0_8']),0)
        self.assertEqual(first['frozen_challenges']['independent_review'],'PENDING_EXTERNAL_REVIEW')
        self.assertEqual(first['frozen_challenges']['count'],6)
        self.assertIn('not terminal routes',first['initial_text']['word_only_baseline']['limit'])
