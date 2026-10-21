"""Read-only, date-aware activity rules. Patterns are not fraud findings."""
from datetime import date, timedelta
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sqlite3

RULES_PATH = Path(__file__).parent / 'policies/activity_rules_v1.json'
LIMITATIONS = [
    'Patterns do not establish fraud or customer authorisation.',
    'Only the selected card is assessed; other cards and accounts are excluded.',
    'Date-only records cannot establish intraday ordering. Same-day transactions are excluded.',
    'Device, location and precise transaction timestamps are unavailable.',
]


def load_rules():
    rules = json.loads(RULES_PATH.read_text())
    for field in ('history_days','minimum_history','amount_multiplier','minimum_amount_minor','repeat_window_days'):
        if type(rules[field]) is not int or rules[field] <= 0:
            raise ValueError('Invalid activity rules')
    if rules['rules_version'] != 'DEMO-ACTIVITY-1.0' or rules['review_rule_version'] != 'DEMO-ACTIVITY-REVIEW-1.0':
        raise ValueError('Unsupported activity rules')
    if not isinstance(rules['review_signal_codes'], list) or not all(isinstance(c, str) for c in rules['review_signal_codes']):
        raise ValueError('Invalid review rules')
    return rules


def _date(value):
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('Noncanonical date')
    return result


def _valid(row):
    return (type(row.get('amount_minor')) is int and row['amount_minor'] > 0
            and isinstance(row.get('currency'), str) and len(row['currency']) == 3
            and row['currency'].isascii() and row['currency'].isupper() and row['currency'].isalpha()
            and all(isinstance(row.get(k), str) and row[k] for k in ('transaction_id','account_id','card_id','merchant_id'))
            and row.get('status') in ('Posted','Pending'))


