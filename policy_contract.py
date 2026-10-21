"""Shared policy clock, attribution envelope and fail-closed conclusion gates.

Facts/customer acknowledgements and operational safety referrals can still be
reported without policy. They must never masquerade as policy conclusions.
"""
from datetime import date
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
from intake import SNAPSHOT

INTAKE_SCOPE='synthetic card intake only'
CASE_SCOPE='synthetic dispute case recording only'
INFO_SCOPE='synthetic card dispute information only'
RULES={
    'P-01':('Customer confirms recognition and resolution','EXPLAIN'),
    'P-02':('Customer reports payment without permission','HUMAN_REVIEW'),
    'P-03':('Unresolved billing, cancellation or refund concern','HUMAN_REVIEW'),
}
REASON_RULE={'CUSTOMER_RECOGNISED':'P-01','REPORTED_UNAUTHORISED':'P-02',
             'CANCELLATION_REVIEW':'P-03','BILLING_REVIEW':'P-03',
             'REFUND_RECORDS_REVIEW':'P-03','REFUND_EVIDENCE_UNAVAILABLE':'P-03'}


def as_of():
    return SNAPSHOT.isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def active(start,end,day=None):
    start_date=date.fromisoformat(start)
    if start_date.isoformat()!=start: raise ValueError('Noncanonical policy date')
    if end is not None:
        end_date=date.fromisoformat(end)
        if end_date.isoformat()!=end or end_date<=start_date: raise ValueError('Invalid policy interval')
    return start_date<=date.fromisoformat(day or as_of()) and (end is None or date.fromisoformat(day or as_of())<end_date)


def envelope(purpose,scope,status='UNAVAILABLE',reason='POLICY_UNAVAILABLE',sources=None,clauses=None,day=None):
    return {'contract_version':'policy-evidence-v1','purpose':purpose,'scope':scope,'as_of':day or as_of(),
            'status':status,'reason_code':reason,'allowed':status=='SUCCESS',
            'sources':sources or [],'clauses':clauses or []}


def label(context):
    if not context.get('allowed'): return None
    return '; '.join(f"{s['policy_id']} v{s['version']}" for s in context['sources'])


def attribution(context):
    return {'policy':label(context),'policy_records_consulted':context['sources'] if context['allowed'] else [],
            'policy_context':context,'policy_conclusion':context['allowed'],'policy_reason_code':context['reason_code']}


def source(policy,scope,content_hash,location,hash_scope='document'):
    return {'policy_id':policy['policy_id'],'version':policy['version'],'scope':scope,
            'effective_from':policy['effective_from'],'effective_to':policy.get('effective_to'),
            'as_of':as_of(),'authority':policy.get('authority','Fictional prototype intake policy'),
            'source_uri':location,'content_sha256':content_hash,'hash_scope':hash_scope,
            **{k:policy[k] for k in ('supersedes','publication_status') if k in policy}}


def intake(db=None):
    """Read current source rather than trusting a cached SUCCESS marker."""
    if db is None:
        path=Path(os.environ.get('CONCERNS_DATABASE',Path(__file__).parent/'data/disputes.sqlite'))
        try:
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as owned:
                owned.row_factory=sqlite3.Row
                owned.execute('BEGIN')
                return intake(owned)
        except (sqlite3.Error,OSError):
            return envelope('transaction_intake',INTAKE_SCOPE)
    try:
        rows=[dict(r) for r in db.execute("SELECT * FROM policies WHERE policy_id='DEMO-INTAKE'")]
        current=[r for r in rows if active(r['effective_from'],r['effective_to'])]
        if not current:
            return envelope('transaction_intake',INTAKE_SCOPE,'NOT_FOUND','POLICY_NOT_EFFECTIVE')
        if len(current)!=1:
            return envelope('transaction_intake',INTAKE_SCOPE,'CONFLICT','POLICY_VERSION_CONFLICT')
        row=current[0]
        if row['scope']!=INTAKE_SCOPE:
            return envelope('transaction_intake',INTAKE_SCOPE,'OUT_OF_SCOPE','POLICY_SCOPE_MISMATCH')
        body=json.loads(row['record_json'])
        if not isinstance(body,dict) or body.get('fictional') is not True: raise ValueError('Invalid policy')
        if not isinstance(row['version'],str) or not re.fullmatch(r'\d+\.\d+',row['version']): raise ValueError('Invalid version')
        if any(body.get(k)!=row[k] for k in ('policy_id','version','effective_from','effective_to','scope')):
            raise ValueError('Policy metadata mismatch')
        parsed={r['rule_id']:(r['condition'],r['outcome']) for r in body['rules']}
        if parsed!=RULES or len(body['rules'])!=len(RULES): raise ValueError('Unsupported policy rules')
        src=source(body,INTAKE_SCOPE,digest(body),f"policy://{body['policy_id']}/{body['version']}")
        clauses=[{'clause_id':r['rule_id'],'text':r['condition'],'outcome':r['outcome'],
                  'source_uri':src['source_uri']+'#'+r['rule_id']} for r in body['rules']]
        result=envelope('transaction_intake',INTAKE_SCOPE,'SUCCESS','POLICY_VALIDATED',[src],clauses)
        result['records']=[dict(row,record_json=body)]
        return result
    except (ValueError,TypeError,KeyError,AttributeError,sqlite3.Error):
        return envelope('transaction_intake',INTAKE_SCOPE,'MALFORMED','POLICY_INVALID')


