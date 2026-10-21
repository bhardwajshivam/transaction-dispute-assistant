"""Deterministic, confirmed case commands. No model is an action authority.

SQLite is both the simulated bank gateway and durable command store. A real
adapter must provide the same idempotent create/status contract.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, date
import hashlib
import json
import sqlite3
from pathlib import Path
from time import time
from uuid import uuid4

from concerns import connection, codec_for, audit
from access import require_staff
from privacy import sanitise

POLICY_PATH = Path(__file__).parent / 'policies/case_intake_v1_1.json'
CONFIRM = 'Confirm and create dispute case'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS case_commands(
 command_id TEXT PRIMARY KEY, concern_id TEXT NOT NULL REFERENCES concerns,
 customer_id TEXT NOT NULL REFERENCES customers, transaction_id TEXT NOT NULL REFERENCES transactions,
 status TEXT NOT NULL CHECK(status IN ('PREPARED','CANCELLED','SUBMITTING','UNKNOWN','SUCCEEDED','REJECTED')),
 created_at REAL NOT NULL, expires_at REAL NOT NULL, confirmed_at REAL,
 case_id TEXT REFERENCES cases, reason_code TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS case_registry(
 case_id TEXT PRIMARY KEY REFERENCES cases, customer_id TEXT NOT NULL REFERENCES customers,
 transaction_id TEXT NOT NULL REFERENCES transactions, created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status='SIMULATED_OPEN'), UNIQUE(customer_id,transaction_id));
CREATE TABLE IF NOT EXISTS case_links(
 case_id TEXT REFERENCES cases, concern_id TEXT REFERENCES concerns,
 PRIMARY KEY(case_id,concern_id));
CREATE TABLE IF NOT EXISTS case_permissions(
 customer_id TEXT NOT NULL REFERENCES customers, account_id TEXT NOT NULL REFERENCES accounts,
 can_create INTEGER NOT NULL CHECK(can_create IN (0,1)), PRIMARY KEY(customer_id,account_id));
CREATE TABLE IF NOT EXISTS case_schema_versions(version INTEGER PRIMARY KEY);
'''


def initialise(db):
    db.executescript(SCHEMA)
    # Seed only once: subsequent connections must never undo a revocation.
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM case_schema_versions WHERE version=1').fetchone():
            db.execute('INSERT INTO case_permissions SELECT customer_id,account_id,1 FROM account_access')
            db.execute('INSERT INTO case_schema_versions VALUES (1)')


@dataclass(frozen=True)
class CustomerPrincipal:
    customer_id: str
    permissions: tuple
    expires_at: float


def demo_customer():
    """Trusted UI boundary for the fixed synthetic customer, not real sign-in."""
    return CustomerPrincipal('C-001', ('case:create',), time() + 900)


class CaseDenied(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _actor(principal):
    if not isinstance(principal, CustomerPrincipal) or principal.expires_at <= time() or 'case:create' not in principal.permissions:
        raise PermissionError('Case creation permission required.')
    return principal.customer_id


def _dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _policy():
    try:
        policy = json.loads(POLICY_PATH.read_text())
        from policy_contract import case_context
        context=case_context(policy)
        if not context['allowed']: raise ValueError()
        if policy['policy_id'] != 'DEMO-CASE-INTAKE' or policy['version'] != '1.1':
            raise ValueError()
        if (not isinstance(policy['supported_issues'], list) or not isinstance(policy['blocked_review_reasons'], list)
                or policy['required_transaction_status'] != 'Posted' or policy['required_route'] != 'HUMAN_REVIEW'
                or policy['outcome'] != 'SIMULATED_OPEN' or not isinstance(policy['notice'], str)):
            raise ValueError()
        return dict(policy,policy_context=context)
    except (OSError, ValueError, KeyError, TypeError):
        raise CaseDenied('CASE_POLICY_UNAVAILABLE') from None


def _snapshot(db, cid, customer):
    row = db.execute('SELECT state_json FROM concerns WHERE concern_id=? AND customer_id=?', (cid, customer)).fetchone()
    if not row:
        raise PermissionError('Concern unavailable.')
    state = json.loads(codec_for(db).open(row[0]))
    a = state.get('answers', {})
    tx = db.execute('SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND a.customer_id=? AND t.card_id=?',
                    (a.get('transaction'), customer, a.get('card_id'))).fetchone()
    if not tx:
        raise CaseDenied('TRANSACTION_NOT_VERIFIED')
    allowed = db.execute('SELECT can_create FROM case_permissions WHERE customer_id=? AND account_id=?', (customer, tx['account_id'])).fetchone()
    if not allowed or not allowed[0]:
        raise PermissionError('Case creation permission revoked.')
    p = _policy()
    if state.get('issue_kind') not in p['supported_issues']:
        raise CaseDenied('UNSUPPORTED_ISSUE_REQUIRES_HUMAN')
    if tx['status'] != p['required_transaction_status']:
        raise CaseDenied('PENDING_TRANSACTION_REQUIRES_HUMAN')
    if not a.get('elaborate') or (state.get('decision') or {}).get('route') != p['required_route']:
        raise CaseDenied('COMPLETE_CONCERN_REVIEW_FIRST')
    if set(state.get('review_reason_codes', [])) & set(p['blocked_review_reasons']):
        raise CaseDenied('UNRESOLVED_EVIDENCE_REQUIRES_HUMAN')
    from policy_contract import intake,gate_reason,equivalent
    routing=gate_reason(state['decision'].get('reason'),intake(db),state)
    if not routing['allowed']:
        raise CaseDenied('CASE_ROUTING_POLICY_UNAVAILABLE')
    if not equivalent(state['decision'].get('policy_context',{}),routing):
        raise CaseDenied('CASE_ROUTING_POLICY_REVALIDATION_REQUIRED')
    from policy_contract import label
    if state['decision'].get('policy')!=label(routing) or state['decision'].get('policy_records_consulted')!=routing['sources'] or state['decision'].get('policy_conclusion') is not True:
        raise CaseDenied('CASE_ROUTING_POLICY_REVALIDATION_REQUIRED')
    p['policy_context']=dict(p['policy_context'],applied_rule_id='CASE-01')
    # Exclude UI state/confirmation messages; include every material assertion and
    # evidence record, so a changed amount, follow-up or policy needs new consent.
    material = {k: state.get(k) for k in ('answers', 'issue_kind', 'intake', 'search_confirmation', 'decision', 'evidence', 'unusual_activity', 'activity_review', 'clustering', 'clustering_review', 'review_requirement', 'review_reason_codes')}
    material['answers'] = {k: v for k, v in a.items() if k not in ('satisfaction', 'handoff_confirm')}
    # An uncertain submission is an operational signal, not changed complaint
    # evidence. Recording it must not invalidate a safe retry of the same key.
    material['review_reason_codes'] = sorted(r for r in state.get('review_reason_codes', []) if r != 'ACTION_OUTCOME_UNKNOWN')
    material['review_requirement'] = 'REQUIRED' if material['review_reason_codes'] else 'NOT_REQUIRED'
    return sanitise({'concern': material, 'transaction': dict(tx), 'policy': p,'routing_policy_context':routing})


def prepare(concern_id, principal, database=None):
    customer = _actor(principal)
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        snapshot = _snapshot(db, concern_id, customer)
        tid = snapshot['transaction']['transaction_id']
        pending = db.execute("SELECT * FROM case_commands WHERE customer_id=? AND transaction_id=? AND status IN ('SUBMITTING','UNKNOWN')", (customer, tid)).fetchone()
        if pending:
            if pending['concern_id'] != concern_id:
                raise CaseDenied('EARLIER_SUBMISSION_UNRESOLVED')
            return _public(pending, codec_for(db))
        # Lowercase opaque IDs avoid looking like uppercase IBANs to the PII
        # scrubber when command state passes through encrypted concern storage.
        command = 'CMD-' + uuid4().hex
        now = time()
        db.execute('INSERT INTO case_commands VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (command, concern_id, customer, tid, 'PREPARED', now, now+600, None, None, 'AWAITING_CONFIRMATION', codec_for(db).seal(_dump(snapshot))))
        audit(db, concern_id, customer, 'CASE_PREPARED')
        return _public(db.execute('SELECT * FROM case_commands WHERE command_id=?', (command,)).fetchone(), codec_for(db))


def _public(row, codec):
    from policy_contract import attribution
    payload = json.loads(codec.open(row['payload_json']))
    tx = payload['transaction']
    return {k: row[k] for k in ('command_id','concern_id','status','case_id','reason_code','expires_at')} | {
        'transaction': {k: tx[k] for k in ('transaction_id','card_id','merchant','purchase_date','amount_minor','currency')},
        'reported_concern': payload['concern']['answers'].get('elaborate'),
        'issue_kind': payload['concern']['issue_kind'],
        'policy_context': payload['policy'].get('policy_context'),
        'policy_attribution': attribution(payload['policy']['policy_context']) if payload['policy'].get('policy_context') else None,
        'routing_policy_context': payload.get('routing_policy_context'),
        'policy': {k: payload['policy'][k] for k in ('policy_id','version','notice')}}


def _owned(db, command, customer):
    row = db.execute('SELECT * FROM case_commands WHERE command_id=? AND customer_id=?', (command, customer)).fetchone()
    if not row:
        raise PermissionError('Command unavailable.')
    return row


def cancel(command, principal, database=None):
    customer = _actor(principal)
    with connection(database) as db:
        row = _owned(db, command, customer)
        if row['status'] == 'PREPARED':
            db.execute("UPDATE case_commands SET status='CANCELLED',reason_code='CUSTOMER_DECLINED' WHERE command_id=? AND status='PREPARED'", (command,))
            audit(db, row['concern_id'], customer, 'CASE_CANCELLED')


def execute(command, principal, confirmation, database=None, *, fault=None):
    """Persist intent before dispatch. fault is test-only adapter fault injection.

    Same command ID is the idempotency key. UNKNOWN must be reconciled/retried
    with this key; a different key never creates a second case for the payment.
    """
    customer = _actor(principal)
    if confirmation != CONFIRM:
        raise CaseDenied('EXPLICIT_CONFIRMATION_REQUIRED')
    denial = None
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        row = _owned(db, command, customer)
        if row['status'] == 'SUCCEEDED':
            return _public(row, codec_for(db))
        if row['status'] not in ('PREPARED','UNKNOWN','SUBMITTING'):
            raise CaseDenied('COMMAND_NOT_EXECUTABLE')
        try:
            if row['confirmed_at'] is None and time() >= row['expires_at']:
                raise CaseDenied('CONFIRMATION_EXPIRED')
            unresolved = db.execute("SELECT 1 FROM case_commands c LEFT JOIN actions a ON a.idempotency_key=c.command_id "
                                    "WHERE c.customer_id=? AND c.transaction_id=? AND c.command_id!=? "
                                    "AND c.status IN ('SUBMITTING','UNKNOWN') AND a.action_id IS NULL LIMIT 1",
                                    (customer, row['transaction_id'], command)).fetchone()
            if unresolved:
                raise CaseDenied('EARLIER_SUBMISSION_UNRESOLVED')
            snapshot = _snapshot(db, row['concern_id'], customer)
            old = json.loads(codec_for(db).open(row['payload_json']))
            if _hash(snapshot) != _hash(old):
                raise CaseDenied('EVIDENCE_CHANGED_RECONFIRM')
        except (CaseDenied, PermissionError) as error:
            denial = error
            # A previously dispatched request may already have committed: retain
            # UNKNOWN until status lookup proves what happened.
            denied_status = 'REJECTED' if row['confirmed_at'] is None else 'UNKNOWN'
            db.execute('UPDATE case_commands SET status=?,reason_code=? WHERE command_id=?', (denied_status, getattr(error, 'code', 'PERMISSION_DENIED'), command))
            audit(db, row['concern_id'], customer, 'CASE_GATE_DENIED', getattr(error, 'code', 'PERMISSION_DENIED'))
        if denial is None:
            db.execute("UPDATE case_commands SET status='SUBMITTING',confirmed_at=COALESCE(confirmed_at,?),reason_code='DISPATCH_PENDING' WHERE command_id=?", (time(), command))
            audit(db, row['concern_id'], customer, 'CASE_CONFIRMED')
    if denial:
        raise denial
    try:
        if fault in ('timeout_before_commit', 'unavailable'):
            raise TimeoutError()
        _gateway(command, customer, database)
        if fault in ('timeout_after_commit', 'malformed'):
            raise TimeoutError()
    except (CaseDenied, PermissionError) as error:
        with connection(database) as db:
            db.execute("UPDATE case_commands SET status='REJECTED',reason_code=? WHERE command_id=?", (getattr(error, 'code', 'PERMISSION_DENIED'), command))
            audit(db, row['concern_id'], customer, 'CASE_GATE_DENIED', getattr(error, 'code', 'PERMISSION_DENIED'))
        raise
    except (TimeoutError, OSError, sqlite3.Error):
        with connection(database) as db:
            db.execute("UPDATE case_commands SET status='UNKNOWN',reason_code='ACTION_OUTCOME_UNKNOWN' WHERE command_id=? AND status!='SUCCEEDED'", (command,))
            audit(db, row['concern_id'], customer, 'CASE_OUTCOME_UNKNOWN', 'UNKNOWN')
        return status(command, principal, database)
    return reconcile(command, principal, database)


def _gateway(command, customer, database):
    """Atomic simulated bank API. No unconfirmed command can execute."""
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        row = _owned(db, command, customer)
        if row['confirmed_at'] is None:
            raise CaseDenied('CONFIRMED_INTENT_REQUIRED')
        # Existing action is authoritative even if evidence changed after commit.
        if db.execute('SELECT 1 FROM actions WHERE idempotency_key=?', (command,)).fetchone():
            return
        if row['status'] not in ('SUBMITTING','UNKNOWN'):
            raise CaseDenied('CONFIRMED_INTENT_REQUIRED')
        payload = _snapshot(db, row['concern_id'], customer)
        if _hash(payload) != _hash(json.loads(codec_for(db).open(row['payload_json']))):
            raise CaseDenied('EVIDENCE_CHANGED_RECONFIRM')
        existing = db.execute('SELECT case_id FROM case_registry WHERE customer_id=? AND transaction_id=?', (customer, row['transaction_id'])).fetchone()
        case_id = existing[0] if existing else 'CASE-' + uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        codec = codec_for(db)
        if not existing:
            package = {'status': 'SIMULATED_OPEN', 'created_at': now, 'customer_id': customer, 'snapshot': payload,
                       'review_lane': 'SPECIALIST_REQUIRED' if payload['concern'].get('review_requirement') == 'REQUIRED' else 'STANDARD_REVIEW'}
            db.execute('INSERT INTO cases VALUES (?,?,?)', (case_id, row['transaction_id'], codec.seal(_dump(package))))
            db.execute('INSERT INTO case_registry VALUES (?,?,?,?,?)', (case_id, customer, row['transaction_id'], now, 'SIMULATED_OPEN'))
        db.execute('INSERT OR IGNORE INTO case_links VALUES (?,?)', (case_id, row['concern_id']))
        record = codec.seal(_dump({'operation': 'CREATE_CASE' if not existing else 'LINK_EXISTING_CASE', 'command_id': command, 'confirmed_at': row['confirmed_at'], 'recorded_at': now, 'policy_hash': _hash(payload['policy']),
                                  'policy_context':payload['policy']['policy_context'],'routing_policy_context':payload['routing_policy_context']}))
        db.execute('INSERT INTO actions VALUES (?,?,?,?)', (uuid4().hex, case_id, command, record))
        db.execute('INSERT INTO audit_events VALUES (?,?,?)', (uuid4().hex, case_id, record))
        audit(db, row['concern_id'], customer, 'CASE_CREATED' if not existing else 'CASE_EXISTING_LINKED')


def status(command, principal, database=None):
    customer = _actor(principal)
    with connection(database) as db:
        return _public(_owned(db, command, customer), codec_for(db))


def reconcile(command, principal, database=None):
    customer = _actor(principal)
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        row = _owned(db, command, customer)
        action = db.execute('SELECT case_id FROM actions WHERE idempotency_key=?', (command,)).fetchone()
        if action and row['confirmed_at'] is not None:
            db.execute("UPDATE case_commands SET status='SUCCEEDED',case_id=?,reason_code='CASE_RECORDED' WHERE command_id=?", (action[0], command))
            audit(db, row['concern_id'], customer, 'CASE_STATUS_VERIFIED')
        elif row['status'] in ('SUBMITTING','UNKNOWN'):
            db.execute("UPDATE case_commands SET status='UNKNOWN',reason_code='ACTION_OUTCOME_UNKNOWN' WHERE command_id=?", (command,))
        return _public(_owned(db, command, customer), codec_for(db))


def latest(concern_id, principal, database=None):
    customer = _actor(principal)
    with connection(database) as db:
        row = db.execute('SELECT * FROM case_commands WHERE concern_id=? AND customer_id=? ORDER BY rowid DESC LIMIT 1', (concern_id, customer)).fetchone()
        return _public(row, codec_for(db)) if row else None


def staff_cases(principal, customer_id='C-001', database=None):
    require_staff(principal, customer_id)
    with connection(database) as db:
        audit(db, None, principal.actor_id, 'STAFF_CASES_READ')
        cases = [dict(r) for r in db.execute('SELECT r.*,c.record_json FROM case_registry r JOIN cases c USING(case_id) WHERE r.customer_id=? ORDER BY r.created_at DESC', (customer_id,))]
        for row in cases:
            row['record'] = json.loads(codec_for(db).open(row.pop('record_json')))
            row['concern_ids'] = [r[0] for r in db.execute('SELECT concern_id FROM case_links WHERE case_id=?', (row['case_id'],))]
        commands = [dict(r) for r in db.execute("SELECT command_id,concern_id,status,reason_code FROM case_commands WHERE customer_id=? AND status IN ('SUBMITTING','UNKNOWN')", (customer_id,))]
        return cases, commands
