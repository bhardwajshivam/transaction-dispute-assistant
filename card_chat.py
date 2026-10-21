"""Interruptible card protection; explicit actions never inferred from risk scores."""
import re
from domain import list_cards, card_label
import card_service as service

OPEN='Secure or block my card'
LOCK='Temporarily lock this card'
BLOCK='Permanently block this card'
CANCEL='Cancel card protection'
CHECK='Check card protection status'
RETRY='Retry the same card protection request'
CONTINUE='Continue my concern'
HELP='Request help with card protection'
FINISH='Finish card protection'
STEPS={'protect_card','protect_kind','protect_confirm','protect_unknown','protect_after','protect_failed'}


def intent(text):
    """Narrow explicit requests; negation, hypothetical and advice questions abstain."""
    if text==OPEN:return True
    text=text.strip().lower()
    request=r"(?:(?:i (?:want|need) to|i would like to|please|can you(?: please)?) )?(?:block|lock|freeze) (?:(?:my|this|the) )?card[.!?]?"
    return bool(re.fullmatch(request,text)
                or re.fullmatch(r'my card (?:is|was|has been) (?:lost|stolen|compromised)[.!]?',text)
                or re.fullmatch(r"(?:i (?:have )?|i.ve )lost my card[.!]?",text))



def active(state):return state.get('step') in STEPS


def choices(state):
    step=state.get('step')
    if step=='protect_card':return [card_label(c) for c in list_cards()]+[CANCEL]
    if step=='protect_kind':return [BLOCK,CANCEL] if state['card_protection'].get('reported_compromise') else [LOCK,BLOCK,CANCEL]
    if step=='protect_confirm':return [service.CONFIRM,CANCEL]
    if step=='protect_unknown':return [CHECK,RETRY,HELP]
    if step in ('protect_failed','protect_after'):
        standalone=state.get('card_resume_step')=='issue' and not state.get('answers',{}).get('issue')
        return [FINISH,HELP] if standalone else [CONTINUE,HELP]
    return []


def begin(state,text):
    previous=state.get('step','issue')
    state['card_resume_step']=previous
    # Keep dispute answers/card untouched when interrupting a different card.
    state['card_protection']={'request':text,'origin_step':previous, 'reported_compromise':bool(re.search(r'\b(lost|stolen|compromised)\b',text,re.I))}
    if re.search(r'\b(lost|stolen|compromised)\b',text,re.I):
        state['reported_card_risk']=True
    state['step']='protect_card'
    state['messages'].extend([('user',text),('assistant','I can help you secure your card. Choose the card to protect. No detailed explanation or transaction search is required first. This prototype only simulates card controls; for real protection, use your bank’s official card controls or urgent support now.')])


def restore(state,result):
    state.setdefault('card_protection',{})['command']=result
    if result['status'] in ('UNKNOWN','SUBMITTING'):
        state['step']='protect_unknown'
        if 'ACTION_OUTCOME_UNKNOWN' not in state.setdefault('review_signals',[]):
            state['review_signals'].append('ACTION_OUTCOME_UNKNOWN')
        state['messages'].append(('assistant','The card protection outcome is unknown. No real card protection is confirmed. Check status or retry this same request; do not create a replacement request. Use the bank’s official controls or urgent support for real protection.'))
    elif result['status']=='SUCCEEDED':
        record=result['action_record'];state['step']='protect_after'
        state['messages'].append(('assistant',f"Simulated card {result['card_id']} status: {record['resulting_status']}. Request: {result['command_id']}. No real bank card was changed. This does not cancel subscriptions, reverse payments or settle a dispute. You may now continue your concern or ask for assistance."))
    elif result['status']=='PREPARED':state['step']='protect_confirm'
    else:
        state['step']='protect_failed'
        state['messages'].append(('assistant','No new card action is confirmed. The request was cancelled or rejected. Use official bank controls for real protection; you can continue your concern or request help.'))


