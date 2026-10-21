"""Small deterministic intake baseline. Rules are fictional demo policy."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Transaction:
    reference: str
    date: date
    merchant: str
    descriptor: str
    amount: str
    status: str
    channel: str
    recurring: bool = False


def load_transactions(account_id="A-001", customer_id="C-001", database=None):
    """Read only this demo account; expected labels are never runtime inputs."""
    import sqlite3
    from pathlib import Path
    import os
    path = Path(database or os.environ.get("CONCERNS_DATABASE", Path(__file__).resolve().parent / "data" / "disputes.sqlite"))
    if not path.exists():
        raise FileNotFoundError("Prepare data: python3 scripts/generate_data.py then python3 scripts/load_database.py")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id "
            "WHERE t.account_id=? AND a.customer_id=? ORDER BY t.transaction_id",
            (account_id, customer_id),
        ).fetchall()
    return tuple(Transaction(
        reference=t["transaction_id"], date=date.fromisoformat(t["purchase_date"]),
        merchant=t["merchant"], descriptor=t["descriptor"],
        amount=f"{t['currency']} {t['amount_minor'] // 100}.{t['amount_minor'] % 100:02d}",
        status=t["status"], channel=t["channel"], recurring=t["recurring"]
    ) for t in rows if t["account_id"] == account_id)




def list_cards(customer_id='C-001', database=None):
    """Only cards on accessible accounts; labels are synthetic masked identifiers."""
    import os
    import sqlite3
    from pathlib import Path
    path = Path(database or os.environ.get('CONCERNS_DATABASE', Path(__file__).resolve().parent / 'data/disputes.sqlite'))
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT a.card_id,a.account_id FROM accounts a JOIN account_access x ON x.account_id=a.account_id WHERE x.customer_id=? ORDER BY a.card_id", (customer_id,))]


def card_label(card):
    # This fixture has no PAN. Do not represent fabricated digits as a real card number.
    return f"Demo card {card['card_id']} · account {card['account_id']}"


def selected_transactions(state, customer_id='C-001', database=None):
    """Fetch fresh candidates for the selected accessible card, not a global list."""
    card_id = state.get('answers', {}).get('card_id')
    card = next((c for c in list_cards(customer_id, database) if c['card_id'] == card_id), None)
    if not card:
        return ()
    return load_transactions(card['account_id'], customer_id, database)


def search_transactions(state, customer_id='C-001', database=None):
    """No transaction query before explicit confirmation; exact filters never relaxed."""
    if not state.get('search_confirmed') or state.get('search_confirmation') != state.get('intake') or state.get('search_card_id') != state.get('answers', {}).get('card_id'):
        return ()
    from intake import missing_field
    if missing_field(state):
        return ()
    import os
    import sqlite3
    from pathlib import Path
    from decimal import Decimal
    f = state.get('intake', {})
    path = Path(database or os.environ.get('CONCERNS_DATABASE', Path(__file__).resolve().parent / 'data/disputes.sqlite'))
    clauses = ['a.customer_id=?', 't.card_id=?']
    values = [customer_id, state.get('answers', {}).get('card_id')]
    if f.get('transaction_reference'):
        clauses.append('t.transaction_id=?'); values.append(f['transaction_reference'])
    else:
        refund = state.get('issue_kind') == 'refund'
        start = f['original_date' if refund else 'transaction_date']
        clauses.append('t.purchase_date BETWEEN ? AND ?'); values += [start, f.get('date_end', start)]
        amount, currency = ('original_amount', 'original_currency') if refund else ('charged_amount', 'charged_currency')
        if f.get(amount):
            clauses.append('t.amount_minor=?'); values.append(int(Decimal(f[amount]) * 100))
            if f.get(currency):
                clauses.append('t.currency=?'); values.append(f[currency])
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE ' + ' AND '.join(clauses) + ' ORDER BY t.purchase_date,t.transaction_id', values).fetchall()
    return tuple(Transaction(reference=t['transaction_id'], date=date.fromisoformat(t['purchase_date']),
        merchant=t['merchant'], descriptor=t['descriptor'], amount=f"{t['currency']} {t['amount_minor'] // 100}.{t['amount_minor'] % 100:02d}",
        status=t['status'], channel=t['channel'], recurring=bool(t['recurring'])) for t in rows)
