"""Shared application turn pipeline used by Streamlit and offline evaluation.

UI session expiry remains in app.py. This service owns protected input,
controller advancement, read-only evidence, mandatory review and persistence.
Dependencies can be replaced by trusted offline fault adapters, never user text.
"""
from copy import deepcopy
from dataclasses import dataclass
import sqlite3
from privacy import protect
from conversation import submit,prompt
from review import update_review,offer_review
from concerns import save_note
from case_chat import handle as handle_case


class WorkflowError(ValueError):
    def __init__(self,stage,code):
        self.stage,self.code=stage,code
        super().__init__(code)


@dataclass
class TurnResult:
    state: dict
    concern_id: str
    revision: int
    redactions: tuple


def process(state,text,concern_id=None,revision=0,*,database=None,extractor=None,gatherer=None):
    protected=protect(text)
    if protected.contains_secrets: raise WorkflowError('input','SECRET_BLOCKED')
    text=protected.text
    candidate=deepcopy(state)
    update_review(candidate)
    question=candidate['step']
    try:
        handled=handle_case(candidate,text,concern_id,database)
    except (sqlite3.Error,ValueError,PermissionError,FileNotFoundError) as error:
        raise WorkflowError('case',getattr(error,'code','PERMISSION_DENIED' if isinstance(error,PermissionError) else 'CASE_SERVICE_UNAVAILABLE')) from None
    if handled:
        question='case_control'
    elif question=='done':
        candidate['messages'].extend([('user',text),('assistant','Your update has been added to this concern’s history. The earlier routing suggestion has not been re-evaluated; contact the bank for further review.')])
        candidate['answers'].setdefault('follow_up_updates',[]).append(text)
        candidate['previous_decision']=candidate.get('decision')
        candidate['decision']=None
        candidate['concern_status']='needs_review'
        if candidate['review_requirement']=='REQUIRED': offer_review(candidate)
        else: candidate['step']='satisfaction'
        prompt(candidate)
        question='follow_up_update'
    else:
        if extractor is None:
            from concern_extraction import extract
            extractor=extract
        submit(candidate,text,extractor=extractor)
    if candidate.get('answers',{}).get('transaction') and question not in ('handoff_confirm','satisfaction','follow_up_update','case_control'):
        if gatherer is None:
            from orchestration import gather
            gatherer=gather
        gatherer(candidate,database=database)
        update_review(candidate)
        if candidate['review_requirement']=='REQUIRED' and candidate['step'] not in ('handoff_confirm','handoff_pending','done'):
            offer_review(candidate); prompt(candidate)
    try:
        cid,revision=save_note(candidate,question,text,concern_id=concern_id,revision=revision,database=database)
    except (sqlite3.Error,ValueError,PermissionError,FileNotFoundError):
        # A case command may already have committed independently of chat saving.
        raise WorkflowError('storage','CHAT_SAVE_UNCONFIRMED') from None
    return TurnResult(candidate,cid,revision,protected.categories)


def reopen(concern_id,*,database=None):
    import json
    from concerns import get_concern
    from case_service import latest,reconcile,demo_customer
    from case_chat import restore
    saved,_=get_concern(concern_id,database=database)
    state=json.loads(saved['state_json'])
    command=latest(concern_id,demo_customer(),database)
    if command:
        if command['status'] in ('UNKNOWN','SUBMITTING'): command=reconcile(command['command_id'],demo_customer(),database)
        restore(state,command)
        state['messages'].append(('assistant',f"Saved case submission status: {command['status']}. Reference: {command.get('case_id') or command['command_id']}."))
    return TurnResult(state,concern_id,saved['revision'],())
