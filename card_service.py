"""Confirmed, idempotent card controls against a simulator, never a bank API."""
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from pathlib import Path
from time import time
from uuid import uuid4
from concerns import connection, audit
from policy_contract import active, as_of, envelope, source

POLICY = Path(__file__).parent/'policies/card_protection_v1.json'
APPROVED = POLICY.with_name('card_protection_approved.json')
CONFIRM = 'Confirm simulated card protection'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS card_controls(
 card_id TEXT PRIMARY KEY REFERENCES accounts(card_id),
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','LOCKED','BLOCKED')),
 version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS card_permissions(
 customer_id TEXT REFERENCES customers, account_id TEXT REFERENCES accounts,
 can_protect INTEGER NOT NULL CHECK(can_protect IN (0,1)), PRIMARY KEY(customer_id,account_id));
CREATE TABLE IF NOT EXISTS card_control_schema(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS card_commands(
 command_id TEXT PRIMARY KEY, concern_id TEXT NOT NULL REFERENCES concerns,
 customer_id TEXT NOT NULL REFERENCES customers, card_id TEXT NOT NULL REFERENCES accounts(card_id),
 action TEXT NOT NULL CHECK(action IN ('LOCK','BLOCK')),
 status TEXT NOT NULL CHECK(status IN ('PREPARED','CANCELLED','SUBMITTING','UNKNOWN','SUCCEEDED','REJECTED')),
 created_at REAL NOT NULL, expires_at REAL NOT NULL, confirmed_at REAL,
 expected_version INTEGER NOT NULL, policy_hash TEXT NOT NULL, reason_code TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS card_actions(
 command_id TEXT PRIMARY KEY REFERENCES card_commands, card_id TEXT NOT NULL REFERENCES accounts(card_id),
 previous_status TEXT NOT NULL, resulting_status TEXT NOT NULL, changed INTEGER NOT NULL,
 recorded_at REAL NOT NULL);
'''


def initialise(db):
    db.executescript(SCHEMA)
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM card_control_schema WHERE version=1').fetchone():
            db.execute('INSERT INTO card_permissions SELECT customer_id,account_id,1 FROM account_access')
            db.execute("INSERT INTO card_controls(card_id,status) SELECT card_id,'ACTIVE' FROM accounts")
            db.execute('INSERT INTO card_control_schema VALUES (1)')


@dataclass(frozen=True)
class CardPrincipal:
    customer_id: str
    permissions: tuple
    expires_at: float


def demo_principal():
    return CardPrincipal('C-001', ('card:protect',), time()+900)


class CardDenied(ValueError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)


def _actor(principal):
    if not isinstance(principal,CardPrincipal) or principal.expires_at<=time() or 'card:protect' not in principal.permissions:
        raise PermissionError('Card protection permission required.')
    return principal.customer_id


def policy():
    try:
        raw=POLICY.read_bytes(); p=json.loads(raw); approved=json.loads(APPROVED.read_text())
        digest=hashlib.sha256(raw).hexdigest()
        if (p['policy_id']!='DEMO-CARD-PROTECTION' or p['version']!='1.0' or p['fictional'] is not True
                or p['scope']!='synthetic card controls only' or set(p['actions'])!={'LOCK','BLOCK'}
                or not all(isinstance(v,str) and v for v in p['actions'].values())
                or not isinstance(p['notice'],str) or not p['notice']
                or not active(p['effective_from'],p['effective_to'])
                or approved!={'policy_id':p['policy_id'],'version':p['version'],'sha256':digest}):
            raise ValueError()
        uri='policy://DEMO-CARD-PROTECTION/1.0'
        attribution=source(p,p['scope'],digest,uri)
        clauses=[{'clause_id':action,'text':text,'source_uri':uri+'#'+action,'outcome':'LOCKED' if action=='LOCK' else 'BLOCKED'} for action,text in p['actions'].items()]
        context=envelope('card_protection',p['scope'],'SUCCESS','CARD_POLICY_VALIDATED',[attribution],clauses)
        return {**p,'content_sha256':digest,'as_of':as_of(),'source_uri':uri,'policy_context':context}
    except (OSError,ValueError,TypeError,KeyError):
        raise CardDenied('CARD_POLICY_UNAVAILABLE') from None


def _card(db,card,customer,permission=True):
    row=db.execute('SELECT a.* FROM accounts a JOIN account_access x ON x.account_id=a.account_id WHERE a.card_id=? AND x.customer_id=?',(card,customer)).fetchone()
    if not row: raise PermissionError('Card unavailable for this customer.')
    if permission:
        allowed=db.execute('SELECT can_protect FROM card_permissions WHERE customer_id=? AND account_id=?',(customer,row['account_id'])).fetchone()
        if not allowed or not allowed[0]: raise PermissionError('Card protection permission revoked.')
    control=db.execute('SELECT * FROM card_controls WHERE card_id=?',(card,)).fetchone()
    if control is None:raise CardDenied('CARD_STATUS_UNAVAILABLE')
    return control


def _owned(db,command,customer):
    row=db.execute('SELECT * FROM card_commands WHERE command_id=? AND customer_id=?',(command,customer)).fetchone()
    if not row: raise PermissionError('Card command unavailable.')
    _card(db,row['card_id'],customer,permission=False)
    return row


def _public(db,row):
    result=dict(row)
    result['action_record']=dict(a) if (a:=db.execute('SELECT * FROM card_actions WHERE command_id=?',(row['command_id'],)).fetchone()) else None
    # Only a committed action record can support a successful completion claim.
    if result['status']=='SUCCEEDED' and result['action_record'] is None:
        raise CardDenied('CARD_ACTION_RECORD_MISSING')
    return result


def prepare(concern_id,card,action,principal,database=None):
    customer=_actor(principal)
    if action not in ('LOCK','BLOCK'):raise CardDenied('CARD_ACTION_NOT_ALLOWED')
    p=policy()
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM concerns WHERE concern_id=? AND customer_id=?',(concern_id,customer)).fetchone():
            raise PermissionError('Concern unavailable.')
        current=_card(db,card,customer)
        pending=db.execute("SELECT * FROM card_commands WHERE customer_id=? AND card_id=? AND status IN ('SUBMITTING','UNKNOWN') ORDER BY rowid DESC LIMIT 1",(customer,card)).fetchone()
        if pending:
            if pending['concern_id']!=concern_id:raise CardDenied('EARLIER_CARD_COMMAND_UNRESOLVED')
            return _public(db,pending)
        if current['status']=='BLOCKED' and action=='LOCK':raise CardDenied('BLOCKED_CARD_CANNOT_BE_DOWNGRADED')
        # A superseded, unconfirmed preview must not remain executable.
        db.execute("UPDATE card_commands SET status='CANCELLED',reason_code='PREVIEW_SUPERSEDED' WHERE concern_id=? AND status='PREPARED'",(concern_id,))
        command='CC-'+uuid4().hex; now=time()
        db.execute('INSERT INTO card_commands VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (command,concern_id,customer,card,action,'PREPARED',now,now+600,None,current['version'],p['content_sha256'],'AWAITING_CONFIRMATION'))
        audit(db,concern_id,customer,'CARD_PREPARED')
        result=_public(db,_owned(db,command,customer));result['policy']=p
        return result


def cancel(command,principal,database=None):
    customer=_actor(principal)
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        row=_owned(db,command,customer)
        if row['status']!='PREPARED':raise CardDenied('CARD_COMMAND_NOT_CANCELLABLE')
        db.execute("UPDATE card_commands SET status='CANCELLED',reason_code='CUSTOMER_DECLINED' WHERE command_id=?",(command,))
        audit(db,row['concern_id'],customer,'CARD_CANCELLED')


def reconcile(command,principal,database=None):
    customer=_actor(principal)
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE'); row=_owned(db,command,customer)
        found=db.execute('SELECT 1 FROM card_actions WHERE command_id=?',(command,)).fetchone()
        if found and row['confirmed_at'] is not None:
            db.execute("UPDATE card_commands SET status='SUCCEEDED',reason_code='SIMULATED_CARD_ACTION_RECORDED' WHERE command_id=?",(command,))
            audit(db,row['concern_id'],customer,'CARD_STATUS_VERIFIED')
        elif row['status'] in ('SUBMITTING','UNKNOWN'):
            db.execute("UPDATE card_commands SET status='UNKNOWN',reason_code='CARD_ACTION_OUTCOME_UNKNOWN' WHERE command_id=?",(command,))
        return _public(db,_owned(db,command,customer))


def latest(concern_id,principal,database=None):
    customer=_actor(principal)
    with connection(database) as db:
        row=db.execute('SELECT * FROM card_commands WHERE concern_id=? AND customer_id=? ORDER BY rowid DESC LIMIT 1',(concern_id,customer)).fetchone()
        return _public(db,_owned(db,row['command_id'],customer)) if row else None


def _gates(db,row,customer):
    current=_card(db,row['card_id'],customer)
    if policy()['content_sha256']!=row['policy_hash']:raise CardDenied('CARD_POLICY_CHANGED_RECONFIRM')
    if current['version']!=row['expected_version']:raise CardDenied('CARD_STATE_CHANGED_RECONFIRM')
    if current['status']=='BLOCKED' and row['action']=='LOCK':raise CardDenied('BLOCKED_CARD_CANNOT_BE_DOWNGRADED')
    return current


def execute(command,principal,confirmation,database=None,*,fault=None):
    customer=_actor(principal)
    if confirmation!=CONFIRM:raise CardDenied('CARD_EXPLICIT_CONFIRMATION_REQUIRED')
    denial=None
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE');row=_owned(db,command,customer)
        if row['status']=='SUCCEEDED':return _public(db,row)
        if row['status'] not in ('PREPARED','UNKNOWN','SUBMITTING'):raise CardDenied('CARD_COMMAND_NOT_EXECUTABLE')
        # A prior commit outranks stale preview state, including after a lost reply.
        committed=db.execute('SELECT 1 FROM card_actions WHERE command_id=?',(command,)).fetchone()
        if not committed:
            try:
                if row['confirmed_at'] is None and time()>=row['expires_at']:raise CardDenied('CARD_CONFIRMATION_EXPIRED')
                _gates(db,row,customer)
                other=db.execute("SELECT 1 FROM card_commands WHERE customer_id=? AND card_id=? AND command_id!=? AND status IN ('SUBMITTING','UNKNOWN')",(customer,row['card_id'],command)).fetchone()
                if other:raise CardDenied('EARLIER_CARD_COMMAND_UNRESOLVED')
            except (CardDenied,PermissionError) as error:
                denial=error
                status='UNKNOWN' if row['confirmed_at'] is not None else 'REJECTED'
                db.execute('UPDATE card_commands SET status=?,reason_code=? WHERE command_id=?',(status,getattr(error,'code','PERMISSION_DENIED'),command))
                audit(db,row['concern_id'],customer,'CARD_GATE_DENIED')
        if denial is None:
            db.execute("UPDATE card_commands SET status='SUBMITTING',confirmed_at=COALESCE(confirmed_at,?),reason_code='DISPATCH_PENDING' WHERE command_id=?",(time(),command))
            audit(db,row['concern_id'],customer,'CARD_CONFIRMED')
    if denial:raise denial
    try:
        if fault=='timeout_before_commit':raise TimeoutError()
        _gateway(command,customer,database)
        if fault=='timeout_after_commit':raise TimeoutError()
    except (CardDenied,PermissionError) as error:
        with connection(database) as db:
            db.execute("UPDATE card_commands SET status='REJECTED',reason_code=? WHERE command_id=?",(getattr(error,'code','PERMISSION_DENIED'),command))
            audit(db,row['concern_id'],customer,'CARD_GATE_DENIED')
        raise
    except (TimeoutError,OSError,sqlite3.Error):
        with connection(database) as db:
            db.execute("UPDATE card_commands SET status='UNKNOWN',reason_code='CARD_ACTION_OUTCOME_UNKNOWN' WHERE command_id=?",(command,))
            audit(db,row['concern_id'],customer,'CARD_ACTION_OUTCOME_UNKNOWN','UNKNOWN')
        return latest_by_id(command,principal,database)
    return reconcile(command,principal,database)


def latest_by_id(command,principal,database=None):
    customer=_actor(principal)
    with connection(database) as db:return _public(db,_owned(db,command,customer))


def _gateway(command,customer,database):
    with connection(database) as db:
        db.execute('BEGIN IMMEDIATE');row=_owned(db,command,customer)
        if row['confirmed_at'] is None:raise CardDenied('CARD_CONFIRMED_INTENT_REQUIRED')
        if db.execute('SELECT 1 FROM card_actions WHERE command_id=?',(command,)).fetchone():return
        if row['status'] not in ('SUBMITTING','UNKNOWN'):raise CardDenied('CARD_CONFIRMED_INTENT_REQUIRED')
        current=_gates(db,row,customer);target='LOCKED' if row['action']=='LOCK' else 'BLOCKED'
        changed=current['status']!=target
        db.execute('UPDATE card_controls SET status=?,version=version+? WHERE card_id=?',(target,int(changed),row['card_id']))
        db.execute('INSERT INTO card_actions VALUES (?,?,?,?,?,?)',(command,row['card_id'],current['status'],target,int(changed),time()))
        audit(db,row['concern_id'],customer,'SIMULATED_CARD_'+row['action'])
