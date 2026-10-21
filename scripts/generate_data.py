"""Standard-library-only reproducible synthetic fixture generation."""
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import random

SNAPSHOT = date(2026, 10, 20)
VERSION = '1.1'


def evidence(source, reference):
    return {'source': source, 'source_reference': reference,
            'observed_at': '2026-10-20T00:00:00Z', 'verification_status': 'synthetic_verified'}


def generate_merchants():
    return [dict(merchant_id=f'M-{i}', trading_name=name, descriptor=descriptor,
                 provenance='synthetic curated mapping')
            for i, (name, descriptor) in enumerate([
                ('Northstar Coffee', 'NSC HOSPITALITY'), ('Streamwave', 'STREAMWAVE MONTHLY'),
                ('Market Square', 'MARKET SQ ONLINE'), ('City Transport', 'CITY TRANSIT'),
                ('Market Square Express', 'MARKET SQ EXPRESS')], 1)]


def generate_accounts(count, cards_per_customer=1):
    accounts = [dict(customer_id=f'C-{i:03}', account_id=f'A-{i:03}', card_id=f'CARD-{i:03}',
                 display_name='Alex Morgan' if i == 1 else f'Demo Customer {i}',
                 currency='GBP', authorised_customer_ids=[f'C-{i:03}'],
                 **evidence('demo_identity_service', f'A-{i:03}')) for i in range(1, count + 1)]
    extras = []
    for number in range(2, cards_per_customer + 1):
        for base in accounts:
            account_id = f"{base['account_id']}-{number}"
            extras.append(dict(base, account_id=account_id, card_id=f"{base['card_id']}-{number}",
                               **evidence('demo_identity_service', account_id)))
    return accounts + extras


def generate_transactions(rng, accounts, merchants, history_size):
    result = []
    for account in accounts:
        for j in range(history_size):
            m = merchants[rng.randrange(len(merchants))]
            # Anchor records preserve the interactive examples; remaining history is sampled.
            anchors = [(0, 3, 850, 'Posted'), (1, 4, 1299, 'Posted'),
                       (2, 5, 4200, 'Posted'), (2, 5, 4200, 'Posted'), (3, 1, 680, 'Pending')]
            if account == accounts[0] and j < 5:
                mi, days, amount, status = anchors[j]
                m = merchants[mi]
            else:
                days = rng.randint(1, 90)
                amount = 1299 if m['merchant_id'] == 'M-2' else rng.randint(250, 25000)
                status = 'Posted' if days > 2 else rng.choice(['Posted', 'Pending'])
            tid = f'TX-{1001 + len(result)}'
            occurred = SNAPSHOT - timedelta(days=days)
            result.append(dict(transaction_id=tid, account_id=account['account_id'],
                card_id=account['card_id'], merchant_id=m['merchant_id'],
                merchant=m['trading_name'], descriptor=m['descriptor'],
                purchase_date=occurred.isoformat(),
                posted_date=(occurred + timedelta(days=0 if j < 5 else min(2, days))).isoformat() if status == 'Posted' else None,
                amount_minor=amount, currency='GBP', original_amount_minor=amount,
                original_currency='GBP', status=status,
                channel='Online' if m['merchant_id'] in ['M-2', 'M-3', 'M-5'] else 'Card present',
                recurring=m['merchant_id'] == 'M-2',
                order_reference=f'ORDER-{tid}', **evidence('demo_transaction_service', tid)))
    return result


def inr_example():
    """Explicit optional INR fixture; no FX conversion is implied."""
    return dict(transaction_id='TX-999001', account_id='A-001', card_id='CARD-001',
                merchant_id='M-3', merchant='Market Square', descriptor='MARKET SQ ONLINE',
                purchase_date='2026-10-19', posted_date='2026-10-19', amount_minor=20000,
                currency='INR', original_amount_minor=20000, original_currency='INR',
                status='Posted', channel='Online', recurring=False,
                order_reference='ORDER-TX-999001', **evidence('demo_transaction_service', 'TX-999001'))


