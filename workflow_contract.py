"""Explicit ordinary turn graph; action services retain their own stronger guards."""
VERSION = 'DISPUTE-WORKFLOW-1.0'
EDGES = {
    'issue': {'card', 'policy_topic'},
    'card': {'elaborate'},
    'elaborate': {'search_details','search_confirm','other_transaction'},
    'different_issue': {'satisfaction'},
    'other_transaction': {'search_details','search_confirm','satisfaction'},
    'search_details': {'search_confirm'},
    'search_confirm': {'elaborate','search_details','transaction'},
    'transaction': {'elaborate','recognise','cancel_type','duplicate','expected_amount','expected_currency_only','receipt','refund_status','satisfaction'},
    'recognise': {'resolved','other_user'},
    'resolved': {'satisfaction','other_user'},
    'other_user': {'permission'},
    'permission': {'safety','satisfaction'},
    'safety': {'satisfaction'},
    'cancel_type': {'cancel_date','cancel_method'},
    'cancel_date': {'cancel_method'},
    'cancel_method': {'cancel_confirm'},
    'cancel_confirm': {'cancel_reference','satisfaction'},
    'cancel_reference': {'satisfaction'},
    'billing_type': {'duplicate','expected_amount','expected_currency'},
    'duplicate': {'purchase_count'},
    'purchase_count': {'receipt'},
    'expected_amount': {'receipt'},
    'expected_currency_only': {'receipt'},
    'receipt': {'adjustment','satisfaction'},
    'adjustment': {'satisfaction'},
    'expected_currency': {'currency_receipt'},
    'currency_receipt': {'satisfaction'},
    'refund_status': {'refund_date','refund_amount','refund_currency_only','refund_method'},
    'refund_date': {'refund_amount','refund_currency_only','refund_method'},
    'refund_amount': {'refund_method'},
    'refund_currency_only': {'refund_method'},
    'refund_method': {'refund_confirm'},
    'refund_confirm': {'refund_reference','satisfaction'},
    'refund_reference': {'satisfaction'},
    'satisfaction': {'done','handoff_confirm','policy_topic'},
    'handoff_confirm': {'handoff_pending','done'},
    'handoff_pending': {'done'},
    'confirm': {'satisfaction'},
    'policy_topic': {'satisfaction'},
    'done': {'satisfaction'},
}
CARD_STEPS = {'protect_card','protect_kind','protect_confirm','protect_unknown','protect_after','protect_failed'}
KNOWN_STEPS = set(EDGES) | CARD_STEPS


def check_state(state):
    if not isinstance(state,dict) or state.get('step') not in KNOWN_STEPS:
        raise ValueError('UNKNOWN_WORKFLOW_STEP')
    if not isinstance(state.get('answers'),dict) or not isinstance(state.get('messages'),list):
        raise ValueError('INVALID_WORKFLOW_STATE')


def check_transition(before, after, control=None):
    check_state(before); check_state(after)
    origin, target = before['step'], after['step']
    # Confirmed action services own preview/permission/idempotency checks. Card
    # resumption restores a saved ordinary step rather than a fixed next edge.
    if control in ('card_control','case_control'):
        return
    if target == origin or target in EDGES.get(origin,set()) or target == 'handoff_confirm':
        return
    raise ValueError('INVALID_WORKFLOW_TRANSITION')
