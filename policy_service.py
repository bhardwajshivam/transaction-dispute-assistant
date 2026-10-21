"""Attributed policy retrieval and bounded Q&A, without model interpretation.

The approved local corpus is authoritative only inside this simulation. Neither
customer prose nor retrieved text can select a path, execute a tool or set dates.
"""
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from policy_contract import as_of as policy_date,information

CORPUS_DIR=Path(__file__).parent/'policies/corpus'
SCOPE='synthetic card dispute information only'
QUESTIONS={
    'What evidence do I need after cancelling a subscription?':'cancellation_evidence',
    'What evidence do I need for a missing refund?':'refund_evidence',
    'Do merchant details or familiar spending prove I authorised a payment?':'merchant_recognition',
    'What evidence do I need for multiple charges or a wrong amount?':'billing_evidence',
}
POLICY_IDS={'cancellation_evidence':'DEMO-CANCEL','refund_evidence':'DEMO-REFUND',
            'merchant_recognition':'DEMO-RECOGNITION','billing_evidence':'DEMO-BILLING'}


class CorpusError(ValueError):
    pass


def _date(value):
    parsed=date.fromisoformat(value)
    if parsed.isoformat()!=value: raise ValueError('Noncanonical date')
    return parsed


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def load_corpus():
    manifest=json.loads((CORPUS_DIR/'manifest.json').read_text(),object_pairs_hook=_unique)
    if manifest['file']!='dispute_information.json' or manifest['corpus_version']!='1.0':
        raise CorpusError('POLICY_CORPUS_MALFORMED')
    raw=(CORPUS_DIR/'dispute_information.json').read_bytes()
    if len(raw)>200000: raise CorpusError('POLICY_CORPUS_MALFORMED')
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=manifest['sha256']: raise CorpusError('POLICY_INTEGRITY_FAILURE')
    corpus=json.loads(raw,object_pairs_hook=_unique)
    if corpus['corpus_version']!='1.0' or not isinstance(corpus['policies'],list):
        raise CorpusError('POLICY_CORPUS_MALFORMED')
    seen=set()
    for doc in corpus['policies']:
        pid,version=doc['policy_id'],doc['version']
        if not isinstance(pid,str) or not re.fullmatch(r'DEMO-[A-Z]+',pid) or not re.fullmatch(r'\d+\.\d+',version):
            raise CorpusError('POLICY_CORPUS_MALFORMED')
        if (pid,version) in seen: raise CorpusError('POLICY_CORPUS_MALFORMED')
        seen.add((pid,version))
        start=_date(doc['effective_from'])
        if doc['effective_to'] is not None and _date(doc['effective_to'])<=start:
            raise CorpusError('POLICY_CORPUS_MALFORMED')
        if doc['topic'] not in POLICY_IDS or POLICY_IDS[doc['topic']]!=pid or doc['scope']!=SCOPE:
            raise CorpusError('POLICY_CORPUS_MALFORMED')
        if doc['source_uri']!=f'policy://{pid}/{version}' or doc['publication_status'] not in ('published','superseded'):
            raise CorpusError('POLICY_CORPUS_MALFORMED')
        for field in ('title','authority','approval_id'):
            if not isinstance(doc[field],str) or not doc[field].strip(): raise CorpusError('POLICY_CORPUS_MALFORMED')
        if not isinstance(doc['clauses'],list) or not doc['clauses']: raise CorpusError('POLICY_CORPUS_MALFORMED')
        clauses=set()
        for clause in doc['clauses']:
            if not re.fullmatch(r'[A-Z]\d+',clause['clause_id']) or clause['clause_id'] in clauses:
                raise CorpusError('POLICY_CORPUS_MALFORMED')
            clauses.add(clause['clause_id'])
            if not isinstance(clause['text'],str) or not 1<=len(clause['text'])<=2000:
                raise CorpusError('POLICY_CORPUS_MALFORMED')
    for doc in corpus['policies']:
        if doc['supersedes'] is not None and (doc['policy_id'],doc['supersedes']) not in seen:
            raise CorpusError('POLICY_CORPUS_MALFORMED')
        if doc['supersedes'] is not None:
            previous=next(d for d in corpus['policies'] if d['policy_id']==doc['policy_id'] and d['version']==doc['supersedes'])
            if _date(previous['effective_from'])>=_date(doc['effective_from']):
                raise CorpusError('POLICY_CORPUS_MALFORMED')
    return corpus['policies'],digest