def generate_supporting_records(transactions):
    receipts, cancellations, refunds, credits = [], [], [], []
    for t in transactions:
        tid = t['transaction_id']
        receipts.append(dict(receipt_id=f'RECEIPT-{tid}', transaction_id=tid,
            order_reference=t['order_reference'], agreed_amount_minor=t['amount_minor'],
            currency=t['currency'], adjustment_minor=0, **evidence('demo_merchant_service', tid)))
        if t['recurring']:
            cancellations.append(dict(cancellation_id=f'CANCEL-{tid}', transaction_id=tid,
                requested_date=(date.fromisoformat(t['purchase_date']) - timedelta(days=3)).isoformat(),
                effective_date=(date.fromisoformat(t['purchase_date']) - timedelta(days=1)).isoformat(),
                method='Email', confirmation_reference=f'CN-{tid}', **evidence('demo_merchant_service', tid)))
        if t['status'] == 'Posted' and int(tid.split('-')[1]) % 7 == 0:
            refund_id = f'REFUND-{tid}'
            refunds.append(dict(refund_id=refund_id, transaction_id=tid, amount_minor=t['amount_minor'],
                currency=t['currency'], processed_date='2026-10-19', destination_card_id=t['card_id'],
                status='Processed', **evidence('demo_refund_service', refund_id)))
            credits.append(dict(credit_id=f'CREDIT-{tid}', refund_id=refund_id, account_id=t['account_id'],
                amount_minor=t['amount_minor'], currency=t['currency'], posted_date='2026-10-20',
                **evidence('demo_credit_service', refund_id)))
    return receipts, cancellations, refunds, credits


def generate_policies():
    return [dict(policy_id='DEMO-INTAKE', version='1.1', fictional=True,
        effective_from='2026-01-01', effective_to=None, scope='synthetic card intake only',
        rules=[{'rule_id': 'P-01', 'condition': 'Customer confirms recognition and resolution', 'outcome': 'EXPLAIN'},
               {'rule_id': 'P-02', 'condition': 'Customer reports payment without permission', 'outcome': 'HUMAN_REVIEW'},
               {'rule_id': 'P-03', 'condition': 'Unresolved billing, cancellation or refund concern', 'outcome': 'HUMAN_REVIEW'}])]


def generate_scenarios(split, transactions):
    # Labels are deliberately outside runtime data. These are human-constructed reference cases.
    statements = {'development': ['I cannot place this payment.', 'A payment followed my cancellation.', 'Two entries look alike.', 'I am waiting for my money back.'],
                  'evaluation': ['Can you help identify this debit?', 'Why was there a debit after I ended my plan?', 'My statement appears to repeat a purchase.', 'The seller says they sent a credit.']}
    families = ['recognition', 'cancellation', 'billing', 'refund']
    cases, conversations = [], []
    for i, family in enumerate(families):
        tid = transactions[[0, 1, 2, 3][i]]['transaction_id']
        sid = f'{split}-{family}'
        conversations.append(dict(scenario_id=sid, transaction_id=tid, initial_statement=statements[split][i],
                                  source='customer_assertion', verified=False))
        cases.append(dict(scenario_id=sid, transaction_id=tid, family=family,
            expected_next_question={'recognition': 'recognise', 'cancellation': 'cancel_type', 'billing': 'billing_type', 'refund': 'refund_status'}[family],
            expected_initial_route='GATHER_EVIDENCE', forbidden_actions=['AUTO_REFUND', 'UNCONFIRMED_CASE_CREATION'],
            rationale='Initial complaint does not contain enough evidence for a final decision.'))
    return conversations, cases


def generate_tool_fixtures():
    return [dict(fixture_id=f'TOOL-{status}', operation='get_transaction', status=status,
                 data=None if status != 'SUCCESS' else {'transaction_id': 'TX-1001'})
            for status in ['SUCCESS', 'NOT_FOUND', 'FORBIDDEN', 'UNAVAILABLE', 'MALFORMED', 'UNKNOWN_OUTCOME']]


