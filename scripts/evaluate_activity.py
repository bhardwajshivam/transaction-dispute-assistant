"""Reproducible constructed counterfactuals, separate from runtime bank data.

Run from project root: python scripts/evaluate_activity.py
Expected labels are consumed only by this evaluator, never by the assistant.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activity import evaluate, review_decision, load_rules


def transaction(reference='TARGET', amount=6000, day='2026-10-20', **changes):
    row = dict(transaction_id=reference, account_id='A-001', card_id='CARD-001', merchant_id='M-3',
               amount_minor=amount, currency='GBP', purchase_date=day, posted_date=day,
               status='Posted', order_reference='ORDER-A')
    return dict(row, **changes)


def history(amount=2000, count=10):
    return [transaction(f'H-{i}', amount, (date(2026,10,10)-timedelta(days=i)).isoformat(),
                        merchant_id='M-1', order_reference=f'ORDER-H-{i}') for i in range(count)]


def scenarios():
    result = []
    def add(name, tx, rows, codes=(), status='ASSESSED', review=False, pair=None):
        result.append({'scenario_id': name, 'pair_id': pair, 'transaction': tx, 'history': rows,
                       'expected': {'reason_codes': sorted(codes), 'status': status,
                                    'route': 'RECOMMEND_SPECIALIST_REVIEW' if review else 'NO_ADDITIONAL_ROUTE'}})
    add('amount_exact_threshold', transaction(amount=6000), history(), pair='amount_boundary')
    add('amount_one_minor_over', transaction(amount=6001), history(), ['AMOUNT_ABOVE_HISTORICAL_BASELINE'], review=True, pair='amount_boundary')
    add('high_against_low_history', transaction(), history(1000), ['AMOUNT_ABOVE_HISTORICAL_BASELINE'], review=True, pair='personal_baseline')
    add('ordinary_against_high_history', transaction(), history(3000), pair='personal_baseline')
    add('too_few_prior_payments', transaction(amount=9001), history(amount=3000,count=9), status='PARTIAL', pair='history_count')
    add('enough_prior_payments', transaction(amount=9001), history(amount=3000,count=10), ['AMOUNT_ABOVE_HISTORICAL_BASELINE'], review=True, pair='history_count')
    for name, order, code, review in [('same_order','ORDER-A','REPEATED_CHARGE_SAME_ORDER',True),
                                       ('distinct_order','ORDER-B','MATCHING_CHARGES_DISTINCT_ORDERS',False),
                                       ('unknown_order',None,'REPEATED_CHARGE_ORDER_UNKNOWN',True)]:
        add(name, transaction(amount=5000), history()+[transaction('EARLIER',5000,'2026-10-19',order_reference=order)], [code], review=review, pair='order_reference')
    add('same_day_ambiguous', transaction(amount=5000), history()+[transaction('SAME-DAY',5000)], pair='date_ordering')
    add('future_payment', transaction(amount=5000), history()+[transaction('FUTURE',5000,'2026-10-21')], pair='date_ordering')
    add('delayed_presentment', transaction(amount=5000), history()+[transaction('DELAYED',5000,'2026-10-19',posted_date='2026-10-21')])
    add('other_currency', transaction(currency='INR'), history(), status='PARTIAL')
    bad = history(); bad[0]['amount_minor'] = '2000'
    add('malformed_history', transaction(), bad, status='INSUFFICIENT_DATA')
    add('pending_target', transaction(status='Pending',posted_date=None), history(), status='INSUFFICIENT_DATA')
    add('no_history', transaction(), [], status='PARTIAL')
    return result


def run(output):
    cases = scenarios()
    rows = []
    false_flags = missed_flags = 0
    for case in cases:
        assessment = evaluate(deepcopy(case['transaction']), deepcopy(case['history']))
        routing = review_decision(assessment)
        actual = {'reason_codes': sorted(s['reason_code'] for s in assessment['signals']), 'status': assessment['status'], 'route': routing['route']}
        passed = actual == case['expected']
        expected_flag = case['expected']['route'] == 'RECOMMEND_SPECIALIST_REVIEW'
        actual_flag = actual['route'] == 'RECOMMEND_SPECIALIST_REVIEW'
        false_flags += int(actual_flag and not expected_flag)
        missed_flags += int(expected_flag and not actual_flag)
        rows.append({'scenario_id': case['scenario_id'], 'passed': passed, 'expected': case['expected'], 'actual': actual})
    report = {'rules': load_rules(), 'scenario_count': len(cases), 'passed': sum(row['passed'] for row in rows),
              'false_review_flags': false_flags, 'missed_constructed_review_flags': missed_flags, 'results': rows,
              'data_quality': {'duplicate_input_cases': len(cases)-len({json.dumps([c['transaction'],c['history']],sort_keys=True) for c in cases}),
                               'expected_route_balance': dict(Counter(c['expected']['route'] for c in cases)),
                               'expected_status_balance': dict(Counter(c['expected']['status'] for c in cases)),
                               'counterfactual_groups': dict(Counter(c['pair_id'] for c in cases if c['pair_id'])),
                               'deliberate_defects': ['Missing order reference', 'String amount in history', 'Pending target with no posting date', 'Empty and insufficient history'],
                               'construction': 'Hand-constructed numeric counterfactuals. No sampled customer prevalence or fraud labels.',
                               'label_leakage_control': 'Expected labels and scenario IDs are excluded from assessor inputs. Customer wording is absent.',
                               'limitations': 'Small engineered rule checks, not an independent estimate of fraud detection performance. No thresholds fitted to these cases.'}}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'data/activity_evaluation')
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({k: report[k] for k in ('scenario_count','passed','false_review_flags','missed_constructed_review_flags')}, indent=2))
    raise SystemExit(0 if report['passed'] == report['scenario_count'] else 1)
