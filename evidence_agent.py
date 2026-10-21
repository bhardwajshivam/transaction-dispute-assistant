"""Bounded read-only evidence loop. No LLM or action authority.

A future proposer may return the same proposal dictionaries; the controller still
validates the tool, evidence gap, selected reference, permissions and call budget.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

DEFAULT_DB = Path(__file__).resolve().parent / 'data/disputes.sqlite'
MAX_CALLS = 8
TOOLS = {
    'transaction': 'verify_selected_transaction',
    'merchant': 'resolve_merchant',
    'receipts': 'lookup_purchase_records',
    'cancellations': 'lookup_cancellation',
    'refunds': 'lookup_refund',
    'credits': 'lookup_related_credits',
    'policy': 'resolve_intake_policy',
}


def gaps(state):
    if not state.get('answers', {}).get('transaction'):
        return []
    step = state.get('step', '')
    if state.get('evidence', {}).get('transaction', {}).get('status') not in (None, 'SUCCESS'):
        return []
    if not state.get('evidence') or 'transaction' not in state['evidence']:
        return ['transaction']
    wanted = ['merchant', 'policy']
    if step.startswith('cancel') or state.get('answers', {}).get('cancel_type'):
        wanted += ['cancellations']
    if step in ('billing_type', 'duplicate', 'purchase_count', 'receipt', 'expected_amount', 'adjustment', 'expected_currency', 'currency_receipt') or state.get('answers', {}).get('billing_type'):
        wanted += ['receipts']
    if step.startswith('refund') or state.get('answers', {}).get('refund_status'):
        wanted += ['refunds', 'credits']
    return [gap for gap in wanted if gap not in state.get('evidence', {})]


def propose(state):
    missing = gaps(state)
    if not missing:
        return None
    gap = missing[0]
    return {'tool': TOOLS[gap], 'gap': gap,
            'transaction_id': state['answers']['transaction']}


def validate_proposal(state, proposal):
    if not isinstance(proposal, dict) or set(proposal) != {'tool', 'gap', 'transaction_id'}:
        return False, 'INVALID_SCHEMA'
    gap = proposal['gap']
    if not isinstance(gap, str) or TOOLS.get(gap) != proposal['tool']:
        return False, 'TOOL_NOT_ALLOWED'
    if proposal['transaction_id'] != state.get('answers', {}).get('transaction'):
        return False, 'REFERENCE_MISMATCH'
    if gap not in gaps(state):
        return False, 'NO_PERMITTED_EVIDENCE_GAP'
    if len(state.get('agent_trace', [])) >= MAX_CALLS:
        return False, 'BUDGET_EXHAUSTED'
    return True, 'VALIDATED'


def read_tool(proposal, customer_id='C-001', database=None, card_id=None):
    """Static, parameterised SQL only; scope is derived from trusted customer context."""
    path = Path(database or os.environ.get('CONCERNS_DATABASE', DEFAULT_DB))
    try:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            tx = db.execute('SELECT t.* FROM transactions t JOIN account_access a ON a.account_id=t.account_id WHERE t.transaction_id=? AND a.customer_id=?', (proposal['transaction_id'], customer_id)).fetchone()
            if tx is None or (card_id is not None and tx['card_id'] != card_id):
                return {'status': 'FORBIDDEN_OR_NOT_FOUND', 'records': []}
            gap = proposal['gap']
            tid = tx['transaction_id']
            if gap == 'transaction': rows = [dict(tx)]
            elif gap == 'merchant': rows = [dict(r) for r in db.execute('SELECT * FROM merchants WHERE merchant_id=?', (tx['merchant_id'],))]
            elif gap == 'credits': rows = [dict(r) for r in db.execute('SELECT c.* FROM credits c JOIN refunds r ON r.refund_id=c.refund_id WHERE r.transaction_id=? AND c.account_id=?', (tid, tx['account_id']))]
            elif gap == 'policy':
                from policy_contract import intake
                context=intake(db)
                return {'status':context['status'],'records':context.get('records',[]),'policy_context':context}
            else:
                queries = {'receipts': 'SELECT * FROM receipts WHERE transaction_id=?',
                           'cancellations': 'SELECT * FROM cancellations WHERE transaction_id=?',
                           'refunds': 'SELECT * FROM refunds WHERE transaction_id=?'}
                if gap not in queries:
                    return {'status': 'REJECTED', 'records': []}
                rows = [dict(r) for r in db.execute(queries[gap], (tid,))]
            for row in rows:
                for field in ('record_json', 'evidence_json'):
                    if field in row:
                        row[field] = json.loads(row[field])
                        if not isinstance(row[field], dict):
                            raise ValueError('Malformed record')
            return {'status': 'SUCCESS' if rows else 'NOT_FOUND', 'records': rows}
    except (sqlite3.Error, OSError):
        return {'status': 'UNAVAILABLE', 'records': []}
    except (ValueError, TypeError):
        return {'status': 'MALFORMED', 'records': []}


def run(state, proposer=propose, customer_id='C-001', database=None):
    """Stop on no gap, rejected proposal, failed transaction check or call limit.

    One attempt per gap per conversation snapshot; no silent retry loops.
    """
    state.setdefault('agent_trace', [])
    state.setdefault('evidence', {})
    while len(state['agent_trace']) < MAX_CALLS:
        try:
            proposal = proposer(state)
        except Exception:
            state['agent_stop_reason'] = 'PROPOSER_FAILED'
            return
        if proposal is None:
            state['agent_stop_reason'] = 'WAITING_FOR_CUSTOMER'
            return
        valid, reason = validate_proposal(state, proposal)
        trace = {'proposal': proposal, 'validation': reason,
                 'recorded_at': datetime.now(timezone.utc).isoformat()}
        state['agent_trace'].append(trace)
        if not valid:
            state['agent_stop_reason'] = reason
            return
        try:
            result = read_tool(proposal, customer_id, database, state.get('answers', {}).get('card_id'))
            statuses={'SUCCESS','NOT_FOUND','UNAVAILABLE','MALFORMED','FORBIDDEN_OR_NOT_FOUND'}
            if proposal['gap']=='policy':
                statuses.update({'CONFLICT','STALE','OUT_OF_SCOPE','NOT_REQUIRED'})
            if not isinstance(result,dict) or result.get('status') not in statuses or not isinstance(result.get('records'),list) or not all(isinstance(row,dict) for row in result.get('records',[])):
                result={'status':'MALFORMED','records':[]}
        except Exception:
            # Tool exceptions may contain credentials, query parameters or PII.
            result={'status':'UNAVAILABLE','records':[]}
        trace['result_status'] = result['status']
        gap = proposal['gap']
        state['evidence'][gap] = {'evidence_id': 'EV-' + uuid4().hex[:12],
            'source': proposal['tool'], 'transaction_id': proposal['transaction_id'],
            'observed_at': trace['recorded_at'], **result}
        signals = state.setdefault('review_signals', [])
        if gap == 'policy' and result['status'] != 'SUCCESS':
            from policy_contract import review_signal
            signal = review_signal(result['policy_context']) if isinstance(result.get('policy_context'),dict) else 'POLICY_UNAVAILABLE'
            if signal not in signals: signals.append(signal)
        if result['status'] in ('UNAVAILABLE', 'MALFORMED', 'FORBIDDEN_OR_NOT_FOUND'):
            if 'EVIDENCE_VERIFICATION_UNAVAILABLE' not in signals:
                signals.append('EVIDENCE_VERIFICATION_UNAVAILABLE')
        if gap == 'transaction' and result['status'] != 'SUCCESS':
            state['agent_stop_reason'] = 'TRANSACTION_NOT_VERIFIED'
            return
    state['agent_stop_reason'] = 'BUDGET_EXHAUSTED'
