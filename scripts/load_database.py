"""Load generated runtime JSON into a new, constrained SQLite database."""
import argparse
import json
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE customers(customer_id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
CREATE TABLE accounts(account_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
 card_id TEXT NOT NULL UNIQUE, currency TEXT NOT NULL, evidence_json TEXT NOT NULL,
 UNIQUE(account_id, card_id));
CREATE TABLE account_access(account_id TEXT REFERENCES accounts, customer_id TEXT REFERENCES customers,
 PRIMARY KEY(account_id, customer_id));
CREATE TABLE merchants(merchant_id TEXT PRIMARY KEY, trading_name TEXT NOT NULL, descriptor TEXT NOT NULL, provenance TEXT NOT NULL);
CREATE TABLE transactions(transaction_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
 card_id TEXT NOT NULL, merchant_id TEXT NOT NULL REFERENCES merchants,
 merchant TEXT NOT NULL, descriptor TEXT NOT NULL, purchase_date TEXT NOT NULL,
 posted_date TEXT, amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor>0),
 currency TEXT NOT NULL, original_amount_minor INTEGER NOT NULL CHECK(original_amount_minor>0),
 original_currency TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Posted','Pending')),
 channel TEXT NOT NULL, recurring INTEGER NOT NULL CHECK(recurring IN (0,1)), order_reference TEXT NOT NULL,
 evidence_json TEXT NOT NULL, FOREIGN KEY(account_id,card_id) REFERENCES accounts(account_id,card_id),
 CHECK(posted_date IS NULL OR posted_date>=purchase_date),
 CHECK((status='Pending' AND posted_date IS NULL) OR (status='Posted' AND posted_date IS NOT NULL)));
CREATE INDEX transactions_account_date ON transactions(account_id,purchase_date);
CREATE TABLE receipts(receipt_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions,
 agreed_amount_minor INTEGER NOT NULL CHECK(agreed_amount_minor>0), currency TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE cancellations(cancellation_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions,
 requested_date TEXT NOT NULL, effective_date TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE refunds(refund_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions,
 amount_minor INTEGER NOT NULL CHECK(amount_minor>0), currency TEXT NOT NULL,
 destination_card_id TEXT NOT NULL REFERENCES accounts(card_id), status TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE credits(credit_id TEXT PRIMARY KEY, refund_id TEXT NOT NULL REFERENCES refunds,
 account_id TEXT NOT NULL REFERENCES accounts, amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 currency TEXT NOT NULL, posted_date TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE policies(policy_id TEXT NOT NULL, version TEXT NOT NULL, effective_from TEXT NOT NULL,
 effective_to TEXT, scope TEXT NOT NULL, record_json TEXT NOT NULL, PRIMARY KEY(policy_id,version));
CREATE TABLE cases(case_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions, record_json TEXT NOT NULL);
CREATE TABLE actions(action_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases, idempotency_key TEXT NOT NULL UNIQUE, record_json TEXT NOT NULL);
CREATE TABLE audit_events(event_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases, record_json TEXT NOT NULL);
CREATE TABLE dataset_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def load_database(source, destination, replace=False):
    source, destination = Path(source), Path(destination)
    if destination.exists() and not replace:
        raise FileExistsError(f'{destination} exists; use --replace only to reset demo data.')
    tables = ['accounts', 'merchants', 'transactions', 'receipts', 'cancellations', 'refunds', 'credits', 'policies', 'cases', 'actions', 'audit_events']
    data = {name: json.loads((source / f'{name}.json').read_text()) for name in tables}
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Build separately: a failed import never destroys a previously working database.
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.sqlite', delete=False) as file:
        temporary = Path(file.name)
    try:
        with sqlite3.connect(temporary) as db:
            db.executescript(SCHEMA)
            for a in data['accounts']:
                db.execute('INSERT OR IGNORE INTO customers VALUES (?,?)', (a['customer_id'], a['display_name']))
                db.execute('INSERT INTO accounts VALUES (?,?,?,?,?)', (a['account_id'], a['customer_id'], a['card_id'], a['currency'], dump(a)))
                for cid in a['authorised_customer_ids']:
                    db.execute('INSERT INTO account_access VALUES (?,?)', (a['account_id'], cid))
            for m in data['merchants']:
                db.execute('INSERT INTO merchants VALUES (?,?,?,?)', tuple(m[k] for k in ['merchant_id','trading_name','descriptor','provenance']))
            columns = ['transaction_id','account_id','card_id','merchant_id','merchant','descriptor','purchase_date','posted_date','amount_minor','currency','original_amount_minor','original_currency','status','channel','recurring','order_reference']
            for t in data['transactions']:
                values = [t[k] for k in columns] + [dump(t)]
                db.execute('INSERT INTO transactions VALUES (' + ','.join('?' for _ in values) + ')', values)
            mappings = {
                'receipts': ['receipt_id','transaction_id','agreed_amount_minor','currency'],
                'cancellations': ['cancellation_id','transaction_id','requested_date','effective_date'],
                'refunds': ['refund_id','transaction_id','amount_minor','currency','destination_card_id','status'],
                'credits': ['credit_id','refund_id','account_id','amount_minor','currency','posted_date'],
                'policies': ['policy_id','version','effective_from','effective_to','scope'],
                'cases': ['case_id','transaction_id'], 'actions': ['action_id','case_id','idempotency_key'],
                'audit_events': ['event_id','case_id']}
            for table, fields in mappings.items():
                for row in data[table]:
                    values = [row[k] for k in fields] + [dump(row)]
                    db.execute(f'INSERT INTO {table} VALUES (' + ','.join('?' for _ in values) + ')', values)
            db.execute('INSERT INTO dataset_metadata VALUES (?,?)', ('schema_version', '1'))
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Foreign-key validation failed')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {name: len(rows) for name, rows in data.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/runtime')
    parser.add_argument('--database', type=Path, default=ROOT / 'data/disputes.sqlite')
    parser.add_argument('--replace', action='store_true', help='Explicitly reset the demo database, including any stored operational records')
    args = parser.parse_args()
    print(json.dumps(load_database(args.source, args.database, args.replace), indent=2))