def handle(state,text,concern_id,database=None):
    if not active(state) and intent(text):
        begin(state,text);return True
    if not active(state):return False
    principal=service.demo_principal();data=state['card_protection'];step=state['step']
    state['messages'].append(('user',text))
    if intent(text) and re.search(r'\b(lost|stolen|compromised)\b',text,re.I):
        data['reported_compromise']=True;state['reported_card_risk']=True
        current=data.get('command') or {}
        if current.get('status')=='PREPARED':
            service.cancel(current['command_id'],principal,database)
            data.pop('command',None)
        if step=='protect_unknown':
            state['messages'].append(('assistant','You reported loss or compromise. Resolve the existing unknown request using status lookup; do not assume protection. Use official bank controls or urgent support immediately.'))
        else:
            state['step']='protect_kind' if data.get('card_id') else 'protect_card'
            state['messages'].append(('assistant','Loss or compromise has been recorded. Any unconfirmed lock preview was cancelled. Choose permanent block for the selected card, or cancel and use official bank controls for real protection. Explicit confirmation is still required.'))
        return True
    if text==FINISH and step in ('protect_after','protect_failed') and FINISH in choices(state):
        state['step']='done'
        state['messages'].append(('assistant','This card-protection journey is closed. No real bank card was changed. Any required specialist review remains in place; use official bank controls for actual protection.'))
        return True
    if text==CONTINUE and step in ('protect_after','protect_failed'):
        state['step']=state.pop('card_resume_step','issue')
        from conversation import prompt
        from review import update_review,offer_review
        update_review(state)
        if state['review_requirement']=='REQUIRED' and state['step'] not in ('issue','card','elaborate'):
            offer_review(state)
        prompt(state);return True
    if text==HELP and step in ('protect_unknown','protect_failed','protect_after'):
        from review import offer_review
        state['review_signals']=list(set(state.get('review_signals',[])+['CARD_PROTECTION_SUPPORT_REQUIRED']))
        offer_review(state)
        from conversation import prompt
        prompt(state);return True
    if text==CANCEL and step in ('protect_card','protect_kind','protect_confirm'):
        if data.get('command'):
            service.cancel(data['command']['command_id'],principal,database)
            data['command']=service.latest_by_id(data['command']['command_id'],principal,database)
        state['step']='protect_failed'
        state['messages'].append(('assistant','Card protection cancelled. No action was submitted by this request. Any existing card restriction or required specialist review remains in place.'))
        return True
    try:
        if step=='protect_card':
            cards=list_cards(database=database)
            card=next((c for c in cards if text in (c['card_id'],card_label(c))),None)
            if not card:raise service.CardDenied('CARD_SELECTION_REQUIRED')
            data['card_id']=card['card_id'];state['step']='protect_kind'
            p=service.policy();data['policy']=p
            state['messages'].append(('assistant',f"For {card['card_id']}, choose temporary lock or permanent block. If the card is lost, stolen or compromised, use the bank’s approved permanent-block route. A temporary lock is not a replacement for reporting compromise.\n\nTemporary lock: {p['actions']['LOCK']}\n\nPermanent block: {p['actions']['BLOCK']}\n\n{p['notice']}\nSource: {p['source_uri']} v{p['version']} as of {p['as_of']}."))
        elif step=='protect_kind' and text in (LOCK,BLOCK):
            if text==LOCK and data.get('reported_compromise'):
                raise service.CardDenied('REPORTED_COMPROMISE_REQUIRES_BLOCK_OR_BANK_HELP')
            action='LOCK' if text==LOCK else 'BLOCK'
            result=service.prepare(concern_id,data['card_id'],action,principal,database)
            restore(state,result)
            if result['status']=='PREPARED':
                p=result['policy']
                state['messages'].append(('assistant',f"Please confirm {action} for simulated card {result['card_id']}. {p['actions'][action]} {p['notice']} Confirmation expires in ten minutes. Choose the explicit confirmation button to submit, or cancel. No action has been taken yet."))
        elif step=='protect_confirm' and text==service.CONFIRM:
            restore(state,service.execute(data['command']['command_id'],principal,text,database))
        elif step=='protect_unknown' and text in (CHECK,RETRY):
            command=data['command']['command_id']
            result=service.reconcile(command,principal,database) if text==CHECK else service.execute(command,principal,service.CONFIRM,database)
            restore(state,result)
        else:
            state['messages'].append(('assistant','Please use the card-protection choices. A plain “yes” or a description does not authorise a card action.'))
    except (service.CardDenied,PermissionError) as error:
        data['last_error']=getattr(error,'code','PERMISSION_DENIED')
        current=data.get('command')
        if current:
            restore(state,service.reconcile(current['command_id'],principal,database))
            if state['step']=='protect_confirm':state['step']='protect_failed'
        else:state['step']='protect_failed'
        state['messages'].append(('assistant',f"Card protection could not proceed ({data['last_error']}). No new successful action is assumed. Use your bank’s official controls or urgent support for real protection."))
    return True
