"""Customer controls for the deterministic case service; no model calls."""
from case_service import prepare, execute, reconcile, cancel, demo_customer, CONFIRM, CaseDenied

OPEN = 'Open a dispute case'
CHECK = 'Check case submission status'
RETRY = 'Retry the same case submission'
DECLINE = 'Do not create a case now'


def restore(state, command):
    state['case_command'] = command
    if command['status'] in ('SUBMITTING', 'UNKNOWN'):
        from review import update_review, offer_review
        if 'ACTION_OUTCOME_UNKNOWN' not in state.setdefault('review_signals', []):
            state['review_signals'].append('ACTION_OUTCOME_UNKNOWN')
        update_review(state)
        if not state.get('handoff') and state.get('step') != 'handoff_confirm':
            offer_review(state)


def options(state):
    command = state.get('case_command') or {}
    if command.get('status') == 'PREPARED':
        return [CONFIRM, DECLINE] if (state.get('decision') or {}).get('policy_conclusion') is True else [DECLINE]
    if command.get('status') in ('SUBMITTING', 'UNKNOWN'):
        return [CHECK, RETRY] if (state.get('decision') or {}).get('policy_conclusion') is True else [CHECK]
    if command.get('status') == 'SUCCEEDED':
        return []
    if (state.get('decision') or {}).get('route') == 'HUMAN_REVIEW' and (state.get('decision') or {}).get('policy_conclusion') is True and state.get('answers', {}).get('transaction') and state.get('step') in ('satisfaction','handoff_confirm','done'):
        return [OPEN]
    return []


def handle(state, text, concern_id, database=None):
    if text not in (OPEN, CONFIRM, CHECK, RETRY, DECLINE):
        return False
    if text not in options(state):
        raise CaseDenied('CASE_CONTROL_NOT_AVAILABLE')
    principal = demo_customer()
    state['messages'].append(('user', text))
    current = state.get('case_command') or {}
    if text == OPEN:
        result = prepare(concern_id, principal, database)
    elif text in (CONFIRM, RETRY):
        result = execute(current['command_id'], principal, CONFIRM, database)
    elif text == CHECK:
        result = reconcile(current['command_id'], principal, database)
    else:
        cancel(current['command_id'], principal, database)
        state.pop('case_command', None)
        state['messages'].append(('assistant', 'No case was submitted. You can continue the conversation or request human assistance.'))
        return True
    restore(state, result)
    if result['status'] == 'PREPARED':
        tx = result['transaction']
        message = (f"Please confirm: record a simulated dispute case for {tx['transaction_id']} on {tx['card_id']}, "
                   f"{tx['merchant']}, {tx['purchase_date']}, {tx['currency']} {tx['amount_minor']/100:.2f}. "
                   f"Reported issue: {result['issue_kind']}. Your statement: {result['reported_concern']} "
                   f"The case will include your saved statements and evidence. Policy: {result['policy']['policy_id']} "
                   f"v{result['policy']['version']}. Confirmation expires in 10 minutes. " + result['policy']['notice'])
    elif result['status'] == 'SUCCEEDED':
        message = (f"Your simulated dispute case is recorded: {result['case_id']}. If a case already existed for this payment, "
                   "this concern has been linked to it. No real bank submission, refund or card action has occurred. "
                   "Any required specialist review still applies. You can continue with the questions below.")
    else:
        message = ('The case submission outcome is not confirmed. Check its status or retry the same request; '
                   'do not start a second submission. Human assistance remains available below.')
    state['messages'].append(('assistant', message))
    return True
