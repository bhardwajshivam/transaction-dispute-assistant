"""Deterministic review requirements, independent of customer satisfaction."""
REASONS = {
    'CARD_PROTECTION_SUPPORT_REQUIRED': 'Card protection requires official bank or specialist assistance; no real protection is provided by this simulator.',
    'AUTHORISATION_UNCLEAR': 'Authorisation remains uncertain and requires specialist review.',
    'POLICY_STALE': 'The policy or its attribution has changed; the earlier conclusion needs revalidation.',
    'POLICY_PRECONDITION_UNVERIFIED': 'The facts required by the retrieved policy have not been established.',
    'POLICY_OUT_OF_SCOPE': 'The requested policy conclusion is outside the available material and needs human assistance.',
    'CLUSTER_ACTIVITY_REVIEW': 'A cluster-distance pattern needs specialist review; this is not a fraud probability.',
    'UNUSUAL_ACTIVITY_REVIEW': 'A transaction-history pattern needs specialist review; this does not establish fraud.',
    'EVIDENCE_VERIFICATION_UNAVAILABLE': 'A required evidence lookup could not be verified.',
    'REPORTED_UNAUTHORISED': 'You reported a payment made without your permission.',
    'ONGOING_CARD_RISK': 'You reported a missing card or other unfamiliar payments.',
    'MATERIAL_EVIDENCE_CONFLICT': 'Material evidence conflicts and needs specialist review.',
    'POLICY_UNAVAILABLE': 'Applicable authoritative policy is unavailable.',
    'POLICY_CONFLICT': 'Applicable policy versions conflict.',
    'ACTION_OUTCOME_UNKNOWN': 'The outcome of a consequential action is unknown.',
    'REFUND_VERIFICATION_UNAVAILABLE': 'The refund cannot be verified with the available tools.',
}


def update_review(state, previous=None):
    """Requirements are sticky; only a future authorised specialist may clear them.

    review_signals are internal adapter flags, never parsed from customer prose.
    """
    a = state.get('answers', {})
    reasons = set(state.get('review_reason_codes', []))
    if previous:
        reasons.update(previous.get('review_reason_codes', []))
    if a.get('permission') == 'Yes': reasons.add('REPORTED_UNAUTHORISED')
    if a.get('safety') == 'Yes' or state.get('reported_card_risk'): reasons.add('ONGOING_CARD_RISK')
    for signal in state.get('review_signals', []):
        if signal in REASONS: reasons.add(signal)
    if (state.get('decision') or {}).get('reason') == 'REFUND_EVIDENCE_UNAVAILABLE':
        reasons.add('REFUND_VERIFICATION_UNAVAILABLE')
    if (state.get('decision') or {}).get('reason') == 'AUTHORISATION_UNCLEAR':
        reasons.add('AUTHORISATION_UNCLEAR')
    state['review_reason_codes'] = sorted(reasons)
    state['review_requirement'] = 'REQUIRED' if reasons else 'NOT_REQUIRED'
    state.setdefault('customer_resolution', 'NOT_ASKED')
    state.setdefault('handoff_status', 'NOT_REQUESTED')
    if reasons and state.get('concern_status') == 'customer_resolved':
        state['concern_status'] = 'review_required'
    return state


def offer_review(state):
    update_review(state)
    if state.get('step') not in ('handoff_confirm','handoff_pending','done','satisfaction'):
        state.setdefault('review_interrupted_step',state.get('step'))
    # Evidence checks can require review immediately after transaction selection,
    # before the newly appended recognition question is rendered to the customer.
    # Remove only that unanswered trailing prompt, never earlier conversation.
    if state.get('step') == 'recognise' and state.get('messages') and state['messages'][-1][0] == 'assistant':
        if state['messages'][-1][1] == 'Do these merchant details help you recognise the payment?':
            state['messages'].pop()
    state['handoff_status'] = 'AWAITING_CONFIRMATION'
    state['step'] = 'handoff_confirm'
    if state['review_requirement'] == 'REQUIRED':
        explanation = ' '.join(REASONS.get(r, r) for r in state['review_reason_codes'])
        state['messages'].append(('assistant', 'Specialist review is required: ' + explanation + ' Declining assistance will not clear this requirement.'))
