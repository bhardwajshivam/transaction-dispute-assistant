"""Failure-boundary privacy and fixed-dimension staff metrics checks."""
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from access import StaffPrincipal
from concern_extraction import extract
from concerns import connection, save_note, get_concern, codec_for, summary, list_handoffs
from conversation import start, OPTIONS
from operations import summarise, staff_summary, COUNTERS
from ollama_backend import BackendError
from privacy import customer_export, sanitise
from scripts.generate_data import generate
from scripts.load_database import load_database
from tests.support import demo_staff
from workflow import process, WorkflowError

CANARY='Email privacycanary@example.com phone +91 9876543210 card 4111111111111111 password privatecanaryvalue'


class OperationalPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);generate(self.root,cards_per_customer=2)
        self.db=self.root/'test.sqlite';load_database(self.root/'runtime',self.db)
        self.env=patch.dict(os.environ,{'CONCERNS_DATABASE':str(self.db),'CONCERN_EXTRACTION_MODE':'deterministic','EVIDENCE_PROPOSER_MODE':'deterministic'})
        self.env.start();self.addCleanup(self.env.stop)

    def assert_no_canary(self,value):
        for token in ('privacycanary@example.com','9876543210','4111111111111111','privatecanaryvalue'):
            self.assertNotIn(token,str(value))

    def selected(self,gatherer=None):
        state=start();cid=None;revision=0
        for text in (OPTIONS[0],'CARD-001','Please check TX-1001.','Confirm and search','TX-1001'):
            result=process(state,text,cid,revision,database=self.db,gatherer=gatherer)
            state,cid,revision=result.state,result.concern_id,result.revision
        return state,cid,revision

    def test_model_exception_and_arbitrary_code_never_enter_trace_or_logs(self):
        output=io.StringIO();handler=logging.StreamHandler(output);logger=logging.getLogger();logger.addHandler(handler);self.addCleanup(logger.removeHandler,handler)
        def failed(*_):raise BackendError(CANARY)
        with patch.dict(os.environ,{'CONCERN_EXTRACTION_MODE':'ollama'}),contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            fields,_,trace=extract('Charged INR 42 on 15-10-2026.','wrong_amount',transport=failed)
        self.assertEqual(fields['charged_amount'],'42.00')
        self.assertEqual(trace['error_code'],'INVALID_EXTRACTION_RESPONSE')
        self.assert_no_canary(json.dumps(trace)+output.getvalue())

    def test_tool_exception_recovers_to_review_without_logging_payload(self):
        import evidence_agent
        real=evidence_agent.read_tool
        output=io.StringIO();handler=logging.StreamHandler(output);logger=logging.getLogger();logger.addHandler(handler);self.addCleanup(logger.removeHandler,handler)
        def tool(proposal,*args):
            if proposal['gap']=='merchant':raise RuntimeError(CANARY)
            return real(proposal,*args)
        with patch('evidence_agent.read_tool',side_effect=tool),contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            state,cid,_=self.selected()
        self.assertEqual(state['evidence']['merchant']['status'],'UNAVAILABLE')
        self.assertEqual(state['step'],'handoff_confirm')
        row,events=get_concern(cid,database=self.db)
        self.assert_no_canary(row['state_json']+json.dumps(events)+output.getvalue())

    def test_unhandled_gatherer_and_action_errors_have_only_safe_codes(self):
        def failed(*a,**kw):raise RuntimeError(CANARY)
        with self.assertRaises(WorkflowError) as caught:self.selected(gatherer=failed)
        self.assertEqual(caught.exception.code,'EVIDENCE_SERVICE_UNAVAILABLE')
        self.assert_no_canary(str(caught.exception))
        class UnsafeError(ValueError):code=CANARY
        with patch('workflow.handle_case',side_effect=UnsafeError(CANARY)):
            with self.assertRaises(WorkflowError) as caught:process(start(),'text',database=self.db)
        self.assertEqual(caught.exception.code,'CASE_SERVICE_UNAVAILABLE')
        self.assert_no_canary(str(caught.exception))

    def test_malformed_tool_response_cannot_become_debug_or_export_payload(self):
        import evidence_agent
        real=evidence_agent.read_tool
        def tool(proposal,*args):
            if proposal['gap']=='merchant':return {'status':CANARY,'records':CANARY,'error':CANARY}
            return real(proposal,*args)
        with patch('evidence_agent.read_tool',side_effect=tool):state,cid,_=self.selected()
        self.assertEqual(state['evidence']['merchant']['status'],'MALFORMED')
        self.assert_no_canary(json.dumps(sanitise(state)))
        row,events=get_concern(cid,database=self.db)
        export=customer_export(json.loads(row['state_json']),cid,events)
        self.assert_no_canary(json.dumps(export))
        self.assertNotIn('evidence',export);self.assertNotIn('extraction_trace',export)
        self.assert_no_canary(summary(cid,database=self.db))

    def test_counter_output_has_fixed_dimensions_and_no_source_values(self):
        state={'answers':{'elaborate':CANARY},'extraction_trace':[{'model':CANARY,'status':'EXTRACTION_UNAVAILABLE_GUIDED_FALLBACK','rejected_fields':[CANARY]}],
               'review_requirement':'REQUIRED','review_reason_codes':['POLICY_CONFLICT',CANARY],
               'agent_trace':[{'result_status':'UNAVAILABLE','raw':CANARY}]}
        report=summarise([state],[{'status':'UNKNOWN'}],[{'status':'SUBMITTING'}],['CASE_EXISTING_LINKED'],[{'changed':0}],1)
        self.assertEqual(set(report['counts']),set(COUNTERS))
        self.assertTrue(all(type(v) is int for v in report['counts'].values()))
        self.assertEqual(report['counts']['extraction_fallbacks'],1)
        self.assertEqual(report['counts']['policy_failure_concerns'],1)
        self.assertEqual(report['counts']['existing_case_links'],1)
        self.assertEqual(report['counts']['card_noop_commands'],1)
        self.assert_no_canary(json.dumps(report))

    def test_staff_scope_expiry_and_one_snapshot_per_concern(self):
        state=start();state['answers']['elaborate']='Synthetic private case narrative'
        state['extraction_trace']=[{'model':'smollm2:135m','status':'EXTRACTION_UNAVAILABLE_GUIDED_FALLBACK'}]
        cid,revision=save_note(state,'issue','Initial note',database=self.db)
        save_note(state,'issue','Later note',cid,revision,database=self.db)
        save_note(start(),'issue','Other customer',customer_id='C-002',database=self.db)
        with self.assertRaises(PermissionError):staff_summary(None,database=self.db)
        with self.assertRaises(PermissionError):staff_summary(StaffPrincipal('staff',('C-001',),demo_staff().expires_at),customer_id='C-002',database=self.db)
        with self.assertRaises(PermissionError):staff_summary(StaffPrincipal('staff',('C-001',),0),database=self.db)
        report=staff_summary(demo_staff(),database=self.db)
        self.assertEqual(report['counts']['concerns'],1)
        self.assertEqual(report['counts']['extraction_attempts'],1)
        self.assertEqual(report['counts']['extraction_fallbacks'],1)
        self.assertNotIn('Synthetic private case narrative',json.dumps(report))
        self.assertNotIn(cid,json.dumps(report));self.assertNotIn('C-001',json.dumps(report))

    def test_debug_view_and_customer_export_redact_nested_tool_fields(self):
        state=start();state['evidence']={'merchant':{'records':[{'contact':'privacycanary@example.com','phone':'+91 9876543210','password':'privatecanaryvalue'}]}}
        clean=sanitise(state)
        self.assert_no_canary(json.dumps(clean))
        export=customer_export(clean,'CON-SYNTHETIC',[])
        self.assertNotIn('evidence',export)
        self.assert_no_canary(json.dumps(export))

    def test_streamlit_debug_panel_does_not_echo_model_exception(self):
        from streamlit.testing.v1 import AppTest
        def failed(*a,**kw):raise BackendError(CANARY)
        with patch.dict(os.environ,{'CONCERN_EXTRACTION_MODE':'ollama','SHOW_INTERNAL_DEBUG':'1'}),patch('concern_extraction.local_chat',side_effect=failed):
            app=AppTest.from_file('app.py',default_timeout=15).run()
            next(b for b in app.button if b.label==OPTIONS[3]).click().run()
            next(b for b in app.button if b.label.startswith('Demo card CARD-001 ')).click().run()
            app.chat_input[0].set_value('Email privacycanary@example.com. Charged INR 42 on 15-10-2026.').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.conversation['step'],'search_confirm')
            self.assertTrue(app.json)
            for item in app.json:self.assert_no_canary(item.value)
            self.assert_no_canary(json.dumps(app.session_state.conversation))

    def test_confirmed_representative_package_and_history_exclude_input_pii(self):
        state=start();cid=None;revision=0
        description='Email privacycanary@example.com phone +91 9876543210 card 4111111111111111. Charged INR 99 on TX-1001.'
        for text in (OPTIONS[3],'CARD-001',description,'Confirm and search','TX-1001','Yes, request human assistance'):
            turn=process(state,text,cid,revision,database=self.db)
            state,cid,revision=turn.state,turn.concern_id,turn.revision
        package=json.loads(list_handoffs(database=self.db,principal=demo_staff())[0]['summary_json'])
        self.assertTrue(package['continuation']['tasks'])
        self.assert_no_canary(json.dumps(package))
        self.assert_no_canary(summary(cid,database=self.db))

    def test_controller_and_storage_failures_do_not_expose_exception_text(self):
        for boundary,expected in (('workflow.submit','CONTROLLER_UNAVAILABLE'),('workflow.save_note','CHAT_SAVE_UNCONFIRMED')):
            with patch(boundary,side_effect=RuntimeError(CANARY)):
                with self.assertRaises(WorkflowError) as caught:process(start(),OPTIONS[0],database=self.db)
            self.assertEqual(caught.exception.code,expected)
            self.assert_no_canary(str(caught.exception))
