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
from card_chat import handle as handle_card, active as card_active, intent as card_intent


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
    from workflow_contract import check_state, check_transition, VERSION
    try:
        check_state(state)
    except ValueError as error:
        raise WorkflowError('transition', str(error)) from None
    protected=protect(text)
    if protected.contains_secrets: raise WorkflowError('input','SECRET_BLOCKED')
    text=protected.text
    candidate=deepcopy(state)
    update_review(candidate)
    question=candidate['step']
    card_request=card_active(candidate) or card_intent(text)
    try:
        card_handled=handle_card(candidate,text,concern_id,database)
        handled=card_handled or handle_case(candidate,text,concern_id,database)
    except (sqlite3.Error,ValueError,PermissionError,FileNotFoundError) as error:
        raise WorkflowError('card' if card_request else 'case',getattr(error,'code','PERMISSION_DENIED' if isinstance(error,PermissionError) else 'CARD_SERVICE_UNAVAILABLE' if card_request else 'CASE_SERVICE_UNAVAILABLE')) from None
    if handled:
        question='card_control' if card_handled else 'case_control'
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
    if candidate.get('answers',{}).get('transaction') and question not in ('handoff_confirm','satisfaction','follow_up_update','case_control','card_control'):
        if gatherer is None:
            from orchestration import gather
            gatherer=gather
        gatherer(candidate,database=database)
        update_review(candidate)
        if candidate['review_requirement']=='REQUIRED' and candidate['step'] not in ('handoff_confirm','handoff_pending','done'):
            offer_review(candidate); prompt(candidate)
    try:
        check_transition(state,candidate,question)
        candidate['workflow_version']=VERSION
    except ValueError as error:
        raise WorkflowError('transition', str(error)) from None
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
    from workflow_contract import check_state
    try:
        check_state(state)
    except ValueError as error:
        raise WorkflowError('transition', str(error)) from None
    command=latest(concern_id,demo_customer(),database)
    if command:
        if command['status'] in ('UNKNOWN','SUBMITTING'): command=reconcile(command['command_id'],demo_customer(),database)
        restore(state,command)
        state['messages'].append(('assistant',f"Saved case submission status: {command['status']}. Reference: {command.get('case_id') or command['command_id']}."))
    from card_service import latest as latest_card, reconcile as reconcile_card, demo_principal
    from card_chat import restore as restore_card, active as card_active
    card=latest_card(concern_id,demo_principal(),database)
    if card and (card_active(state) or card['status'] in ('SUBMITTING','UNKNOWN')):
        if card['status'] in ('SUBMITTING','UNKNOWN'):card=reconcile_card(card['command_id'],demo_principal(),database)
        restore_card(state,card)
    return TurnResult(state,concern_id,saved['revision'],())
