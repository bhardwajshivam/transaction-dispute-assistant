"""Persistent, append-only concern history, separate from formal bank disputes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from review import update_review
from access import require_staff
from privacy import protect, sanitise
from secure_storage import Codec, migrate, PREFIX
import hashlib

DEFAULT_DB = Path(__file__).resolve().parent / 'data/disputes.sqlite'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS concerns(
 concern_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 revision INTEGER NOT NULL, state_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS concern_events(
 event_id TEXT PRIMARY KEY, concern_id TEXT NOT NULL REFERENCES concerns,
 recorded_at TEXT NOT NULL, question_key TEXT NOT NULL,
 customer_statement TEXT NOT NULL, state_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS concern_review(
 concern_id TEXT PRIMARY KEY REFERENCES concerns,
 review_requirement TEXT NOT NULL CHECK(review_requirement IN ('REQUIRED','NOT_REQUIRED')),
 reason_codes_json TEXT NOT NULL, customer_resolution TEXT NOT NULL,
 handoff_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handoff_requests(
 request_id TEXT PRIMARY KEY, concern_id TEXT NOT NULL UNIQUE REFERENCES concerns,
 customer_id TEXT NOT NULL REFERENCES customers, created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status='SIMULATED_QUEUED'), summary_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS privacy_audit(
 audit_id TEXT PRIMARY KEY, concern_id TEXT, actor_id TEXT NOT NULL,
 operation TEXT NOT NULL, outcome TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS concern_holds(concern_id TEXT PRIMARY KEY REFERENCES concerns, reason_code TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS concerns_customer ON concerns(customer_id,updated_at);
CREATE INDEX IF NOT EXISTS concern_events_parent ON concern_events(concern_id,recorded_at);
'''


@contextmanager
def connection(database=None):
    path = Path(database or os.environ.get('CONCERNS_DATABASE', DEFAULT_DB))
    if not path.exists():
        raise FileNotFoundError('Prepare the database before recording concerns.')
    os.chmod(path, 0o600)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA secure_delete=ON')
    try:
        # Additive migration: preserve existing records; no database reset needed.
        db.executescript(SCHEMA)
        from case_service import initialise
        initialise(db)
        from card_service import initialise as initialise_cards
        initialise_cards(db)
        encrypted_columns = [('concerns', 'state_json'), ('case_commands', 'payload_json'), ('cases', 'record_json'), ('actions', 'record_json'), ('audit_events', 'record_json')]
        sample = next((r[0] for table, column in encrypted_columns
                       if (r := db.execute(f'SELECT {column} FROM {table} WHERE {column} LIKE ? LIMIT 1', (PREFIX+'%',)).fetchone())), None)
        encrypted = sample is not None
        codec = Codec(path, encrypted_exists=encrypted)
        if encrypted:
            codec.open(sample)  # Fail before migration if the configured key is wrong.
        migrate(db, codec)
        with db:
            yield db
    finally:
        db.close()


def codec_for(db):
    return Codec(db.execute('PRAGMA database_list').fetchone()[2], encrypted_exists=True)


def audit(db, concern_id, actor_id, operation, outcome='SUCCESS'):
    db.execute('INSERT INTO privacy_audit VALUES (?,?,?,?,?,?)',
               (str(uuid4()), concern_id, actor_id, operation, outcome, datetime.now(timezone.utc).isoformat()))


def list_concerns(customer_id='C-001', database=None):
    with connection(database) as db:
        return [dict(r) for r in db.execute('SELECT concern_id,created_at,updated_at,revision FROM concerns WHERE customer_id=? ORDER BY updated_at DESC', (customer_id,))]


def get_concern(concern_id, customer_id='C-001', database=None):
    with connection(database) as db:
        row = db.execute('SELECT * FROM concerns WHERE concern_id=? AND customer_id=?', (concern_id, customer_id)).fetchone()
        if row is None:
            raise PermissionError('Concern unavailable for this customer.')
        events = [dict(r) for r in db.execute('SELECT * FROM concern_events WHERE concern_id=? ORDER BY rowid', (concern_id,))]
        codec = codec_for(db)
        result = dict(row)
        result['state_json'] = codec.open(result['state_json'])
        for event in events:
            event['state_json'] = codec.open(event['state_json'])
            event['customer_statement'] = codec.open(event['customer_statement'])
        saved_state = json.loads(result['state_json'])
        from policy_contract import revalidate
        revalidate(saved_state,db)
        if not saved_state.get('answers', {}).get('card_id'):
            tid = saved_state.get('answers', {}).get('transaction')
            tx = db.execute('SELECT t.card_id FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND a.customer_id=?', (tid, customer_id)).fetchone() if tid else None
            if tx:
                saved_state['answers']['card_id'] = tx['card_id']
            elif saved_state.get('step') in ('elaborate', 'transaction'):
                saved_state['step'] = 'card'
                saved_state['messages'].append(('assistant', 'Which card is this concern about? Please select one of your cards.'))
        if saved_state.get('step') == 'transaction' and 'intake' not in saved_state:
            saved_state['step'] = 'elaborate'
            saved_state['messages'].append(('assistant', 'Before searching, please describe your concern so I can collect and confirm the necessary details.'))
        update_review(saved_state)
        if saved_state['review_requirement'] == 'REQUIRED' and saved_state.get('step') in ('done', 'satisfaction', 'recognise') and not saved_state.get('handoff') and saved_state.get('handoff_status') != 'DECLINED':
            from review import offer_review
            offer_review(saved_state)
            from conversation import prompt
            prompt(saved_state)
        result['state_json'] = json.dumps(saved_state, ensure_ascii=False)
        return result, events


def save_note(state, question, statement, concern_id=None, revision=0,
              event_id=None, customer_id='C-001', database=None):
    """Atomic snapshot + immutable event, with retry deduplication and stale-write rejection."""
    protected = protect(statement)
    if protected.contains_secrets:
        raise ValueError('Remove authentication secrets before recording a concern.')
    statement = protected.text
    clean = sanitise(state)
    state.clear(); state.update(clean)
    event_id = event_id or str(uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    payload = json.dumps(state, ensure_ascii=False)
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        codec = codec_for(db)
        existing = db.execute('SELECT c.* FROM concern_events e JOIN concerns c USING(concern_id) WHERE e.event_id=? AND c.customer_id=?', (event_id, customer_id)).fetchone()
        if existing:
            event = db.execute('SELECT * FROM concern_events WHERE event_id=?', (event_id,)).fetchone()
            stored_event = json.loads(codec.open(event['state_json']))
            matches = (stored_event.get('snapshot_digest') == hashlib.sha256(payload.encode()).hexdigest()) if 'snapshot_digest' in stored_event else (codec.open(event['state_json']) == payload)
            if codec.open(event['customer_statement']) != statement or event['question_key'] != question or not matches:
                raise ValueError('Event ID reused with different content.')
            return existing['concern_id'], existing['revision']
        selected_card = state.get('answers', {}).get('card_id')
        if selected_card and not db.execute('SELECT 1 FROM accounts a JOIN account_access x ON x.account_id=a.account_id WHERE a.card_id=? AND x.customer_id=?', (selected_card, customer_id)).fetchone():
            raise PermissionError('Card is not accessible.')
        transaction_id = state.get('answers', {}).get('transaction')
        if transaction_id and not db.execute('SELECT 1 FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND a.customer_id=?', (transaction_id, customer_id)).fetchone():
            raise PermissionError('Transaction is not accessible.')
        if transaction_id and selected_card and not db.execute('SELECT 1 FROM transactions WHERE transaction_id=? AND card_id=?', (transaction_id, selected_card)).fetchone():
            raise PermissionError('Transaction does not belong to the selected card.')
        previous = None
        if concern_id:
            owned = db.execute('SELECT state_json FROM concerns WHERE concern_id=? AND customer_id=?', (concern_id, customer_id)).fetchone()
            if owned is None:
                raise PermissionError('Concern unavailable for this customer.')
            previous = json.loads(codec.open(owned['state_json']))
            update_review(previous)
        from policy_contract import revalidate
        revalidate(state,db)
        update_review(state, previous)
        if state['review_requirement'] == 'REQUIRED' and state.get('step') in ('satisfaction', 'recognise'):
            from review import offer_review
            offer_review(state)
            from conversation import prompt
            prompt(state)
        payload = json.dumps(state, ensure_ascii=False)
        enqueue = state.get("step") == "handoff_pending"
        if enqueue:
            if question != "handoff_confirm" or statement != "Yes, request human assistance" or state["answers"].get("handoff_confirm") != statement:
                raise ValueError('Explicit handoff confirmation required.')
            if not concern_id:
                concern_id = 'CON-' + uuid4().hex[:12].upper()
                db.execute('INSERT INTO concerns VALUES (?,?,?,?,?,?)', (concern_id, customer_id, now, now, 0, codec.seal(payload)))
                revision = 0
            queued = db.execute('SELECT request_id FROM handoff_requests WHERE concern_id=? AND customer_id=?', (concern_id, customer_id)).fetchone()
            request_id = queued['request_id'] if queued else 'HELP-' + uuid4().hex[:12].upper()
            state["handoff"] = {"request_id": request_id, "status": "SIMULATED_QUEUED"}
            state["concern_status"] = "awaiting_human"
            state["handoff_status"] = "SIMULATED_QUEUED"
            state["step"] = "done"
            state["messages"].append(("assistant", f"Your assistance request has been recorded: {request_id}. In a live banking service, a representative would contact you on your registered mobile number shortly. This is a simulation: no callback has been scheduled and no real representative has been notified."))
            payload = json.dumps(state, ensure_ascii=False)
        if concern_id:
            changed = db.execute('UPDATE concerns SET updated_at=?,revision=revision+1,state_json=? WHERE concern_id=? AND customer_id=? AND revision=?', (now, codec.seal(payload), concern_id, customer_id, revision))
            if changed.rowcount != 1:
                raise ValueError('Concern changed elsewhere or is unavailable. Reopen it before updating.')
        else:
            concern_id = 'CON-' + uuid4().hex[:12].upper()
            db.execute('INSERT INTO concerns VALUES (?,?,?,?,?,?)', (concern_id, customer_id, now, now, 1, codec.seal(payload)))
            revision = 0
        event_snapshot = json.dumps({'state_step': state['step'], 'snapshot_digest': hashlib.sha256(payload.encode()).hexdigest()})
        db.execute('INSERT INTO concern_events VALUES (?,?,?,?,?,?)', (event_id, concern_id, now, question, codec.seal(statement), codec.seal(event_snapshot)))
        audit(db, concern_id, customer_id, 'NOTE_SAVED')
        db.execute('INSERT INTO concern_review VALUES (?,?,?,?,?) ON CONFLICT(concern_id) DO UPDATE SET review_requirement=excluded.review_requirement,reason_codes_json=excluded.reason_codes_json,customer_resolution=excluded.customer_resolution,handoff_status=excluded.handoff_status',
                   (concern_id, state['review_requirement'], json.dumps(state['review_reason_codes']), state['customer_resolution'], state['handoff_status']))
        if enqueue and not queued:
            events = [dict(r) for r in db.execute('SELECT recorded_at,question_key,customer_statement FROM concern_events WHERE concern_id=? ORDER BY rowid', (concern_id,))]
            for event in events:
                event['customer_statement'] = codec.open(event['customer_statement'])
            tx = db.execute('SELECT * FROM transactions WHERE transaction_id=?', (transaction_id,)).fetchone() if transaction_id else None
            missing=[]
            if not transaction_id and state.get('issue_kind')!='policy_question' and not state.get('card_protection'): missing.append('SELECTED_TRANSACTION')
            for key,evidence in state.get('evidence',{}).items():
                if evidence.get('status') not in ('SUCCESS','NOT_FOUND'):
                    missing.append(key.upper()+'_VERIFICATION')
            if state.get('policy_qa') and not state['policy_qa'].get('policy_conclusion'):
                missing.append('APPLICABLE_POLICY_CONCLUSION')
            if state.get('review_interrupted_step'):
                missing.append('UNCOMPLETED_INTAKE_QUESTIONS')
            for field in ('cancel_date','cancel_reference','expected_amount','refund_date','refund_amount','refund_reference'):
                if state.get('answers',{}).get(field) in ('I don’t know','I don’t have it available'):
                    missing.append(field.upper())
            if state['review_reason_codes']:
                missing.append('SPECIALIST_REVIEW_OF_RECORDED_REASONS')
            attempted=[dict(row) for row in db.execute('SELECT command_id,status,case_id,reason_code,confirmed_at FROM case_commands WHERE concern_id=? ORDER BY rowid',(concern_id,))]
            attempted += [dict(row) for row in db.execute('SELECT command_id,status,card_id,action,reason_code,confirmed_at FROM card_commands WHERE concern_id=? ORDER BY rowid',(concern_id,))]
            package = {"customer_statements_unverified": events,
                       "demo_bank_facts": dict(tx) if tx else None,
                       "decision": state.get('decision'), "answers": state['answers'],
                       "evidence": state.get("evidence", {}), "controller_trace": state.get("agent_trace", []),
                       "unusual_activity": state.get('unusual_activity'), "activity_review": state.get('activity_review'),
                       "clustering": state.get('clustering'), "clustering_review": state.get('clustering_review'),
                       "card_protection": state.get('card_protection'),
                       "policy_qa": state.get('policy_qa'), "policy_qa_history": state.get('policy_qa_history', []),
                       "intake_assertions": state.get("intake_assertions", []), "search_confirmation": state.get("search_confirmation"), "extraction_trace": state.get("extraction_trace", []),
                       "proposer_trace": state.get("proposer_trace", []), "evidence_runtime": state.get("evidence_runtime", {}),
                       "review_requirement": state['review_requirement'],
                       "review_reason_codes": state['review_reason_codes'],
                       "customer_resolution": state['customer_resolution'],
                       "handoff_status": state['handoff_status'],
                       "reason_for_handoff": '; '.join(state['review_reason_codes']) if state['review_requirement']=='REQUIRED' else state['answers'].get('satisfaction', 'Customer requested assistance'),
                       "missing_information": missing,"actions_attempted":attempted,
                       "outstanding_step_at_escalation":state.get('review_interrupted_step'),
                       "policy_consulted": (state.get('decision') or {}).get('policy'),
                       "policy_context": (state.get('decision') or {}).get('policy_context'),
                       "limitations": 'No real human connection. Documents unverified; only fictional intake rules consulted.',
                       "conversation": state['messages']}
            db.execute('INSERT INTO handoff_requests VALUES (?,?,?,?,?,?)', (request_id, concern_id, customer_id, now, 'SIMULATED_QUEUED', codec.seal(json.dumps(sanitise(package), ensure_ascii=False))))
            audit(db, concern_id, customer_id, 'HANDOFF_QUEUED')
        return concern_id, revision + 1


def summary(concern_id, customer_id='C-001', database=None):
    row, events = get_concern(concern_id, customer_id, database)
    state = json.loads(row['state_json'])
    lines = [f"Concern: {concern_id}", f"First recorded (UTC): {row['created_at']}",
             f"Last updated (UTC): {row['updated_at']}", '', 'Customer statements (unverified, chronological):']
    lines += [f"{e['recorded_at']} | {e['question_key']}: {e['customer_statement']}" for e in events]
    tid = state.get('answers', {}).get('transaction')
    if tid:
        with connection(database) as db:
            tx = db.execute('SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND a.customer_id=?', (tid, customer_id)).fetchone()
            if tx:
                lines += ['', 'Current demo bank facts (database lookup):',
                          f"{tid} | {tx['merchant']} | {tx['purchase_date']} | {tx['amount_minor']} minor units {tx['currency']} | {tx['status']}"]
    lines += ['', 'Reported search details and extraction provenance (unverified):', json.dumps(state.get('intake_assertions', []), ensure_ascii=False), '', 'Confirmed search details:', json.dumps(state.get('search_confirmation'), ensure_ascii=False), '', 'Gathered evidence (synthetic read-only records):', json.dumps(state.get('evidence', {}), ensure_ascii=False), '', f"Specialist review: {state['review_requirement']}", f"Review reasons: {', '.join(state['review_reason_codes'])}", f"Customer resolution: {state['customer_resolution']}", f"Handoff status: {state['handoff_status']}", '', 'Recorded routing suggestion:', json.dumps(state.get('decision'), ensure_ascii=False),
              '', f"Outstanding workflow step: {state['step']}",
              'No bank dispute submitted or human handoff delivered. Customer statements are not independently verified.']
    lines += ['', 'Unusual activity checks (signals, not fraud findings):', json.dumps(state.get('unusual_activity'), ensure_ascii=False),
              'Separate activity review recommendation:', json.dumps(state.get('activity_review'), ensure_ascii=False)]
    lines += ['', 'Clustering assessment (not a fraud probability):', json.dumps(state.get('clustering'), ensure_ascii=False),
              'Clustering review control:', json.dumps(state.get('clustering_review'), ensure_ascii=False)]
    lines += ['', 'Retrieved policy-question evidence:', json.dumps(state.get('policy_qa_history', []), ensure_ascii=False)]
    return '\n'.join(lines)



def list_handoffs(customer_id='C-001', database=None, *, principal=None):
    """Staff gate plus server-configured customer scope."""
    require_staff(principal, customer_id)
    with connection(database) as db:
        rows = [dict(row) for row in db.execute(
            'SELECT h.request_id,h.concern_id,h.created_at,h.status,h.summary_json,c.updated_at '
            'FROM handoff_requests h JOIN concerns c ON c.concern_id=h.concern_id '
            'WHERE h.customer_id=? AND c.customer_id=? ORDER BY h.created_at DESC',
            (customer_id, customer_id))]
        audit(db, None, principal.actor_id, 'STAFF_QUEUE_READ')
        codec = codec_for(db)
        for row in rows:
            row['summary_json'] = codec.open(row['summary_json'])
        return rows



def staff_concern(concern_id, principal, customer_id='C-001', database=None):
    require_staff(principal, customer_id)
    result = get_concern(concern_id, customer_id, database)
    with connection(database) as db:
        audit(db, concern_id, principal.actor_id, 'STAFF_CONCERN_READ')
    return result


def record_export(concern_id, customer_id='C-001', database=None, principal=None):
    if principal is not None:
        require_staff(principal, customer_id)
    # Recheck ownership when the button is clicked, not just at page render.
    get_concern(concern_id, customer_id, database)
    with connection(database) as db:
        audit(db, concern_id, principal.actor_id if principal else customer_id, 'EXPORT_REQUESTED')
