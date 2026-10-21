"""Shared-service transition, resumption and representative continuation contracts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conversation import start, OPTIONS, QUESTIONS
from concerns import connection, get_concern, list_handoffs
from scripts.generate_data import generate
from scripts.load_database import load_database
from tests.support import demo_staff
from workflow import process, reopen, WorkflowError
from workflow_contract import EDGES, KNOWN_STEPS, VERSION
import card_chat
import card_service
import case_service


class WorkflowControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);generate(self.root,cards_per_customer=2)
        self.db=self.root/'test.sqlite';load_database(self.root/'runtime',self.db)
        self.env=patch.dict(os.environ,{'CONCERNS_DATABASE':str(self.db),'CONCERN_EXTRACTION_MODE':'deterministic','EVIDENCE_PROPOSER_MODE':'deterministic'})
        self.env.start();self.addCleanup(self.env.stop)
        self.state=start();self.cid=None;self.rev=0

    def turn(self,text):
        result=process(self.state,text,self.cid,self.rev,database=self.db)
        self.state,self.cid,self.rev=result.state,result.concern_id,result.revision
        return result

    def begin_search(self):
        for text in (OPTIONS[3],'CARD-001','Charged 42 instead of 40 on 15-10-2026.'):
            self.turn(text)

    def rows(self,table):
        with connection(self.db) as db:return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def test_contract_includes_all_rendered_question_states(self):
        self.assertTrue(set(QUESTIONS)<=KNOWN_STEPS)
        self.assertTrue(all(target in KNOWN_STEPS for targets in EDGES.values() for target in targets))

    def test_unknown_state_stops_before_tools_or_storage(self):
        self.state['step']='invented_step'
        with patch('workflow.handle_card') as card,patch('workflow.save_note') as save:
            with self.assertRaisesRegex(WorkflowError,'UNKNOWN_WORKFLOW_STEP'):
                self.turn('Yes')
            card.assert_not_called();save.assert_not_called()

    def test_illegal_controller_jump_is_not_saved(self):
        def bad(state,*args,**kwargs):state['step']='receipt'
        with patch('workflow.submit',side_effect=bad),patch('workflow.save_note') as save:
            with self.assertRaisesRegex(WorkflowError,'INVALID_WORKFLOW_TRANSITION'):
                self.turn(OPTIONS[0])
            save.assert_not_called()
        self.assertEqual(self.state['step'],'issue')

    def test_early_confirmation_and_unlisted_card_do_not_authorise_or_advance(self):
        with self.assertRaises(WorkflowError):self.turn(case_service.CONFIRM)
        self.assertEqual(self.rows('actions'),0)
        self.turn(OPTIONS[0]);self.turn('CARD-002')
        self.assertEqual(self.state['step'],'card')
        self.assertNotIn('card_id',self.state['answers'])

    def test_repeated_search_confirmation_and_wrong_reference_preserve_candidates(self):
        from domain import search_transactions
        self.begin_search();self.turn('Confirm and search')
        expected={t.reference for t in search_transactions(self.state)}
        self.assertEqual(expected,{'TX-1003','TX-1004'})
        self.turn('Confirm and search');self.turn('TX-1001')
        self.assertEqual(self.state['step'],'transaction')
        self.assertNotIn('transaction',self.state['answers'])
        self.assertEqual({t.reference for t in search_transactions(self.state)},expected)
        self.assertEqual(self.rows('actions'),0)

    def test_stale_turn_cannot_overwrite_saved_state(self):
        self.begin_search();old=deepcopy(self.state);oldrev=self.rev
        self.turn('Edit details')
        with self.assertRaisesRegex(WorkflowError,'CHAT_SAVE_UNCONFIRMED'):
            process(old,'Confirm and search',self.cid,oldrev,database=self.db)
        saved=reopen(self.cid,database=self.db)
        self.assertEqual(saved.state['step'],'elaborate')
        self.assertEqual(saved.revision,self.rev)

    def test_card_interruption_reopen_and_cancel_resume_original_search(self):
        self.begin_search();answers=deepcopy(self.state['answers']);criteria=deepcopy(self.state['intake'])
        self.turn(card_chat.OPEN);self.turn('CARD-001-2');self.turn(card_chat.LOCK)
        recovered=reopen(self.cid,database=self.db)
        self.state,self.rev=recovered.state,recovered.revision
        self.assertEqual(self.state['step'],'protect_confirm')
        self.turn(card_chat.CANCEL);self.turn(card_chat.CONTINUE)
        self.assertEqual(self.state['step'],'search_confirm')
        self.assertEqual(self.state['answers'],answers);self.assertEqual(self.state['intake'],criteria)
        self.assertEqual(self.rows('card_actions'),0)
        self.assertEqual(self.state['workflow_version'],VERSION)

    def test_handoff_package_supports_conflict_continuation_without_transcript(self):
        for text in (OPTIONS[3],'CARD-001','Charged INR 99 on payment TX-1001.','Confirm and search','TX-1001'):
            self.turn(text)
        self.assertEqual(self.state['step'],'handoff_confirm')
        self.turn('Yes, request human assistance')
        request=list_handoffs(database=self.db,principal=demo_staff())[0]
        package=json.loads(request['summary_json'])
        self.assertEqual(package['demo_bank_facts']['amount_minor'],850)
        self.assertEqual(package['search_confirmation']['charged_amount'],'99.00')
        self.assertIn('MATERIAL_EVIDENCE_CONFLICT',package['review_reason_codes'])
        self.assertTrue(package['evidence']);self.assertTrue(package['customer_statements_unverified'])
        self.assertTrue(package['missing_information'])
        plan=package['continuation'];self.assertEqual(plan['authority'],'ADVISORY_CONTINUATION_ONLY')
        self.assertEqual(plan['callback_status'],'NOT_SCHEDULED_SIMULATION')
        codes={t['code'] for t in plan['tasks']}
        self.assertTrue({'COMPARE_ASSERTIONS_WITH_FACTS','RESOLVE_RECORDED_GAPS','REVALIDATE_POLICY_AND_AUTHORITY','REVIEW_LATER_UPDATES'}<=codes)
        original=request['summary_json']
        self.turn('I have a receipt now. Please retain my earlier disputed amount for review.')
        self.assertEqual(list_handoffs(database=self.db,principal=demo_staff())[0]['summary_json'],original)
        _,events=get_concern(self.cid,database=self.db)
        self.assertIn('I have a receipt now.',events[-1]['customer_statement'])
        self.assertEqual(self.rows('handoff_requests'),1)

    def test_unknown_action_handoff_prioritises_reconciliation_not_replacement(self):
        for text in (card_chat.OPEN,'CARD-001',card_chat.BLOCK):self.turn(text)
        execute=card_service.execute
        with patch('card_service.execute',side_effect=lambda *a,**kw:execute(*a,**kw,fault='timeout_before_commit')):
            self.turn(card_service.CONFIRM)
        self.assertEqual(self.state['step'],'protect_unknown')
        command=self.state['card_protection']['command']['command_id']
        self.turn(card_chat.HELP);self.turn('Yes, request human assistance')
        package=json.loads(list_handoffs(database=self.db,principal=demo_staff())[0]['summary_json'])
        task=package['continuation']['tasks'][0]
        self.assertEqual(task['code'],'RECONCILE_EXISTING_ACTION')
        self.assertEqual(task['references'],[command])
        self.assertIn('Do not create a replacement',task['instruction'])
        self.assertEqual(self.rows('card_actions'),0)
