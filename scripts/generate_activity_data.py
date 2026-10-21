"""Seeded richer synthetic histories. Never overwrites the existing demo DB.

python scripts/generate_activity_data.py --output data/activity_corpus
python scripts/load_database.py --source data/activity_corpus/runtime --database data/activity.sqlite
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.generate_data import (SNAPSHOT, evidence, generate_accounts, generate_policies,
                                   generate_supporting_records, validate, write_json)

VERSION = 'ACTIVITY-CORPUS-1.1'
CATEGORIES = [
    ('groceries', 'Market Square', 'MS RETAIL', 3500, .30, '5411'),
    ('coffee', 'Northstar Coffee', 'NSC HOSPITALITY', 650, .23, '5814'),
    ('transport', 'City Transport', 'CITY TRANSIT', 1100, .18, '4111'),
    ('dining', 'Harbour Kitchen', 'HK DINING GROUP', 4200, .13, '5812'),
    ('shopping', 'Oak & Field', 'OAF COMMERCE', 8000, .11, '5311'),
    ('travel', 'Wayfarer Travel', 'WF BOOKINGS', 22000, .05, '4722'),
]


def _record(rng, account, merchant, ref, day, amount, *, order=None, lag=None, recurring=False):
    lag = rng.choices([0,1,2,5], [.50,.32,.15,.03])[0] if lag is None else lag
    posted = day + timedelta(days=lag)
    pending = posted > SNAPSHOT
    hour = rng.randint(7,11) if merchant['category'] == 'coffee' else rng.randint(9,22)
    occurred = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60))
    return dict(transaction_id=ref, account_id=account['account_id'], card_id=account['card_id'],
                merchant_id=merchant['merchant_id'], merchant=merchant['trading_name'], descriptor=merchant['descriptor'],
                purchase_date=day.isoformat(), posted_date=None if pending else posted.isoformat(),
                occurred_at=occurred.isoformat(), posted_at=None if pending else datetime.combine(posted,datetime.min.time(),tzinfo=timezone.utc).replace(hour=23).isoformat(),
                amount_minor=amount, currency=account['currency'], original_amount_minor=amount, original_currency=account['currency'],
                status='Pending' if pending else 'Posted', channel='Online' if recurring or merchant['category'] in ('shopping','travel') else rng.choice(['Card present','Online']),
                recurring=recurring, order_reference=order if order is not None else f'ORD-{rng.getrandbits(64):016x}',
                merchant_country='GB' if account['currency']=='GBP' else 'IN', merchant_category=merchant['mcc'],
                **evidence('demo_transaction_service', ref))


def merchants():
    rows = []
    for i,(category,name,descriptor,_,_,mcc) in enumerate(CATEGORIES):
        for suffix in range(2):
            rows.append(dict(merchant_id=f'M-{i*2+suffix+1}', trading_name=name+(' Express' if suffix else ''),
                             descriptor=descriptor+(' EXPRESS' if suffix else ''), category=category, mcc=mcc,
                             provenance='synthetic curated trading name'))
    rows.append(dict(merchant_id='M-13',trading_name='Streamwave',descriptor='SW DIGITAL SERVICES',category='subscription',mcc='4899',provenance='synthetic curated trading name'))
    rows.append(dict(merchant_id='M-14',trading_name='Cedar Services',descriptor='CEDAR PAYMENTS',category='specialist',mcc='5999',provenance='synthetic curated trading name'))
    return rows


def _history(rng, account, merchants_by_category, count, scale, next_ref):
    rows = []
    days=[SNAPSHOT-timedelta(days=i) for i in range(1,181)]
    for _ in range(count):
        category = rng.choices(CATEGORIES, weights=[r[4] for r in CATEGORIES])[0]
        name, _, _, centre, _, _ = category
        merchant = rng.choice(merchants_by_category[name])
        # Long-tailed category amounts; customer/card scales vary independently.
        amount = max(100, round(rng.lognormvariate(math.log(centre*scale), .48)))
        # Weekday coffee/commuting and weekend leisure have different temporal
        # distributions. Exact timestamps are available for future feature work.
        weekend_weight=2.5 if name in ('dining','travel','groceries') else .35 if name in ('coffee','transport') else 1.0
        day = rng.choices(days,weights=[weekend_weight if d.weekday()>=5 else 1.0 for d in days])[0]
        rows.append(_record(rng,account,merchant,next_ref(),day,amount))
    recurring = merchants_by_category['subscription'][0]
    subscription = max(100,round(1299*scale))
    for month in range(5,11):
        rows.append(_record(rng,account,recurring,next_ref(),date(2026,month,3),subscription,recurring=True,lag=1))
    return rows


def _runtime_exceptions(rng, account, merchant, scale, next_ref):
    """Construct cases with benign truth as well as genuine processing ambiguity."""
    amount = max(5000,round(4000*scale))
    shared_order = f'ORD-{rng.getrandbits(64):016x}'
    same = [_record(rng,account,merchant,next_ref(),date(2026,10,16+i),amount,order=shared_order,lag=0) for i in range(2)]
    different = [_record(rng,account,merchant,next_ref(),date(2026,10,18+i),amount,lag=0) for i in range(2)]
    large = _record(rng,account,merchant,next_ref(),date(2026,10,18),round(150000*scale),lag=0)
    sidecar = [dict(transaction_id=large['transaction_id'],construction='legitimate_large_purchase',authorisation_truth='authorised',
                    explanation='A planned purchase with a matching merchant receipt; unusualness alone should not establish fraud.'),
               dict(transaction_id=same[1]['transaction_id'],construction='repeated_same_order',authorisation_truth='unknown',
                    explanation='Two posted charges share an order reference; processing duplication still requires investigation.'),
               dict(transaction_id=different[1]['transaction_id'],construction='two_separate_orders',authorisation_truth='authorised',
                    explanation='Same merchant and amount, distinct orders. Matching amount does not establish a duplicate.')]
    return same+different+[large], sidecar


def activity_cases(rng, account, history, allocate_ref):
    """Independent constructed route labels, not calls into the assessor.

    Baseline histories are sampled from this customer's realistic ledger. Only
    qualifying earlier INR records enter the designed boundary calculation.
    """
    prior = [deepcopy(t) for t in history if t['status']=='Posted' and t['posted_date']<'2026-10-20'
             and '2026-07-22'<=t['purchase_date']<'2026-10-20']
    if len(prior)<10:
        raise ValueError('Constructed baseline requires at least ten prior payments')
    middle = median(t['amount_minor'] for t in prior)
    # Use a curated merchant not represented in this isolated scenario history,
    # so the amount pair changes exactly one factor, without incidental repeats.
    chosen = dict(merchant_id='M-14', trading_name='Cedar Services', descriptor='CEDAR PAYMENTS',category='shopping',mcc='5999')
    base = _record(rng,account,chosen,allocate_ref(),SNAPSHOT,5000,lag=0)
    cases=[]
    def add(family, variant, tx, rows, expected_codes, expected_route, *, truth='unknown', status='ASSESSED', note=''):
        cases.append(dict(case_id=allocate_ref(), family=family, variant=variant, customer_id=account['customer_id'],
                          transaction=deepcopy(tx), history=deepcopy(rows),
                          expected=dict(reason_codes=sorted(expected_codes),route=expected_route,status=status),
                          authorisation_truth=truth, rationale=note))
    no='NO_ADDITIONAL_ROUTE'; yes='RECOMMEND_SPECIALIST_REVIEW'
    # Fractional medians: floor(3*median) sits at/below the strict boundary.
    at=max(5000,int(3*middle)); above=at+1
    low=dict(base,amount_minor=at,original_amount_minor=at)
    high=dict(base,amount_minor=above,original_amount_minor=above)
    # If the minimum floor dominates, both amounts can exceed 3x median. Such
    # rare histories get a documented context floor pair rather than fake labels.
    if at <= 3*middle:
        add('amount_boundary','at',low,prior,[],no,note='At or just below strict 3x boundary.')
        add('amount_boundary','above',high,prior,['AMOUNT_ABOVE_HISTORICAL_BASELINE'],yes,note='One minor unit crosses the amount boundary.')
    else:
        low=dict(base,amount_minor=4999,original_amount_minor=4999)
        high=dict(base,amount_minor=5000,original_amount_minor=5000)
        add('amount_boundary','at_floor_minus_one',low,prior,[],no)
        add('amount_boundary','at_floor',high,prior,['AMOUNT_ABOVE_HISTORICAL_BASELINE'],yes)
    # Labels distinguish authorisation from unusualness. Both high payments
    # deserve identical review signals despite opposite constructed truth.
    add('legitimate_exception','planned_purchase',high,prior,['AMOUNT_ABOVE_HISTORICAL_BASELINE'],yes,truth='authorised',note='Legitimate outlier: a fraud classifier would create a false alarm if it equated unusualness with fraud.')
    ordinary_amount=min(4000,max(100,round(middle)))
    ordinary=dict(base,amount_minor=ordinary_amount,original_amount_minor=ordinary_amount)
    add('normal_looking_unauthorised','reported_unapproved',ordinary,prior,[],no,truth='unauthorised',note='Normal-looking payment can still be unauthorised; customer complaint routing must operate independently.')
    for variant, order, codes, route in [('same','ORD-SHARED',['REPEATED_CHARGE_SAME_ORDER'],yes),
                                          ('different','ORD-OTHER',['MATCHING_CHARGES_DISTINCT_ORDERS'],no),
                                          ('missing','',['REPEATED_CHARGE_ORDER_UNKNOWN'],yes)]:
        tx=dict(ordinary,order_reference='ORD-SHARED')
        earlier=dict(tx,transaction_id=allocate_ref(),purchase_date='2026-10-19',posted_date='2026-10-19',order_reference=order,
                     occurred_at='2026-10-19T10:00:00+00:00',posted_at='2026-10-19T23:00:00+00:00')
        add('order_reference',variant,tx,prior+[earlier],codes,route,note='Only order reference differs between paired variants.')
    for variant,day,posting in [('earlier','2026-10-18','2026-10-18'),('same_day','2026-10-20','2026-10-20'),('future','2026-10-21','2026-10-21'),('delayed','2026-10-19','2026-10-21')]:
        tx=dict(ordinary,order_reference='ORD-SHARED')
        extra=dict(tx,transaction_id=allocate_ref(),purchase_date=day,posted_date=posting,occurred_at=day+'T10:00:00+00:00',posted_at=posting+'T23:00:00+00:00')
        codes=['REPEATED_CHARGE_SAME_ORDER'] if variant=='earlier' else []
        add('time_availability',variant,tx,prior+[extra],codes,yes if codes else no,note='Current date-only rules must not use same-day/future knowledge even though richer timestamps are stored.')
    add('sparse_history','nine_rows',ordinary,prior[:9],[],no,status='PARTIAL')
    # Hard faults deliberately live outside importable runtime tables.
    bad=deepcopy(prior); bad[0]['amount_minor']='not-an-amount'
    add('malformed_history','invalid_amount',ordinary,bad,[],no,status='INSUFFICIENT_DATA')
    return cases


def quality(data, splits):
    report=validate(data)
    rows=data['transactions']; by_id={t['transaction_id']:t for t in rows}
    errors=report['errors']
    account_cards={a['account_id']:a['card_id'] for a in data['accounts']}
    for t in rows:
        if account_cards.get(t['account_id'])!=t['card_id']: errors.append('Card/account mismatch')
        if t['occurred_at'][:10]!=t['purchase_date']: errors.append('Timestamp/date mismatch')
        if (t['status']=='Pending') != (t['posted_date'] is None): errors.append('Status/posting mismatch')
        if t['posted_at'] and t['posted_at']<t['occurred_at']: errors.append('Posting timestamp precedes purchase')
    for receipt in data['receipts']:
        if receipt['currency']!=by_id[receipt['transaction_id']]['currency']: errors.append('Receipt currency mismatch')
    dev, evaluation=splits['development'],splits['evaluation']
    people=[{c['customer_id'] for c in group} for group in (dev,evaluation)]
    if people[0]&people[1]: errors.append('Customer split leakage')
    def signatures(group):
        result=set()
        for c in group:
            target=c['transaction']
            def facts(t):
                order=t.get('order_reference')
                relation='missing' if not order else 'target_order' if order==target.get('order_reference') else 'different_order'
                return [t.get(k) for k in ('merchant_id','purchase_date','posted_date','amount_minor','currency','status')]+[relation]
            # Strip opaque IDs/account identity and incidental timestamps. Keep
            # meaningful order equality, amounts and temporal evidence.
            canonical=[facts(target),sorted([facts(t) for t in c['history']],key=lambda row:json.dumps(row))]
            result.add(hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest())
        return result
    # The legitimate-outlier scenario intentionally shares evidence with its
    # boundary neighbour but has a different constructed authorisation truth.
    repeated_inputs={name:len(cases)-len(signatures(cases)) for name,cases in splits.items()}
    cross_split=len(signatures(dev)&signatures(evaluation))
    if cross_split: errors.append('Exact cross-split input leakage')
    groups={}; neighbours=Counter()
    for t in rows:
        groups.setdefault((t['card_id'],t['merchant_id'],t['amount_minor'],t['currency']),[]).append(t)
    for group in groups.values():
        group=sorted(group,key=lambda t:t['purchase_date'])
        for i,left in enumerate(group):
            for right in group[i+1:]:
                days=(date.fromisoformat(right['purchase_date'])-date.fromisoformat(left['purchase_date'])).days
                if days>3: break
                kind='missing_order' if not left['order_reference'] or not right['order_reference'] else 'same_order' if left['order_reference']==right['order_reference'] else 'distinct_orders'
                neighbours[kind]+=1
    report.update(currency_balance=dict(Counter(t['currency'] for t in rows)),channel_balance=dict(Counter(t['channel'] for t in rows)),
                  merchant_count=len(data['merchants']),customer_count=len({a['customer_id'] for a in data['accounts']}),
                  card_history_counts=dict(Counter(t['card_id'] for t in rows)),
                  missing_order_references=sum(not t['order_reference'] for t in rows),
                  missing_receipt_count=len(rows)-len(data['receipts']),
                  delayed_presentment_count=sum(t['posted_date'] is not None and (date.fromisoformat(t['posted_date'])-date.fromisoformat(t['purchase_date'])).days>=3 for t in rows),
                  exact_cross_split_inputs=cross_split, customer_split_overlap=sorted(people[0]&people[1]),
                  repeated_inputs_within_split=repeated_inputs,
                  near_duplicate_pairs_within_three_days=dict(neighbours),
                  field_missingness={k:sum(t.get(k) in (None,'') for t in rows) for k in ('posted_date','posted_at','occurred_at','order_reference','merchant_category','merchant_country')},
                  evaluation_family_balance={name:dict(Counter(c['family'] for c in cases)) for name,cases in splits.items()},
                  evaluation_route_balance={name:dict(Counter(c['expected']['route'] for c in cases)) for name,cases in splits.items()},
                  evaluation_truth_balance={name:dict(Counter(c['authorisation_truth'] for c in cases)) for name,cases in splits.items()},
                  notes=['No real fraud prevalence or calibration is claimed.',
                         'Same family recipes deliberately recur across customer-disjoint splits; this is not family-held-out generalisation.',
                         'Repeated evaluation inputs with different truth illustrate non-identifiability of authorisation from transaction patterns.',
                         'Labels, profiles, family names, customer statements and construction metadata are excluded from runtime tables.',
                         'Near-neighbours are intentional: amount/order/time edits are grouped by family. No learned model has been fitted.'])
    return report


def generate(output,seed=20261021,customers=12,history_size=120):
    output=Path(output)
    if customers<4 or customers%2 or history_size<80:
        raise ValueError('Use an even customer count >=4 and at least 80 sampled payments per primary card.')
    rng=random.Random(seed)
    accounts=generate_accounts(customers,2)
    shops=merchants(); by_category={name:[m for m in shops if m['category']==name] for name in [r[0] for r in CATEGORIES]+['subscription']}
    used_refs=set()
    def ref():
        # Random opaque references prevent the construction sequence from
        # encoding family/route labels. Six digits also avoid PII-like numbers.
        while True:
            value=f'TX-{rng.randrange(100000,999999)}'
            if value not in used_refs:
                used_refs.add(value)
                return value
    rows=[]; design=[]; profiles=[]; protected=set(); splits={'development':[],'evaluation':[]}
    for account in accounts:
        index=int(account['customer_id'].split('-')[1])-1
        # INR amounts are generated in their own nominal scale, never converted
        # or used as a currency-normalised representation.
        scale=[.65,1.4,3.0][index%3]*3*rng.uniform(.85,1.15)
        secondary=account['card_id'].endswith('-2')
        count=round(history_size*(.35 if secondary else 1.0)*rng.uniform(.85,1.15))
        hist=_history(rng,account,by_category,count,scale,ref)
        special,meta=_runtime_exceptions(rng,account,by_category['shopping'][0],scale,ref)
        rows.extend(hist+special); design.extend(meta)
        protected.update(t['transaction_id'] for t in special)
        profiles.append(dict(customer_id=account['customer_id'],card_id=account['card_id'],spending_scale=scale,sampled_count=count,
                             profile=['lower_spend','mixed_spend','higher_spend'][index%3],sparse_secondary_card=secondary))
        if not secondary:
            split='development' if index<customers//2 else 'evaluation'
            splits[split].extend(activity_cases(rng,account,hist,ref))
    # Missing order references are facts, never a target-specific suffix/marker.
    for row in rows:
        if row['transaction_id'] not in protected and rng.random()<.035: row['order_reference']=''
    receipts,cancellations,refunds,credits=generate_supporting_records(rows)
    matching_receipt_required={d['transaction_id'] for d in design if d['construction']=='legitimate_large_purchase'}
    receipts=[r for r in receipts if r['transaction_id'] in matching_receipt_required or rng.random()>.20]
    # Existing cancellation/refund examples remain a simple supporting fixture;
    # no terminal cancellation/refund labels are asserted by this corpus.
    data=dict(accounts=accounts,merchants=shops,transactions=rows,receipts=receipts,cancellations=cancellations,
              refunds=refunds,credits=credits,policies=generate_policies(),cases=[],actions=[],audit_events=[])
    report=quality(data,splits)
    if report['errors']: raise ValueError(report['errors'][:10])
    # Reject an output containing a DB; regeneration must not accidentally alter
    # an active service directory or its operational state.
    if output.exists() and list(output.glob('*.sqlite')):
        raise ValueError('Choose a generation directory without operational databases.')
    for name,value in data.items(): write_json(output/'runtime'/f'{name}.json',value)
    for split,cases in splits.items(): write_json(output/split/'activity_cases.json',cases)
    write_json(output/'design'/'profiles.json',profiles)
    write_json(output/'design'/'runtime_exceptions.json',design)
    write_json(output/'testing'/'history_tool_responses.json',[
        {'operation':'get_card_history','status':status,'records':[],'retryable':status=='UNAVAILABLE'}
        for status in ('UNAVAILABLE','FORBIDDEN_OR_NOT_FOUND','MALFORMED')])
    write_json(output/'quality_report.json',report)
    managed=list((output/'runtime').glob('*.json'))+[output/s/'activity_cases.json' for s in splits]+[
        output/'design'/'profiles.json',output/'design'/'runtime_exceptions.json',output/'quality_report.json',output/'testing'/'history_tool_responses.json']
    hashes={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(managed)}
    write_json(output/'manifest.json',dict(generator_version=VERSION,seed=seed,customers=customers,sampled_primary_card_history=history_size,
               snapshot=SNAPSHOT.isoformat(),currency='INR',sha256=hashes))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'data/activity_corpus')
    parser.add_argument('--seed',type=int,default=20261021)
    parser.add_argument('--customers',type=int,default=12)
    parser.add_argument('--history-size',type=int,default=120)
    args=parser.parse_args()
    report=generate(args.output,args.seed,args.customers,args.history_size)
    print(json.dumps({k:report[k] for k in ('transaction_count','customer_count','currency_balance','missing_receipt_count','errors')},indent=2))