def validate(data):
    txs = data['transactions']; ids = [t['transaction_id'] for t in txs]
    accounts = {a['account_id'] for a in data['accounts']}
    merchants = {m['merchant_id'] for m in data['merchants']}
    errors = []
    if len(ids) != len(set(ids)): errors.append('Duplicate transaction IDs')
    for t in txs:
        if t['account_id'] not in accounts or t['merchant_id'] not in merchants: errors.append('Broken transaction reference')
        if not isinstance(t['amount_minor'], int) or t['amount_minor'] <= 0: errors.append('Invalid amount')
        if t['posted_date'] and t['posted_date'] < t['purchase_date']: errors.append('Posting precedes purchase')
    for table in ['receipts', 'cancellations', 'refunds']:
        if any(r['transaction_id'] not in ids for r in data[table]): errors.append(f'Broken {table} reference')
    signatures = Counter((t['account_id'], t['merchant_id'], t['purchase_date'], t['amount_minor']) for t in txs)
    return dict(errors=errors, transaction_count=len(txs), status_balance=dict(Counter(t['status'] for t in txs)),
        recurring_count=sum(t['recurring'] for t in txs),
        duplicate_looking_groups=sum(n > 1 for n in signatures.values()),
        missing_posted_dates=sum(t['posted_date'] is None for t in txs),
        notes=['Duplicate-looking entries are intentional and do not establish duplicate processing.',
               'Missing posting dates are expected for pending payments.',
               'Initial fixtures are not statistically representative; currency coverage is explicit rather than calibrated.',
               'Reference scenarios cover question selection, not final policy outcomes.',
               'Development/evaluation wording differs but scenario families overlap; not an independent generalisation benchmark.'])


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def generate(output, seed=42, customers=3, history_size=30, cards_per_customer=1, include_inr_example=False):
    if customers < 2 or history_size < 5:
        raise ValueError('Use at least 2 customers and 5 transactions per customer.')
    if type(cards_per_customer) is not int or not 1 <= cards_per_customer <= 10:
        raise ValueError('cards_per_customer must be between 1 and 10')
    rng = random.Random(seed)
    accounts = generate_accounts(customers, cards_per_customer)
    merchants = generate_merchants()
    transactions = generate_transactions(rng, accounts, merchants, history_size)
    if include_inr_example:
        transactions.append(inr_example())
    receipts, cancellations, refunds, credits = generate_supporting_records(transactions)
    data = dict(accounts=accounts, merchants=merchants, transactions=transactions, receipts=receipts,
                cancellations=cancellations, refunds=refunds, credits=credits, policies=generate_policies(),
                cases=[], actions=[], audit_events=[])
    report = validate(data)
    if report['errors']: raise ValueError(report['errors'])
    for name, records in data.items(): write_json(output / 'runtime' / f'{name}.json', records)
    for split, account in [('development', accounts[0]), ('evaluation', accounts[1])]:
        rows = [t for t in transactions if t['account_id'] == account['account_id']]
        conversations, cases = generate_scenarios(split, rows)
        write_json(output / split / 'customer_statements.json', conversations)
        write_json(output / split / 'expected_outcomes.json', cases)
    write_json(output / 'testing' / 'tool_responses.json', generate_tool_fixtures())
    write_json(output / 'quality_report.json', report)
    # Hash generator-owned outputs only: evaluator reports in the same data
    # directory must not change the reproducibility manifest.
    owned = [output / 'runtime' / f'{name}.json' for name in data]
    owned += [output / split / name for split in ('development', 'evaluation')
              for name in ('customer_statements.json', 'expected_outcomes.json')]
    owned += [output / 'testing/tool_responses.json', output / 'quality_report.json']
    hashes = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(owned)}
    write_json(output / 'manifest.json', dict(generator_version=VERSION, seed=seed, customers=customers,
        transactions_per_card=history_size, cards_per_customer=cards_per_customer, include_inr_example=include_inr_example, snapshot=SNAPSHOT.isoformat(), sha256=hashes))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--customers', type=int, default=3)
    parser.add_argument('--transactions-per-customer', type=int, default=30)
    parser.add_argument('--include-inr-example', action='store_true')
    parser.add_argument('--cards-per-customer', type=int, default=1)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.seed, args.customers, args.transactions_per_customer, args.cards_per_customer, args.include_inr_example), indent=2))