def information(result,day=None):
    """Normalise already retrieved corpus evidence, checking binding and scope."""
    status=result.get('status','UNAVAILABLE')
    expected=day or as_of()
    context=envelope('policy_information',INFO_SCOPE,status,result.get('reason_code','POLICY_UNAVAILABLE'),day=expected)
    if status!='SUCCESS': return context
    try:
        if result['scope']!=INFO_SCOPE or result['as_of']!=expected or len(result['sources'])!=1:
            raise ValueError('Scope/date mismatch')
        src=result['sources'][0]
        if not active(src['effective_from'],src['effective_to'],result['as_of']): raise ValueError('Stale policy')
        if src['source_uri']!=f"policy://{src['policy_id']}/{src['version']}": raise ValueError('Source mismatch')
        checksum=result['corpus_sha256']
        if len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum): raise ValueError('Missing digest')
        from policy_service import load_corpus
        approved,actual_digest=load_corpus()
        if checksum!=actual_digest: raise ValueError('Unverified corpus digest')
        documents=[d for d in approved if d['policy_id']==src['policy_id'] and d['version']==src['version']]
        if len(documents)!=1: raise ValueError('Source not approved')
        doc=documents[0]
        if any(src.get(k)!=doc[k] for k in ('policy_id','version','title','authority','approval_id','publication_status','supersedes','effective_from','effective_to','source_uri')):
            raise ValueError('Source metadata not approved')
        clauses=result['clauses']
        if not clauses or any(c['source_uri']!=src['source_uri']+'#'+c['clause_id'] or not isinstance(c['text'],str) for c in clauses):
            raise ValueError('Clause attribution mismatch')
        if clauses!=[dict(c,source_uri=src['source_uri']+'#'+c['clause_id']) for c in doc['clauses']]:
            raise ValueError('Clause content not approved')
        normal=source(src,INFO_SCOPE,checksum,src['source_uri'],'corpus')
        normal['as_of']=expected
        normal.update({k:src[k] for k in ('publication_status','supersedes','approval_id','applicability')})
        return envelope('policy_information',INFO_SCOPE,'SUCCESS','POLICY_VALIDATED',[normal],clauses,expected)
    except (KeyError,ValueError,TypeError,AttributeError,OSError):
        return envelope('policy_information',INFO_SCOPE,'MALFORMED','POLICY_INVALID',day=expected)


def case_context(policy):
    try:
        if policy['scope']!=CASE_SCOPE or not active(policy['effective_from'],policy['effective_to']): raise ValueError('Invalid case policy')
        src=source(policy,CASE_SCOPE,digest(policy),f"policy://{policy['policy_id']}/{policy['version']}")
        clauses=policy['clauses']
        expected={'clause_id':'CASE-01','text':'Record only a confirmed, permitted, supported posted-payment concern with validated routing evidence.','outcome':'SIMULATED_OPEN'}
        if clauses!=[expected]: raise ValueError('Unsupported case rule')
        clause=dict(clauses[0],source_uri=src['source_uri']+'#CASE-01')
        return envelope('case_intake',CASE_SCOPE,'SUCCESS','POLICY_VALIDATED',[src],[clause])
    except (ValueError,TypeError,KeyError):
        return envelope('case_intake',CASE_SCOPE,'UNAVAILABLE','CASE_POLICY_UNAVAILABLE')