def evaluate(transaction, history, rules=None):
    """Pure rules over an already-authorised snapshot; no expected labels used."""
    r = rules or load_rules()
    output = {'status': 'INSUFFICIENT_DATA', 'rules_version': r['rules_version'],
              'rules_snapshot': r, 'transaction_id': transaction.get('transaction_id'),
              'source': 'synthetic_transaction_history', 'card_id': transaction.get('card_id'),
              'signals': [], 'checks': {}, 'limitations': list(LIMITATIONS)}
    try:
        target_date = _date(transaction['purchase_date'])
        if not _valid(transaction) or transaction['status'] != 'Posted' or _date(transaction['posted_date']) < target_date:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        output['reason_code'] = 'INVALID_OR_PENDING_TRANSACTION'
        return output
    eligible, invalid, same_day = [], 0, 0
    seen = {transaction['transaction_id']}
    for row in history:
        if row.get('transaction_id') == transaction['transaction_id']:
            continue
        # Defence in depth: an upstream adapter must not mix another card in.
        if row.get('account_id') != transaction['account_id'] or row.get('card_id') != transaction['card_id']:
            continue
        try:
            purchased = _date(row['purchase_date'])
            if purchased >= target_date:
                same_day += int(purchased == target_date)
                continue
            if purchased < target_date - timedelta(days=r['history_days']):
                continue
            if not _valid(row) or row['transaction_id'] in seen:
                raise ValueError()
            seen.add(row['transaction_id'])
            if row['status'] != 'Posted':
                continue
            posted = _date(row['posted_date'])
            if posted < purchased:
                raise ValueError()
            if posted >= target_date:
                continue  # Not available in the bank history before the target.
            if row['currency'] == transaction['currency']:
                eligible.append(row)
        except (KeyError, TypeError, ValueError):
            invalid += 1
    eligible.sort(key=lambda x: x['transaction_id'])
    output.update(history_count=len(eligible), excluded_same_day_count=same_day, invalid_history_count=invalid,
                  history_window={'from': (target_date-timedelta(days=r['history_days'])).isoformat(), 'before': target_date.isoformat(), 'currency': transaction['currency']})
    baseline = {'status': 'INSUFFICIENT_DATA', 'reason_code': 'INSUFFICIENT_HISTORY', 'history_count': len(eligible)}
    if len(eligible) >= r['minimum_history'] and not invalid:
        # Integer/Fraction arithmetic keeps threshold boundaries exact.
        amounts = sorted(row['amount_minor'] for row in eligible)
        n = len(amounts)
        middle = Fraction(amounts[n//2]) if n % 2 else Fraction(amounts[n//2-1]+amounts[n//2], 2)
        baseline = {'status': 'ASSESSED', 'baseline_median_minor': float(middle), 'history_count': n}
        if transaction['amount_minor'] >= r['minimum_amount_minor'] and transaction['amount_minor'] > middle*r['amount_multiplier']:
            output['signals'].append({'reason_code': 'AMOUNT_ABOVE_HISTORICAL_BASELINE', 'severity': 'REVIEW_SIGNAL',
                                      'observed_amount_minor': transaction['amount_minor'], 'baseline_median_minor': float(middle),
                                      'currency': transaction['currency'], 'history_count': n,
                                      'transaction_ids': [row['transaction_id'] for row in eligible]})
    elif invalid:
        baseline['reason_code'] = 'MALFORMED_HISTORY'
    output['checks']['amount'] = baseline
    repeated = [row for row in eligible if row['merchant_id'] == transaction['merchant_id'] and row['amount_minor'] == transaction['amount_minor']
                and _date(row['purchase_date']) >= target_date-timedelta(days=r['repeat_window_days'])]
    repeat = {'status': 'INSUFFICIENT_DATA' if invalid else 'ASSESSED', 'matching_transaction_ids': [row['transaction_id'] for row in repeated]}
    if invalid:
        repeat['reason_code'] = 'MALFORMED_HISTORY'
    for row in repeated:
        target_order, earlier_order = transaction.get('order_reference'), row.get('order_reference')
        if not isinstance(target_order, str) or not target_order.strip() or not isinstance(earlier_order, str) or not earlier_order.strip():
            code, severity = 'REPEATED_CHARGE_ORDER_UNKNOWN', 'REVIEW_SIGNAL'
        elif target_order == earlier_order:
            code, severity = 'REPEATED_CHARGE_SAME_ORDER', 'REVIEW_SIGNAL'
        else:
            code, severity = 'MATCHING_CHARGES_DISTINCT_ORDERS', 'CONTEXT_ONLY'
        output['signals'].append({'reason_code': code, 'severity': severity, 'transaction_ids': [row['transaction_id'], transaction['transaction_id']],
                                  'currency': transaction['currency'], 'amount_minor': transaction['amount_minor']})
    output['checks']['repeated_charge'] = repeat
    statuses = [check['status'] for check in output['checks'].values()]
    output['status'] = 'ASSESSED' if all(s == 'ASSESSED' for s in statuses) else 'PARTIAL' if 'ASSESSED' in statuses or output['signals'] else 'INSUFFICIENT_DATA'
    # A compact, reproducible evidence record supports the recorded calculation.
    output['history_evidence'] = [{k: row.get(k) for k in ('transaction_id','purchase_date','posted_date','merchant_id','amount_minor','currency','order_reference')} for row in eligible]
    digest = hashlib.sha256(json.dumps({'transaction': transaction, 'history': output['history_evidence'], 'rules': r}, sort_keys=True).encode()).hexdigest()
    output['evidence_id'] = 'activity-' + digest[:24]
    return output


def assess(transaction_id, card_id, customer_id='C-001', database=None):
    """Read-only consistent bank snapshot; ownership is verified independently."""
    try:
        rules = load_rules()
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'UNAVAILABLE', 'reason_code': 'ACTIVITY_RULES_UNAVAILABLE', 'signals': [], 'limitations': list(LIMITATIONS)}
    path = Path(database or os.environ.get('CONCERNS_DATABASE', Path(__file__).parent / 'data/disputes.sqlite'))
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            tx = db.execute('SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND t.card_id=? AND a.customer_id=?',
                            (transaction_id, card_id, customer_id)).fetchone()
            if tx is None:
                return {'status': 'FORBIDDEN_OR_NOT_FOUND', 'reason_code': 'ACTIVITY_TRANSACTION_NOT_VERIFIED', 'signals': []}
            history = [dict(row) for row in db.execute('SELECT * FROM transactions WHERE account_id=? AND card_id=?', (tx['account_id'], card_id))]
            return evaluate(dict(tx), history, rules)
    except (sqlite3.Error, OSError):
        return {'status': 'UNAVAILABLE', 'reason_code': 'ACTIVITY_HISTORY_UNAVAILABLE', 'signals': [], 'limitations': list(LIMITATIONS)}


def review_decision(assessment):
    """Separate routing table. No case, refund or card-action authority."""
    rules = assessment.get('rules_snapshot', {})
    codes = sorted({s['reason_code'] for s in assessment.get('signals', []) if s.get('severity') == 'REVIEW_SIGNAL'
                    and s['reason_code'] in rules.get('review_signal_codes', [])})
    return {'policy_version': rules.get('review_rule_version'), 'route': 'RECOMMEND_SPECIALIST_REVIEW' if codes else 'NO_ADDITIONAL_ROUTE',
            'reason_codes': codes, 'assessment_status': assessment['status'],
            'notice': 'No signal is not evidence that a transaction is safe. No action is authorised.'}


def attach(state, customer_id='C-001', database=None):
    a = state.get('answers', {})
    if not a.get('transaction'):
        return
    result = assess(a['transaction'], a.get('card_id'), customer_id, database)
    state['unusual_activity'] = result
    state['activity_review'] = review_decision(result)
    if state['activity_review']['route'] == 'RECOMMEND_SPECIALIST_REVIEW':
        if 'UNUSUAL_ACTIVITY_REVIEW' not in state.setdefault('review_signals', []):
            state['review_signals'].append('UNUSUAL_ACTIVITY_REVIEW')
