"""Bounded deterministic Lloyd k-means; cluster distance is not fraud probability.

Standard-library implementation keeps this small prototype reproducible without
an additional numerical runtime. Scaling/centres fit only earlier training rows;
a later historical calibration window sets the distance threshold.
"""
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

CONFIG_PATH=Path(__file__).parent/'policies/clustering_v1.json'
NOTICE='Cluster-distance anomaly score, not a probability of fraud. No action is authorised.'


def config():
    c=json.loads(CONFIG_PATH.read_text())
    if c['version']!='DEMO-KMEANS-1.0' or c['mode'] not in ('shadow','recommend_review'):
        raise ValueError('Unsupported clustering configuration')
    bounds={'history_days':(1,365),'minimum_history':(40,300),'maximum_history':(50,500),'clusters':(1,8),
            'maximum_iterations':(1,100),'minimum_training':(20,300),'minimum_calibration':(10,100)}
    for name,(lower,upper) in bounds.items():
        if type(c[name]) is not int or not lower<=c[name]<=upper:
            raise ValueError('Invalid clustering bound')
    for name,lower,upper in [('training_fraction',.5,.85),('distance_quantile',.8,.99),('minimum_distance_threshold',.1,10),
                             ('minimum_log_amount_scale',.01,2),('categorical_weight',.1,2)]:
        if type(c[name]) not in (int,float) or not math.isfinite(c[name]) or not lower<=c[name]<=upper:
            raise ValueError('Invalid clustering parameter')
    if c['maximum_history']<c['minimum_history']:
        raise ValueError('Inconsistent history limits')
    return c


def _facts(row):
    metadata=row.get('evidence_json',{})
    if isinstance(metadata,str): metadata=json.loads(metadata)
    if not isinstance(metadata,dict): raise ValueError('Invalid transaction metadata')
    category=row.get('merchant_category',metadata.get('merchant_category','UNKNOWN'))
    if not isinstance(category,str) or not category or len(category)>32: raise ValueError('Invalid category')
    if row.get('channel') not in ('Online','Card present') or row.get('recurring') not in (0,1,False,True):
        raise ValueError('Invalid clustering features')
    if type(row.get('amount_minor')) is not int or not 0<row['amount_minor']<=9223372036854775807:
        raise ValueError('Invalid amount')
    return {'transaction_id':row['transaction_id'],'purchase_date':row['purchase_date'],'posted_date':row['posted_date'],
            'amount_minor':row['amount_minor'],'channel':row['channel'],'recurring':int(row['recurring']),
            'merchant_category':category}


def _distance(a,b):
    return sum((x-y)**2 for x,y in zip(a,b))


def _date(value):
    result=date.fromisoformat(value)
    if result.isoformat()!=value: raise ValueError('Noncanonical date')
    return result


def fit(points,k,iterations):
    """Deterministic farthest-first initialisation, stable ties, bounded Lloyd steps."""
    mean=[sum(p[i] for p in points)/len(points) for i in range(len(points[0]))]
    centres=[list(min(points,key=lambda p:(_distance(p,mean),p)))]
    for _ in range(1,min(k,len({tuple(p) for p in points}))):
        centres.append(list(max(points,key=lambda p:(min(_distance(p,c) for c in centres),p))))
    converged=False
    for step in range(iterations):
        groups=[[] for _ in centres]
        for point in points:
            nearest=min(range(len(centres)),key=lambda i:(_distance(point,centres[i]),i))
            groups[nearest].append(point)
        updated=[[sum(p[j] for p in group)/len(group) for j in range(len(mean))] if group else centres[i]
                 for i,group in enumerate(groups)]
        if max(_distance(a,b) for a,b in zip(updated,centres))<=1e-12:
            centres=updated; converged=True; break
        centres=updated
    return centres,converged,step+1