def gate_reason(reason,context,state=None):
    """Execute supported rule identifiers; policy prose is never executable."""
    rule=REASON_RULE.get(reason)
    if not rule:
        return envelope('transaction_intake',INTAKE_SCOPE,'NOT_REQUIRED','OPERATIONAL_REFERRAL_ONLY')
    if not context.get('allowed'): return context
    answers=(state or {}).get('answers',{})
    premise=False
    if rule=='P-01': premise=answers.get('recognise')=='Yes' and answers.get('resolved')=='Yes'
    elif rule=='P-02': premise=answers.get('permission')=='Yes'
    elif reason=='CANCELLATION_REVIEW':
        premise=all(answers.get(k) for k in ('cancel_type','cancel_date','cancel_method','cancel_confirm'))
    elif reason=='BILLING_REVIEW':
        billing=answers.get('billing_type')
        premise=(billing=='I was charged more than once' and all(answers.get(k) for k in ('duplicate','purchase_count','receipt'))
                 or billing=='The amount is wrong' and all(answers.get(k) for k in ('expected_amount','receipt','adjustment'))
                 or billing=='The currency is unexpected' and all(answers.get(k) for k in ('expected_currency','currency_receipt')))
    elif reason in ('REFUND_RECORDS_REVIEW','REFUND_EVIDENCE_UNAVAILABLE'):
        premise=all(answers.get(k) for k in ('refund_status','refund_date','refund_amount','refund_method','refund_confirm'))
    if not premise:
        return envelope('transaction_intake',INTAKE_SCOPE,'UNSUPPORTED','POLICY_PRECONDITION_UNVERIFIED')
    matching=[c for c in context.get('clauses',[]) if c.get('clause_id')==rule]
    if len(matching)!=1:
        return envelope('transaction_intake',INTAKE_SCOPE,'MALFORMED','POLICY_RULE_UNSUPPORTED')
    return dict({k:v for k,v in context.items() if k!='records'},clauses=matching,applied_rule_id=rule)


def review_signal(context):
    if context['reason_code']=='POLICY_PRECONDITION_UNVERIFIED': return 'POLICY_PRECONDITION_UNVERIFIED'
    if context['status']=='STALE': return 'POLICY_STALE'
    return 'POLICY_CONFLICT' if context['status']=='CONFLICT' else 'POLICY_OUT_OF_SCOPE' if context['status']=='OUT_OF_SCOPE' else 'POLICY_UNAVAILABLE'


def equivalent(saved,fresh):
    """Ignore incidental fields, never source content, applied clauses or clock."""
    fields=('contract_version','purpose','scope','as_of','allowed','sources','clauses','applied_rule_id')
    if not isinstance(saved,dict) or not isinstance(fresh,dict): return False
    return saved.get('allowed') is True and fresh.get('allowed') is True and all(saved.get(k)==fresh.get(k) for k in fields)


def revalidate(state,db=None):
    """Reopened/exported active decisions cannot reuse unverified old authority.

    Immutable messages/events remain historical. Only the active in-memory
    conclusion is withdrawn; an ensuing explicit update persists its new state.
    """
    decision=state.get('decision')
    if not decision or not (decision.get('policy_conclusion') or decision.get('policy')): return
    saved=decision.get('policy_context',{})
    if not isinstance(saved,dict): saved={}
    if saved.get('purpose')=='policy_information':
        from policy_service import answer,POLICY_IDS,QUESTIONS
        pid=next(iter(saved.get('sources',[])),{}).get('policy_id')
        topic=next((key for key,value in POLICY_IDS.items() if value==pid),None)
        question=next((key for key,value in QUESTIONS.items() if value==topic),'unsupported')
        current_answer=answer(question)
        fresh=information(current_answer)
        route_valid=decision.get('route')=='POLICY_INFORMATION' and decision.get('explanation')==current_answer['text']
    else:
        fresh=gate_reason(decision.get('reason'),intake(db),state)
        route_valid=fresh.get('allowed') and decision.get('route')==fresh['clauses'][0]['outcome']
    attributed=(decision.get('policy')==label(fresh) and decision.get('policy_records_consulted')==fresh['sources']
                and decision.get('policy_conclusion') is True)
    if equivalent(saved,fresh) and route_valid and attributed: return
    from copy import deepcopy
    state['previous_decision']=deepcopy(decision)
    if fresh['allowed']:
        fresh=envelope(saved.get('purpose','transaction_intake'),saved.get('scope',INTAKE_SCOPE),'STALE','POLICY_CHANGED_RECONFIRM')
    elif fresh['status']=='NOT_REQUIRED':
        fresh=envelope('transaction_intake',INTAKE_SCOPE,'STALE','POLICY_ATTRIBUTION_UNVERIFIED')
    message='The earlier policy-backed outcome cannot be revalidated against the current approved evidence. It is historical only; no current policy conclusion is available. Specialist review is needed.'
    intended=decision.get('intended_reason',decision.get('reason'))
    decision.update(route='HUMAN_REVIEW',policy=None,policy_records_consulted=[],policy_context=fresh,policy_conclusion=False,
                    reason='REPORTED_UNAUTHORISED' if intended=='REPORTED_UNAUTHORISED' else fresh['reason_code'],intended_reason=intended,
                    decision_type='OPERATIONAL_REFERRAL',policy_reason_code=fresh['reason_code'],explanation=message)
    state.setdefault('review_signals',[]).append(review_signal(fresh))
    state.setdefault('messages',[]).append(('assistant',message))
    if saved.get('purpose')=='policy_information' and state.get('policy_qa'):
        state['policy_qa']=dict(state['policy_qa'],status='STALE',policy_conclusion=False,current_validation=fresh)
