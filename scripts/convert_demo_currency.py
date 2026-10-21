"""Legacy opt-in maintenance; new generators already produce INR directly.

Relabel old GBP demo facts without changing amounts or historical snapshots."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def convert(value):
    if isinstance(value, dict):
        return {k: 'INR' if (k == 'currency' or k.endswith('_currency')) and v == 'GBP' else convert(v) for k,v in value.items()}
    if isinstance(value, list):
        return [convert(v) for v in value]
    return value


def migrate(path):
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        before=db.execute("SELECT count(*) FROM transactions WHERE currency='GBP'").fetchone()[0]
        amounts=db.execute('SELECT transaction_id,amount_minor,original_amount_minor FROM transactions ORDER BY transaction_id').fetchall()
        for table,column in [('accounts','evidence_json'),('transactions','evidence_json'),('receipts','record_json'),('cancellations','record_json'),('refunds','record_json'),('credits','record_json')]:
            for rowid,payload in db.execute(f'SELECT rowid,{column} FROM {table}').fetchall():
                original=json.loads(payload)
                changed=convert(original)
                if changed!=original:
                    db.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?',(json.dumps(changed,sort_keys=True,ensure_ascii=False),rowid))
        for table in ('accounts','transactions','receipts','refunds','credits'):
            db.execute(f"UPDATE {table} SET currency='INR' WHERE currency='GBP'")
        db.execute("UPDATE transactions SET original_currency='INR' WHERE original_currency='GBP'")
        if amounts!=db.execute('SELECT transaction_id,amount_minor,original_amount_minor FROM transactions ORDER BY transaction_id').fetchall():
            raise ValueError('Amounts changed unexpectedly')
        if db.execute('PRAGMA foreign_key_check').fetchall() or db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Database verification failed')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_audit'").fetchone():
            db.execute('INSERT INTO privacy_audit VALUES (?,?,?,?,?,?)',
                       (uuid4().hex,None,'local-demo-admin','DEMO_GBP_RELABELLED_INR','SUCCESS',datetime.now(timezone.utc).isoformat()))
        remaining=db.execute("SELECT count(*) FROM transactions WHERE currency='GBP' OR original_currency='GBP'").fetchone()[0]
        return {'database':str(path),'transactions_relabelled':before,'remaining_gbp_transactions':remaining,'amounts_unchanged':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('databases',nargs='+',type=Path)
    args=parser.parse_args()
    for path in args.databases:
        print(json.dumps(migrate(path)))