def evaluate(transaction,history,c=None):
    c=c or config()
    base={'status':'INSUFFICIENT_DATA','version':c['version'],'mode':c['mode'],'configuration':c,
          'transaction_id':transaction.get('transaction_id'),'notice':NOTICE,
          'limitations':['Same-day payments excluded; dates do not establish intraday ordering.',
                         'Customer/card-local history may be thin or contaminated. Threshold is an unvalidated prototype choice.']}
    try:
        target_day=_date(transaction['purchase_date'])
        if transaction.get('status')!='Posted' or _date(transaction['posted_date'])<target_day:
            raise ValueError('Pending/invalid target')
        if not isinstance(transaction.get('currency'),str) or not transaction['currency']:
            raise ValueError('Missing currency')
        target=_facts(transaction)
        rows=[]; seen={target['transaction_id']}
        for row in history:
            if row.get('transaction_id')==target['transaction_id']: continue
            if row.get('card_id')!=transaction.get('card_id') or row.get('account_id')!=transaction.get('account_id'): continue
            day=_date(row['purchase_date'])
            if not target_day-timedelta(days=c['history_days'])<=day<target_day: continue
            if row.get('status')=='Pending': continue
            if row.get('status')!='Posted': raise ValueError('Unknown posting state')
            posted=_date(row['posted_date'])
            if posted<day: raise ValueError('Invalid posting date')
            if posted>=target_day or row.get('currency')!=transaction['currency']: continue
            facts=_facts(row)
            if facts['transaction_id'] in seen: raise ValueError('Duplicate history')
            seen.add(facts['transaction_id']); rows.append(facts)
    except (KeyError,ValueError,TypeError,OverflowError):
        return dict(base,reason_code='CLUSTER_FEATURES_INVALID')
    rows.sort(key=lambda r:(r['purchase_date'],r['transaction_id']))
    rows=rows[-c['maximum_history']:]
    base['history_count']=len(rows)
    if len(rows)<c['minimum_history']:
        return dict(base,reason_code='CLUSTER_HISTORY_TOO_SMALL')
    cutoff=rows[min(len(rows)-1,int(len(rows)*c['training_fraction']))]['purchase_date']
    training=[r for r in rows if r['purchase_date']<cutoff and r['posted_date']<cutoff]
    calibration=[r for r in rows if r['purchase_date']>=cutoff]
    if len(training)<c['minimum_training'] or len(calibration)<c['minimum_calibration']:
        return dict(base,reason_code='CLUSTER_TEMPORAL_SPLIT_TOO_SMALL')
    categories=sorted({r['merchant_category'] for r in training})
    logs=[math.log1p(r['amount_minor']) for r in training]
    centre=sum(logs)/len(logs)
    scale=max(c['minimum_log_amount_scale'],math.sqrt(sum((x-centre)**2 for x in logs)/len(logs)))
    names=['log_amount','online','recurring']+['category:'+name for name in categories]+['unseen_category']
    def vector(row):
        weight=c['categorical_weight']
        return [(math.log1p(row['amount_minor'])-centre)/scale,weight*int(row['channel']=='Online'),weight*row['recurring']]+[
            weight*int(row['merchant_category']==category) for category in categories]+[weight*int(row['merchant_category'] not in categories)]
    points=[vector(r) for r in training]
    centres,converged,iterations=fit(points,c['clusters'],c['maximum_iterations'])
    if not converged:
        return dict(base,status='UNAVAILABLE',reason_code='CLUSTER_DID_NOT_CONVERGE')
    distances=sorted(math.sqrt(min(_distance(vector(r),p) for p in centres)) for r in calibration)
    threshold=max(c['minimum_distance_threshold'],distances[math.ceil(c['distance_quantile']*len(distances))-1])
    point=vector(target)
    closest=min(range(len(centres)),key=lambda i:(_distance(point,centres[i]),i))
    squared=[(a-b)**2 for a,b in zip(point,centres[closest])]
    distance=math.sqrt(sum(squared)); score=distance/threshold
    model={'features':names,'log_amount_mean':centre,'log_amount_scale':scale,'centres':centres,'threshold':threshold,
           'training_records':training,'calibration_records':calibration,'calibration_distances':distances,
           'training_before':cutoff,'currency':transaction['currency'],'configuration':c}
    digest=hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(base,status='ASSESSED',reason_code='CLUSTER_DISTANCE_HIGH' if score>1 else 'CLUSTER_WITHIN_DISTANCE_THRESHOLD',
                anomaly_score=score,score_definition='distance / held-out historical threshold; values > 1 flag unusualness',
                distance=distance,threshold=threshold,flagged=score>1,nearest_cluster=closest,
                contributions=sorted([{'feature':name,'squared_distance':value} for name,value in zip(names,squared)],key=lambda v:-v['squared_distance'])[:3],
                training_count=len(training),calibration_count=len(calibration),iterations=iterations,
                model_id='cluster-'+digest[:24],model=model)


def assess(transaction_id,card_id,customer_id='C-001',database=None):
    try: c=config()
    except (OSError,ValueError,KeyError,TypeError):
        return {'status':'UNAVAILABLE','reason_code':'CLUSTER_CONFIG_UNAVAILABLE','notice':NOTICE}
    path=Path(database or os.environ.get('CONCERNS_DATABASE',Path(__file__).parent/'data/disputes.sqlite'))
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            db.row_factory=sqlite3.Row; db.execute('BEGIN')
            tx=db.execute('SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND t.card_id=? AND a.customer_id=?',
                          (transaction_id,card_id,customer_id)).fetchone()
            if tx is None: return {'status':'FORBIDDEN_OR_NOT_FOUND','reason_code':'CLUSTER_TRANSACTION_NOT_VERIFIED','notice':NOTICE}
            history=[dict(r) for r in db.execute('SELECT * FROM transactions WHERE account_id=? AND card_id=?',(tx['account_id'],card_id))]
            return evaluate(dict(tx),history,c)
    except (sqlite3.Error,OSError):
        return {'status':'UNAVAILABLE','reason_code':'CLUSTER_HISTORY_UNAVAILABLE','notice':NOTICE}


def review_decision(result):
    enabled=result.get('mode')=='recommend_review'
    review=enabled and result.get('status')=='ASSESSED' and result.get('flagged') is True
    return {'policy_version':'DEMO-CLUSTER-REVIEW-1.0','mode':result.get('mode'),
            'route':'RECOMMEND_SPECIALIST_REVIEW' if review else 'NO_ADDITIONAL_ROUTE',
            'reason_codes':['CLUSTER_DISTANCE_HIGH'] if review else [],'notice':NOTICE}


def attach(state,customer_id='C-001',database=None):
    a=state.get('answers',{})
    if not a.get('transaction'): return
    result=assess(a['transaction'],a.get('card_id'),customer_id,database)
    state['clustering']=result; state['clustering_review']=review_decision(result)
    if state['clustering_review']['route']=='RECOMMEND_SPECIALIST_REVIEW':
        if 'CLUSTER_ACTIVITY_REVIEW' not in state.setdefault('review_signals',[]):
            state['review_signals'].append('CLUSTER_ACTIVITY_REVIEW')
