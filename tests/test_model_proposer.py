import json
import unittest
from copy import deepcopy
from evidence_agent import propose, validate_proposal
from model_proposer import build_context, make_proposer, parse_response


class ModelContractTests(unittest.TestCase):
    def state(self):
        return {'step': 'refund_status', 'answers': {'transaction': 'TX-1001',
                'additional_statements': ['secret customer message']}, 'messages': [('user', 'secret transcript')],
                'api_key': 'secret token', 'review_requirement': 'REQUIRED', 'evidence': {}}

    def test_context_excludes_unnecessary_data(self):
        s = self.state()
        original = deepcopy(s)
        ctx = build_context(s)
        self.assertNotIn('secret', json.dumps(ctx))
        self.assertEqual(ctx['allowed_proposals'], [propose(s)])
        self.assertEqual(s, original)

    def test_valid_and_controller_revalidation(self):
        s = self.state()
        candidate = propose(s)
        proposer = make_proposer(lambda context, schema, instruction: json.dumps(context['allowed_proposals'][0]))
        result = proposer(s)
        self.assertEqual(result, candidate)
        self.assertTrue(validate_proposal(s, result)[0])
        self.assertFalse(s['proposer_trace'][0]['fallback'])
        self.assertEqual(s['review_requirement'], 'REQUIRED')

    def test_invalid_output_falls_back(self):
        outputs = ['not json', 'null', '[]', '{"tool":"create_case"}',
                   json.dumps({'tool': 'verify_selected_transaction', 'gap': 'transaction', 'transaction_id': 'OTHER'}),
                   '{"tool":"verify_selected_transaction","tool":"create_case","gap":"transaction","transaction_id":"TX-1001"}',
                   'x' * 5000, json.dumps({'tool': [], 'gap': 'transaction', 'transaction_id': 'TX-1001'})]
        for raw in outputs:
            with self.subTest(raw=raw[:80]):
                s = self.state()
                result = make_proposer(lambda *_, raw=raw: raw)(s)
                self.assertEqual(result, propose(s))
                self.assertTrue(s['proposer_trace'][0]['fallback'])
                self.assertNotIn('raw', s['proposer_trace'][0])

    def test_backend_failure_and_no_gap_do_not_break_workflow(self):
        def failed(*_):
            raise TimeoutError('secret')
        s = self.state()
        result = make_proposer(failed)(s)
        self.assertEqual(result, propose(s))
        self.assertEqual(s['proposer_trace'][0]['status'], 'MODEL_UNAVAILABLE')
        self.assertNotIn('secret', json.dumps(s['proposer_trace']))
        s['answers'] = {}
        self.assertIsNone(make_proposer(lambda *_: self.fail('Should not call model'))(s))

    def test_budget_and_backend_cannot_mutate_state(self):
        s = self.state()
        def mutate(context, schema, instructions):
            context['selected_transaction_reference'] = 'OTHER'
            schema.clear()
            return json.dumps(propose(s))
        make_proposer(mutate)(s)
        self.assertEqual(s['answers']['transaction'], 'TX-1001')
        s['agent_trace'] = [{}] * 8
        self.assertIsNone(make_proposer(lambda *_: self.fail('Budget exhausted'))(s))
        with self.assertRaises(ValueError):
            parse_response('{"tool":null,"gap":"transaction","transaction_id":"TX-1001"}')
