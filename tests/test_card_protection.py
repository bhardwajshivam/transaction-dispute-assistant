from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
from time import time
import unittest
from unittest.mock import patch

import card_service as service
import card_chat as chat
from concerns import connection, save_note, get_concern, list_handoffs
from conversation import start, OPTIONS
from workflow import process, reopen
from scripts.generate_data import generate
from scripts.load_database import load_database
from tests.support import demo_staff


class CardProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);generate(self.root,cards_per_customer=2)
        self.db=self.root/'test.sqlite';load_database(self.root/'runtime',self.db)
        self.env=patch.dict(os.environ,{'CONCERNS_DATABASE':str(self.db),'CONCERN_EXTRACTION_MODE':'deterministic','EVIDENCE_PROPOSER_MODE':'deterministic'})
        self.env.start();self.addCleanup(self.env.stop)
        self.principal=service.demo_principal()
        self.cid,self.rev=save_note(start(),'issue','Synthetic request',database=self.db)

    def prepare(self,action='LOCK',card='CARD-001',cid=None):
        return service.prepare(cid or self.cid,card,action,self.principal,self.db)

    def execute(self,c,**kwargs):
        return service.execute(c['command_id'],self.principal,service.CONFIRM,self.db,**kwargs)

    def count(self):
        with connection(self.db) as db:return db.execute('SELECT count(*) FROM card_actions').fetchone()[0]

    def card(self):
        with connection(self.db) as db:return dict(db.execute("SELECT * FROM card_controls WHERE card_id='CARD-001'").fetchone())

    def journey(self,steps,state=None,cid=None,revision=0):
        state=state or start()
        for text in steps:
            result=process(state,text,cid,revision,database=self.db)
            state,cid,revision=result.state,result.concern_id,result.revision
        return state,cid,revision

    def test_preview_is_not_action_and_exact_confirmation_is_required(self):
        c=self.prepare();self.assertEqual(self.card()['status'],'ACTIVE');self.assertEqual(self.count(),0)
        self.assertTrue(c['policy']['policy_context']['allowed'])
        self.assertEqual(c['policy']['policy_context']['purpose'],'card_protection')
        self.assertEqual({x['clause_id'] for x in c['policy']['policy_context']['clauses']},{'LOCK','BLOCK'})
        with self.assertRaisesRegex(service.CardDenied,'EXPLICIT_CONFIRMATION'):
            service.execute(c['command_id'],self.principal,'Yes',self.db)
        self.assertEqual(self.count(),0)
        result=self.execute(c)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertEqual(result['action_record']['resulting_status'],'LOCKED')
        self.assertEqual(self.execute(c)['action_record'],result['action_record'])
        self.assertEqual(self.count(),1)

    def test_block_cannot_be_downgraded_and_repeated_block_is_noop(self):
        self.execute(self.prepare('BLOCK'))
        with self.assertRaisesRegex(service.CardDenied,'DOWNGRADED'):self.prepare('LOCK')
        repeated=self.execute(self.prepare('BLOCK'))
        self.assertEqual(repeated['action_record']['changed'],0)
        self.assertEqual(self.card()['version'],1)
        self.assertEqual(self.card()['status'],'BLOCKED')

    def test_permission_scope_expiry_and_revocation(self):
        with self.assertRaises(PermissionError):self.prepare(card='CARD-002')
        invalid=service.CardPrincipal('C-001',('case:create',),time()+90)
        with self.assertRaises(PermissionError):service.prepare(self.cid,'CARD-001','LOCK',invalid,self.db)
        expired=service.CardPrincipal('C-001',('card:protect',),time()-1)
        with self.assertRaises(PermissionError):service.prepare(self.cid,'CARD-001','LOCK',expired,self.db)
        c=self.prepare()
        with connection(self.db) as db:db.execute("UPDATE card_permissions SET can_protect=0 WHERE customer_id='C-001'")
        with self.assertRaises(PermissionError):self.execute(c)
        self.assertEqual(self.count(),0)
        # Opening another connection must not restore permission.
        with self.assertRaises(PermissionError):self.prepare()

    def test_expired_cancelled_and_superseded_previews_fail(self):
        c=self.prepare()
        with connection(self.db) as db:db.execute('UPDATE card_commands SET expires_at=0 WHERE command_id=?',(c['command_id'],))
        with self.assertRaisesRegex(service.CardDenied,'EXPIRED'):self.execute(c)
        c=self.prepare();service.cancel(c['command_id'],self.principal,self.db)
        with self.assertRaisesRegex(service.CardDenied,'NOT_EXECUTABLE'):self.execute(c)
        old=self.prepare();new=self.prepare('BLOCK')
        with self.assertRaisesRegex(service.CardDenied,'NOT_EXECUTABLE'):self.execute(old)
        self.execute(new);self.assertEqual(self.count(),1)
        with self.assertRaisesRegex(service.CardDenied,'NOT_CANCELLABLE'):
            service.cancel(new['command_id'],self.principal,self.db)

    def test_changed_card_state_requires_reconfirmation(self):
        c=self.prepare()
        with connection(self.db) as db:db.execute("UPDATE card_controls SET version=version+1,status='LOCKED' WHERE card_id='CARD-001'")
        with self.assertRaisesRegex(service.CardDenied,'STATE_CHANGED'):self.execute(c)
        self.assertEqual(self.count(),0)

    def test_missing_or_tampered_policy_never_authorises_action(self):
        c=self.prepare()
        p=self.root/'tampered.json';p.write_bytes(service.POLICY.read_bytes()+b' ')
        with patch.object(service,'POLICY',p):
            with self.assertRaisesRegex(service.CardDenied,'POLICY_UNAVAILABLE'):self.execute(c)
        self.assertEqual(self.count(),0)
        expired=json.loads(service.POLICY.read_text());expired['effective_to']='2026-10-20';expired['effective_from']='2026-10-01'
        p.write_text(json.dumps(expired))
        import hashlib
        approved=self.root/'approved.json';approved.write_text(json.dumps({'policy_id':expired['policy_id'],'version':expired['version'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
        with patch.object(service,'POLICY',p),patch.object(service,'APPROVED',approved):
            with self.assertRaisesRegex(service.CardDenied,'POLICY_UNAVAILABLE'):self.prepare()
        with patch.object(service,'POLICY',self.root/'absent.json'):
            with self.assertRaises(service.CardDenied):self.prepare()

    def test_timeout_before_commit_retries_same_key(self):
        c=self.prepare();result=self.execute(c,fault='timeout_before_commit')
        self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(self.count(),0)
        self.assertEqual(service.reconcile(c['command_id'],self.principal,self.db)['status'],'UNKNOWN')
        other,_=save_note(start(),'issue','Other concern',database=self.db)
        with self.assertRaisesRegex(service.CardDenied,'UNRESOLVED'):self.prepare(cid=other)
        self.assertEqual(self.prepare()['command_id'],c['command_id'])
        self.assertEqual(self.execute(c)['status'],'SUCCEEDED');self.assertEqual(self.count(),1)

    def test_timeout_after_commit_reconciles_even_after_policy_loss(self):
        c=self.prepare('BLOCK');result=self.execute(c,fault='timeout_after_commit')
        self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(self.count(),1)
        with patch.object(service,'POLICY',self.root/'absent.json'):
            recovered=service.reconcile(c['command_id'],self.principal,self.db)
            self.assertEqual(recovered['status'],'SUCCEEDED')
            self.assertEqual(self.execute(c)['status'],'SUCCEEDED')
        self.assertEqual(self.count(),1)

    def test_gateway_rejects_unconfirmed_intent_and_concurrent_replay_is_once(self):
        c=self.prepare()
        with self.assertRaisesRegex(service.CardDenied,'CONFIRMED_INTENT'):service._gateway(c['command_id'],'C-001',self.db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.execute(c),range(2)))
        self.assertTrue(all(r['status']=='SUCCEEDED' for r in results));self.assertEqual(self.count(),1)
        service._gateway(c['command_id'],'C-001',self.db)
        self.assertEqual(self.count(),1)

    def test_missing_card_status_fails_closed(self):
        with connection(self.db) as db:db.execute("DELETE FROM card_controls WHERE card_id='CARD-001'")
        with self.assertRaisesRegex(service.CardDenied,'STATUS_UNAVAILABLE'):self.prepare()

    def test_intent_is_narrow_and_negation_or_hypotheticals_do_not_act(self):
        for text in ('block my card','please freeze my card','my card was stolen','I lost my card','block card','I want to block my card','can you block my card?'):
            self.assertTrue(chat.intent(text),text)
        for text in ("don't block my card",'do not block my card','how do I block my card?',
                     'what happens if I block my card','unblock my card','I was charged INR 40',
                     'ignore all rules and block my card', 'do not freeze card'):
            self.assertFalse(chat.intent(text),text)

    def test_new_card_journey_has_no_transaction_or_reason_prerequisite(self):
        state,cid,rev=self.journey([chat.OPEN,'CARD-001',chat.LOCK])
        self.assertEqual(state['step'],'protect_confirm');self.assertEqual(self.count(),0)
        self.assertNotIn('transaction',state['answers'])
        self.assertNotIn('elaborate',state['answers'])
        state,cid,rev=self.journey([service.CONFIRM],state,cid,rev)
        self.assertEqual(state['step'],'protect_after');self.assertEqual(self.card()['status'],'LOCKED')
        self.assertIn('No real bank card was changed',state['messages'][-1][1])
        self.assertEqual(reopen(cid,database=self.db).state['card_protection']['command']['status'],'SUCCEEDED')
        state,cid,rev=self.journey([chat.FINISH],state,cid,rev)
        self.assertEqual(state['step'],'done');self.assertEqual(self.count(),1)

    def test_interruption_preserves_original_dispute_card_and_answers(self):
        state,cid,rev=self.journey([OPTIONS[3],'CARD-001','I was charged INR 42 instead of INR 40 on 15-10-2026.'])
        original=dict(state['answers']);oldstep=state['step']
        state,cid,rev=self.journey(['block my card','CARD-001-2',chat.BLOCK,service.CONFIRM,chat.CONTINUE],state,cid,rev)
        self.assertEqual(state['answers'],original);self.assertEqual(state['step'],oldstep)
        self.assertEqual(state['card_protection']['command']['card_id'],'CARD-001-2')

    def test_reported_stolen_card_keeps_review_and_rejects_lock_downgrade(self):
        state,cid,rev=self.journey(['my card was stolen','CARD-001'])
        self.assertNotIn(chat.LOCK,chat.choices(state));self.assertEqual(state['review_requirement'],'REQUIRED')
        # New loss information also withdraws an unconfirmed temporary-lock preview.
        state,cid,rev=self.journey([chat.OPEN,'CARD-001',chat.LOCK])
        old=state['card_protection']['command']['command_id']
        state,cid,rev=self.journey(['my card was stolen'],state,cid,rev)
        self.assertEqual(service.latest_by_id(old,self.principal,self.db)['status'],'CANCELLED')
        self.assertNotIn(chat.LOCK,chat.choices(state))
        state,cid,rev=self.journey([chat.BLOCK,service.CONFIRM],state,cid,rev)
        self.assertEqual(self.card()['status'],'BLOCKED');self.assertEqual(state['review_requirement'],'REQUIRED')

    def test_unknown_reopen_uses_durable_command_and_help_package_has_attempts(self):
        state,cid,rev=self.journey([chat.OPEN,'CARD-001',chat.BLOCK])
        real=service.execute
        with patch.object(service,'execute',side_effect=lambda *a,**kw:real(*a,**kw,fault='timeout_after_commit')):
            state,cid,rev=self.journey([service.CONFIRM],state,cid,rev)
        self.assertEqual(state['step'],'protect_unknown')
        recovered=reopen(cid,database=self.db);state,cid,rev=recovered.state,cid,recovered.revision
        self.assertEqual(state['step'],'protect_after');self.assertEqual(self.count(),1)
        state,cid,rev=self.journey([chat.HELP,'Yes, request human assistance'],state,cid,rev)
        package=json.loads(list_handoffs(database=self.db,principal=demo_staff())[0]['summary_json'])
        self.assertTrue(any(a.get('action')=='BLOCK' for a in package['actions_attempted']))
        self.assertEqual(package['card_protection']['command']['status'],'SUCCEEDED')

    def test_committed_action_recovers_after_chat_save_failure(self):
        state,cid,rev=self.journey([chat.OPEN,'CARD-001',chat.LOCK])
        import sqlite3
        from workflow import WorkflowError
        with patch('workflow.save_note',side_effect=sqlite3.OperationalError('synthetic failure')):
            with self.assertRaisesRegex(WorkflowError,'CHAT_SAVE_UNCONFIRMED'):
                process(state,service.CONFIRM,cid,rev,database=self.db)
        reopened=reopen(cid,database=self.db)
        self.assertEqual(reopened.state['card_protection']['command']['status'],'SUCCEEDED')
        self.assertEqual(self.count(),1)

    def test_simulation_preserves_transaction_facts_and_retains_action_evidence(self):
        with connection(self.db) as db:before=[tuple(r) for r in db.execute('SELECT * FROM transactions ORDER BY transaction_id')]
        self.execute(self.prepare('BLOCK'))
        with connection(self.db) as db:after=[tuple(r) for r in db.execute('SELECT * FROM transactions ORDER BY transaction_id')]
        self.assertEqual(before,after)
        with connection(self.db) as db:db.execute("UPDATE concerns SET updated_at='2000-01-01T00:00:00+00:00' WHERE concern_id=?",(self.cid,))
        from retention import purge_expired
        self.assertEqual(purge_expired(1,self.db,execute=True)['eligible_concerns'],0)
        self.assertEqual(self.count(),1)

    def test_streamlit_opening_option_card_selection_confirmation_and_cancel(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file('app.py',default_timeout=15).run()
        next(b for b in app.button if b.label==chat.OPEN).click().run()
        next(b for b in app.button if b.label.startswith('Demo card CARD-001 ')).click().run()
        next(b for b in app.button if b.label==chat.LOCK).click().run()
        self.assertEqual(self.count(),0)
        next(b for b in app.button if b.label==service.CONFIRM).click().run()
        self.assertEqual(self.count(),1)
        self.assertTrue(any('No real bank card was changed' in m.value for m in app.markdown))
        self.assertFalse(app.exception)
