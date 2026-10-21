"""State transitions for general, attributed policy questions; no account action."""
from policy_service import QUESTIONS,answer

OPEN='I have a question about dispute policy'
ANOTHER='Ask another policy question'


def handle(state,text):
    from conversation import prompt
    from review import update_review,offer_review
    if state['step']=='issue' and text==OPEN:
        state['answers']['issue']=OPEN
        state['issue_kind']='policy_question'
        state['step']='policy_topic'
        prompt(state)
        return True
    if state.get('issue_kind')=='policy_question' and state['step']=='satisfaction' and text==ANOTHER:
        state['step']='policy_topic'
        prompt(state)
        return True
    if state['step']!='policy_topic': return False
    state['answers'].setdefault('policy_questions',[]).append(text)
    result=answer(text)
    from policy_contract import information,attribution
    context=information(result)
    if result['status']!='CLARIFY' and not context['allowed']:
        result=dict(result,status=context['status'],reason_code=context['reason_code'],policy_conclusion=False,
                    text='I cannot give a policy conclusion because the applicable source cannot be verified or is outside scope. You can request human assistance.')
    state['policy_qa']=result
    state.setdefault('policy_qa_history',[]).append(result)
    state['messages'].append(('assistant',result['text']))
    if result['status']=='CLARIFY':
        prompt(state)
        return True
    success=context['allowed']
    state['decision']={'route':'POLICY_INFORMATION' if success else 'HUMAN_REVIEW',
                       'reason':'POLICY_ANSWER_GROUNDED' if success else result['reason_code'],
                       **attribution(context),'decision_type':'POLICY_INFORMATION' if success else 'OPERATIONAL_REFERRAL',
                       'explanation':result['text'],'evidence_ids':[result['corpus_sha256']] if success else []}
    if success:
        update_review(state)
        if state['review_requirement']=='REQUIRED': offer_review(state)
        else: state['step']='satisfaction'
    else:
        signal='POLICY_CONFLICT' if result['status']=='CONFLICT' else 'POLICY_OUT_OF_SCOPE' if result['status']=='OUT_OF_SCOPE' else 'POLICY_UNAVAILABLE'
        state.setdefault('review_signals',[]).append(signal)
        offer_review(state)
    prompt(state)
    return True