def _attribution(doc,as_of):
    return {k:doc[k] for k in ('policy_id','version','title','source_uri','authority','approval_id','effective_from','effective_to','publication_status','supersedes')} | {
        'as_of':as_of,'applicability':'HISTORICAL_APPLICABLE' if doc['publication_status']=='superseded' else 'CURRENT_AS_OF'}


def retrieve(topic,as_of=None,scope=SCOPE):
    as_of=as_of or policy_date()
    result={'status':'OUT_OF_SCOPE','reason_code':'POLICY_TOPIC_OUT_OF_SCOPE','as_of':as_of,'scope':scope,
            'sources':[],'excluded_versions':[],'clauses':[]}
    if topic not in POLICY_IDS or scope!=SCOPE: return result
    try:
        day=_date(as_of)
        docs,digest=load_corpus()
        relevant=[d for d in docs if d['topic']==topic and d['scope']==scope]
        active=[d for d in relevant if _date(d['effective_from'])<=day and (d['effective_to'] is None or day<_date(d['effective_to']))]
        result['corpus_sha256']=digest
        result['excluded_versions']=[{'policy_id':d['policy_id'],'version':d['version'],'publication_status':d['publication_status'],
                                     'reason':'NOT_EFFECTIVE_AS_OF','effective_from':d['effective_from'],'effective_to':d['effective_to']} for d in relevant if d not in active]
        if not active: return dict(result,status='NOT_FOUND',reason_code='POLICY_NOT_EFFECTIVE')
        if len(active)!=1:
            return dict(result,status='CONFLICT',reason_code='POLICY_VERSION_CONFLICT',sources=[_attribution(d,as_of) for d in active])
        doc=active[0]
        return dict(result,status='SUCCESS',reason_code='POLICY_RETRIEVED',sources=[_attribution(doc,as_of)],
                    clauses=[dict(c,source_uri=f"{doc['source_uri']}#{c['clause_id']}") for c in doc['clauses']])
    except CorpusError as error:
        return dict(result,status='UNAVAILABLE',reason_code=str(error))
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return dict(result,status='UNAVAILABLE',reason_code='POLICY_CORPUS_UNAVAILABLE_OR_MALFORMED')


def classify(question):
    if question in QUESTIONS: return QUESTIONS[question]
    q=question.casefold()
    if re.search(r'\b(eligible|eligibility|entitled|entitlement|qualify|guarantee|guaranteed|deadline|liability|days|legal|historical|superseded|version|mortgage|insurance|loan)\b|\bas of\b|\bold policy\b|\b20\d{2}\b',q):
        return 'out_of_scope'
    topics=[]
    if re.search(r'cancel|subscription|recurring',q): topics.append('cancellation_evidence')
    if re.search(r'refund',q): topics.append('refund_evidence')
    if re.search(r'merchant|recognis|recogniz|authoris|authoriz',q): topics.append('merchant_recognition')
    if re.search(r'duplicate|multiple charges|wrong amount|charged twice',q): topics.append('billing_evidence')
    if len(topics)!=1: return None
    if re.search(r'\b(evidence|documents?|provide|need|prove|proof)\b',q): return topics[0]
    return None


def answer(question,as_of=None):
    topic=classify(question)
    if topic is None:
        return {'status':'CLARIFY','reason_code':'POLICY_QUESTION_AMBIGUOUS','policy_conclusion':False,'sources':[],
                'text':'Please choose one of the supported policy questions so I do not guess which policy applies.'}
    evidence=retrieve(topic,as_of)
    context=information(evidence,as_of)
    if not context['allowed']:
        return dict(evidence,status=context['status'],reason_code=context['reason_code'],policy_context=context,policy_conclusion=False,
                    text='I cannot give a policy conclusion: the requested material is outside scope, missing, conflicting or cannot be verified. You can request human assistance. No eligibility or refund decision has been made.')
    source=evidence['sources'][0]
    header=f"Fictional prototype policy, applicable as of {evidence['as_of']}: {source['title']} ({source['policy_id']} v{source['version']})."
    header+=f" Effective from {source['effective_from']}; effective to {source['effective_to'] or 'no scheduled end'}."
    if source['supersedes']: header+=f" Supersedes v{source['supersedes']}."
    lines=[header]+[f"• {c['text']} [Source: {c['source_uri']}]" for c in evidence['clauses']]
    lines+=['This is general evidence-collection guidance, not a decision about your account, eligibility or refund.']
    return dict(evidence,policy_context=context,policy_conclusion=True,text='\n\n'.join(lines))
