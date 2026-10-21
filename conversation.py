"""Deterministic question graph; customer text is evidence, never an instruction."""
from datetime import date
import sqlite3
from domain import list_cards, card_label, selected_transactions, search_transactions
from intake import advance as advance_intake, collect as collect_intake
from concern_extraction import extract as extract_concern
from privacy import protect
from review import update_review, offer_review
from policy_journey import OPEN as POLICY_OPTION, ANOTHER as ANOTHER_POLICY, handle as handle_policy

OPTIONS = ["I have an unrecognised transaction", "I am charged even after cancelling my subscription", "I have been charged multiple times", "I have been charged the wrong amount", "I haven’t received my refund", "I have a different issue"]
YES_NO = ["Yes", "No", "I’m not sure"]
QUESTIONS = {
    'policy_topic': ('What would you like to know? These policies are fictional evidence-collection guidance; they do not decide refund eligibility or legal deadlines.', []),
    "issue": ("Hi, how can I help you today?", OPTIONS),
    "card": ("Which card is this concern about? Please select one of your cards.", []),
    "elaborate": ("Can you please elaborate your concern?", []),
    "different_issue": ("Please tell me what happened and what you need help with. Don’t include card numbers, passwords or other sensitive information.", []),
    "search_confirm": ("Please confirm the search details.", ["Confirm and search", "Edit details"]),
    "search_details": ("Please provide the missing search detail.", ["I don’t know / need help"]),
    "other_transaction": ("Does your issue concern a specific card transaction?", ["Yes", "No", "I’m not sure"]),
    "transaction": ("Which payment is this about? Choose a transaction below. You can search by merchant, descriptor or reference.", []),
    "recognise": ("Do these merchant details help you recognise the payment?", YES_NO),
    "resolved": ("Does this resolve your concern?", YES_NO),
    "other_user": ("Could another authorised cardholder have made this payment?", YES_NO),
    "permission": ("Do you believe this payment was made without your permission?", YES_NO),
    "safety": ("Is your card missing, or have you noticed any other unfamiliar payments?", YES_NO),
    "cancel_type": ("What did you cancel?", ["A subscription or recurring payment", "An order or booking", "Something else / not sure"]),
    "cancel_date": ("When did you cancel? Enter DD-MM-YYYY, or choose ‘I don’t know’.", ["I don’t know"]),
    "cancel_method": ("How did you cancel?", ["Merchant website or app", "Email", "Telephone", "Through the bank", "Another method", "I don’t know"]),
    "cancel_confirm": ("Did you receive cancellation confirmation?", YES_NO),
    "cancel_reference": ("Please describe the confirmation or provide its cancellation reference. Do not include sensitive details. Documents cannot be verified in this demo.", ["I don’t have it available"]),
    "billing_type": ("Which best describes the problem?", ["I was charged more than once", "The amount is wrong", "The currency is unexpected"]),
    "duplicate": ("Which other payment looks like a duplicate?", []),
    "purchase_count": ("Were these payments for one purchase or separate purchases?", ["One purchase", "Separate purchases", "I’m not sure"]),
    "receipt": ("Do you have a receipt or order confirmation?", YES_NO),
    "expected_amount": ("What amount and currency did you agree to pay? For example: INR 40.00. Choose ‘I don’t know’ if unsure.", ["I don’t know"]),
    "adjustment": ("Did the purchase include a tip, deposit or later adjustment?", YES_NO),
    "expected_currency_only": ("What currency was the expected amount in? Please enter its code, for example INR.", []),
    "refund_currency_only": ("What currency is the expected refund in? Please enter its code, for example INR.", []),
    "expected_currency": ("Which currency did you agree to pay in?", ["I don’t know"]),
    "currency_receipt": ("What currency and amount appear on your receipt?", ["I don’t have a receipt"]),
    "refund_status": ("What has the merchant told you?", ["They agreed to issue a refund", "They confirmed the refund was processed", "I returned or cancelled but have no refund confirmation", "I’m not sure"]),
    "refund_date": ("When was the refund promised? Enter DD-MM-YYYY, or choose ‘I don’t know’.", ["I don’t know"]),
    "refund_amount": ("What refund amount and currency are you expecting?", ["I don’t know"]),
    "refund_method": ("Was it being refunded to this card or another payment method?", ["This card", "Another payment method", "I’m not sure"]),
    "refund_confirm": ("Do you have a refund confirmation or reference?", YES_NO),
    "refund_reference": ("Please provide the refund reference or describe the confirmation. This remains an unverified customer statement.", ["I don’t have it available"]),
    "satisfaction": ("Have I resolved your concern?", ["Yes, my concern is resolved", "No, I need more help", "I’m not sure"]),
    "handoff_confirm": ("May I send the discussion summary to the simulated human-assistance queue? No real representative is connected in this demo.", ["Yes, request human assistance", "Not now"]),
    "confirm": ("Would you like to record this conversation as a session-local demo intake? No bank case will be created and nobody will be notified.", ["Confirm demo intake", "Not now"]),
}


def transaction_label(t):
    return f"{t.reference} · {t.date:%d %b %Y} · {t.merchant} · {t.amount} · {t.status}"


def start():
    state = {"step": "issue", "answers": {}, "messages": [], "decision": None, "receipt": None}
    update_review(state)
    prompt(state)
    return state


def prompt(state):
    step = state["step"]
    if step == 'recognise':
        update_review(state)
        if state['review_requirement'] == 'REQUIRED':
            offer_review(state)
            step = state['step']
    if step in QUESTIONS:
        question = QUESTIONS[step][0]
        if step == "refund_date" and state["answers"].get("refund_status") == "They confirmed the refund was processed":
            question = "When did the merchant say the refund was processed? Enter DD-MM-YYYY, or choose ‘I don’t know’."
        if step == 'cancel_date':
            record = state.get('evidence', {}).get('cancellations', {})
            if record.get('status') == 'SUCCESS':
                requested = record['records'][0]['requested_date']
                question = f"The demo merchant record shows a cancellation request dated {requested}. When did you cancel? Enter DD-MM-YYYY or choose ‘I don’t know’; any difference will remain recorded."
        state["messages"].append(("assistant", question))


def choices(state):
    step = state["step"]
    from card_chat import active as card_active, choices as card_choices, OPEN as CARD_OPEN
    if card_active(state):return card_choices(state)
    if step == 'issue':
        return OPTIONS + [CARD_OPEN, POLICY_OPTION]
    if step == 'policy_topic':
        from policy_service import QUESTIONS as POLICY_QUESTIONS
        return list(POLICY_QUESTIONS)
    if step == 'satisfaction' and state.get('issue_kind') == 'policy_question':
        return QUESTIONS['satisfaction'][1] + [ANOTHER_POLICY]
    if step == "card":
        return [card_label(c) for c in list_cards()]
    if step == "transaction":
        try:
            candidates = search_transactions(state) if 'intake' in state else selected_transactions(state)
            state['search_status'] = 'SUCCESS'
        except sqlite3.Error:
            candidates = ()
            state['search_status'] = 'UNAVAILABLE'
        return [transaction_label(t) for t in candidates] + ["Change search details", "Request human assistance"]
    if step == "duplicate":
        return [transaction_label(t) for t in selected_transactions(state) if t.reference != state["answers"]["transaction"]] + ["I can’t find it"]
    return QUESTIONS.get(step, ("", []))[1]


def finish(state, reason, message, resolved=False):
    from policy_contract import intake,gate_reason,attribution,review_signal,REASON_RULE,envelope,INTAKE_SCOPE
    if reason in REASON_RULE and state.get('answers',{}).get('transaction'):
        context=gate_reason(reason,intake(),state)
    else:
        context=envelope('transaction_intake',INTAKE_SCOPE,'NOT_REQUIRED','CUSTOMER_ACKNOWLEDGEMENT_OR_OPERATIONAL_REFERRAL')
    blocked=context['status'] not in ('SUCCESS','NOT_REQUIRED')
    if blocked:
        state.setdefault('review_signals',[]).append(review_signal(context))
        if reason=='REPORTED_UNAUTHORISED':
            message='You reported that the payment was made without your permission. Contact the bank through an official channel for specialist review. The applicable intake policy could not be verified; no policy conclusion or fraud finding is available.'
        else:
            message='Your statements have been recorded, but the evidence or applicable intake policy is insufficient for a supported conclusion. I cannot give a policy-backed outcome. Human review is needed; no eligibility or refund decision has been made.'
    if context['allowed']:
        src=context['sources'][0]; clause=context['clauses'][0]
        message+=f"\n\nFictional intake routing source: {clause['source_uri']} (effective from {src['effective_from']}; applicable as of {context['as_of']})."
    state["decision"] = {"route": "EXPLAIN" if resolved and not blocked else "HUMAN_REVIEW",
                         'reason':context['reason_code'] if blocked and reason!='REPORTED_UNAUTHORISED' else reason,
                         'intended_reason':reason,
                         'explanation':message,'decision_type':'INTAKE_ROUTING' if context['allowed'] else 'OPERATIONAL_REFERRAL',
                         **attribution(context)}
    state["decision"]["evidence_ids"] = [e['evidence_id'] for key,e in state.get('evidence', {}).items() if key!='policy' and e['status'] == 'SUCCESS']
    if context['allowed']:
        state['decision']['evidence_ids'] += [s['content_sha256'] for s in context['sources']]
    state["messages"].append(("assistant", message))
    update_review(state)
    if state["review_requirement"] == "REQUIRED":
        offer_review(state)
    else:
        state["step"] = "satisfaction"
    prompt(state)


def next_refund_amount(state):
    if state['answers'].get('refund_amount'):
        return 'refund_method'
    if state.get('intake', {}).get('refund_amount'):
        return 'refund_currency_only'
    return 'refund_amount'


def submit(state, text, extractor=None):
    protected = protect(text)
    if protected.contains_secrets:
        state['messages'].append(('assistant', 'Please remove PINs, CVVs, OTPs, passwords or access tokens and resend your concern. They are not needed here.'))
        return
    text = protected.text.strip()
    if not text or state["step"] == "done":
        return
    update_review(state)
    if state["step"] in ("satisfaction", "recognise") and state["review_requirement"] == "REQUIRED":
        offer_review(state)
        prompt(state)
        return
    step, a = state["step"], state["answers"]
    state["messages"].append(("user", text))
    if handle_policy(state, text):
        return
    if step == 'search_details':
        collect_intake(state, text)
        return
    if step == 'search_confirm':
        if text == 'Edit details':
            state['search_confirmed'] = False
            state['intake'] = {}
            state['step'] = 'elaborate'
            prompt(state)
        elif text == 'Confirm and search':
            from intake import missing_field
            if missing_field(state):
                advance_intake(state)
                return
            state['search_confirmed'] = True
            state['search_confirmation'] = dict(state['intake'])
            state['search_card_id'] = a['card_id']
            state['step'] = 'transaction'
            prompt(state)
        else:
            state['messages'].append(('assistant', 'Please confirm the search details or choose Edit details.'))
        return
    if step == 'transaction' and text in ('Change search details', 'Request human assistance'):
        if text == 'Change search details':
            state['search_confirmed'] = False
            state['intake'] = {}
            state['step'] = 'elaborate'
        else:
            offer_review(state)
        prompt(state)
        return
    options = choices(state)
    if step == "transaction" and state.get("search_status") == "UNAVAILABLE":
        state["messages"].append(("assistant", "Transaction lookup is unavailable. No search result can be verified. Please try again or request human assistance."))
        return
    # Structured questions require explicit choices. Free text is preserved but not classified.
    if step == "card":
        card = next((c for c in list_cards() if text in (c['card_id'], card_label(c))), None)
        if card is None:
            state['messages'].append(('assistant', 'Please select one of your listed cards.'))
            return
        a['card_id'] = card['card_id']
    elif step in {"transaction", "duplicate"}:
        # Older saved conversations infer their card only from their already-selected transaction.
        match = next((t for t in (search_transactions(state) if step == "transaction" and "intake" in state else selected_transactions(state)) if text == t.reference or text == transaction_label(t)), None)
        if match and not (step == "duplicate" and match.reference == a["transaction"]):
            a[step] = match.reference
        elif step == "duplicate" and text == "I can’t find it":
            a[step] = text
        else:
            state["messages"].append(("assistant", "Please select a payment from the list or enter its exact TX reference. I won’t guess which transaction you mean."))
            return
    elif options and step not in {"cancel_date", "cancel_reference", "expected_amount", "expected_currency", "currency_receipt", "refund_date", "refund_amount", "refund_reference"}:
        if text not in options:
            a.setdefault("additional_statements", []).append(text)
            state["messages"].append(("assistant", "I’ve kept your description. Please choose one of the options so I can continue without guessing. If your card is at risk, use the urgent-help control."))
            return
        a[step] = text
    else:
        if step in {"cancel_date", "refund_date"} and text != "I don’t know":
            try:
                from intake import normalise
                text = normalise('cancellation_date' if step == 'cancel_date' else 'refund_date', text)
            except ValueError as exc:
                state["messages"].append(("assistant", str(exc)))
                return
        a[step] = text
    next_step = None
    if step == "issue":
        next_step = "card"
    elif step == "card":
        next_step = "elaborate"
    elif step == "elaborate":
        state['issue_kind'] = dict(zip(OPTIONS, ['unrecognised', 'cancellation', 'duplicate', 'wrong_amount', 'refund', 'other']))[a['issue']]
        if state['issue_kind'] == 'other':
            a['different_issue'] = text
            next_step = 'other_transaction'
        else:
            extract = extractor or (lambda message, kind: extract_concern(message, kind, use_ollama=False))
            fields, sources, trace = extract(text, state['issue_kind'])
            state['intake'] = fields
            state.setdefault('extraction_trace', []).append(trace)
            state.setdefault('intake_assertions', []).extend({'field': key, 'value': value, 'source_text': sources[key], 'source': trace.get('field_sources', {}).get(key, [trace['status']]), 'verified': False} for key, value in fields.items())
            advance_intake(state)
            return
    elif step == 'other_transaction':
        if text == 'Yes':
            state['intake'] = {}
            advance_intake(state)
            return
        finish(state, 'OUTSIDE_DEMO_SCOPE', 'Your issue is outside this prototype’s supported journeys. Your description has been recorded for human assistance; no transaction search was performed.')
        return
    elif step == "different_issue":
        finish(state, "OUTSIDE_DEMO_SCOPE", "I’ve recorded your issue. It falls outside the supported transaction-dispute journeys, so I cannot assess it here. You can request human assistance with the summary of what you’ve told me.")
        return
    elif step == "transaction":
        t = next(t for t in selected_transactions(state) if t.reference == a[step])
        state["messages"].append(("assistant", f"Demo bank record: {transaction_label(t)}. Statement descriptor: {t.descriptor}. Channel: {t.channel}. Merchant details do not prove authorisation."))
        issue_steps = dict(zip(OPTIONS[:5], ["recognise", "cancel_type", "duplicate", "expected_amount", "refund_status"]))
        if a['issue'] == OPTIONS[2]:
            a['billing_type'] = 'I was charged more than once'
        elif a['issue'] == OPTIONS[3]:
            a['billing_type'] = 'The amount is wrong'
        issue_steps.update(dict(zip(["I don’t recognise this payment", "I was charged after cancelling", "I was charged twice or the amount is wrong", "My refund hasn’t arrived"], ["recognise", "cancel_type", "billing_type", "refund_status"])))
        issue_steps['I have been charged multiple times/ wrong amount'] = 'billing_type'
        if a['issue'] == OPTIONS[5]:
            finish(state, 'OUTSIDE_DEMO_SCOPE', 'Your transaction and description have been recorded. This issue needs human assistance.')
            return
        next_step = issue_steps[a["issue"]]
        reported = state.get('intake', {})
        actual_amount = t.amount.split()[1]
        reported_amount = reported.get('original_amount' if state.get('issue_kind') == 'refund' else 'charged_amount')
        if reported_amount and reported_amount != actual_amount:
            state.setdefault('review_signals', []).append('MATERIAL_EVIDENCE_CONFLICT')
            state['messages'].append(('assistant', 'The selected transaction amount differs from your reported charged/purchase amount. This discrepancy needs review.'))
        if next_step == 'expected_amount' and reported.get('expected_amount') and not reported.get('expected_currency'):
            next_step = 'expected_currency_only'
        if next_step == 'expected_amount' and reported.get('expected_amount') and reported.get('expected_currency'):
            a['expected_amount'] = f"{reported['expected_currency']} {reported['expected_amount']}"
            next_step = 'receipt'
        if reported.get('cancellation_date'):
            a['cancel_date'] = reported['cancellation_date']
        if reported.get('refund_date'):
            a['refund_date'] = reported['refund_date']
        if reported.get('refund_amount') and reported.get('refund_currency'):
            a['refund_amount'] = f"{reported['refund_currency']} {reported['refund_amount']}"
    elif step == "recognise": next_step = "resolved" if text == "Yes" else "other_user"
    elif step == "resolved":
        if text == "Yes":
            finish(state, "CUSTOMER_RECOGNISED", "You confirmed that you recognise the payment and your concern is resolved. No action was taken.", True)
            return
        next_step = "other_user"
    elif step == "other_user": next_step = "permission"
    elif step == "permission":
        if text == "Yes":
            state["messages"].append(("assistant", "If your card may be at risk, contact your bank urgently using its official app or the number on your card. This demo cannot secure your card."))
            finish(state, "REPORTED_UNAUTHORISED", "You reported that this payment was made without your permission. Specialist review is needed; this does not establish fraud.")
            return
        next_step = "safety"
    elif step == "safety":
        urgent = text == "Yes" or a["permission"] == "Yes"
        if urgent:
            state["messages"].append(("assistant", "If your card may be at risk, contact your bank urgently using its official app or the number on your card. This demo cannot block cards or contact the bank."))
        finish(state, "REPORTED_UNAUTHORISED" if a["permission"] == "Yes" else "AUTHORISATION_UNCLEAR", "Your statements need a bank colleague’s review. Merchant history does not establish authorisation. Any uncertainty or conflicting answers will remain in the intake summary.")
        return
    elif step == "cancel_type": next_step = "cancel_method" if a.get("cancel_date") else "cancel_date"
    elif step == "cancel_date": next_step = "cancel_method"
    elif step == "cancel_method": next_step = "cancel_confirm"
    elif step == "cancel_confirm": next_step = "cancel_reference" if text == "Yes" else "finish_cancel"
    elif step == "cancel_reference": next_step = "finish_cancel"
    elif step == "billing_type": next_step = {"I was charged more than once": "duplicate", "The amount is wrong": "expected_amount", "The currency is unexpected": "expected_currency"}[text]
    elif step == "duplicate": next_step = "purchase_count"
    elif step == "purchase_count": next_step = "receipt"
    elif step == 'expected_currency_only':
        try:
            from intake import set_field
            set_field(state, 'expected_currency', text)
        except ValueError as exc:
            state['messages'].append(('assistant', str(exc)))
            return
        a['expected_amount'] = f"{state['intake']['expected_currency']} {state['intake']['expected_amount']}"
        next_step = 'receipt'
    elif step == "expected_amount": next_step = "receipt"
    elif step == "receipt": next_step = "adjustment" if a["billing_type"] == "The amount is wrong" else "finish_billing"
    elif step == "adjustment": next_step = "finish_billing"
    elif step == "expected_currency": next_step = "currency_receipt"
    elif step == "currency_receipt": next_step = "finish_billing"
    elif step == "refund_status": next_step = next_refund_amount(state) if a.get("refund_date") else "refund_date"
    elif step == "refund_date": next_step = next_refund_amount(state)
    elif step == 'refund_currency_only':
        try:
            from intake import set_field
            set_field(state, 'refund_currency', text)
        except ValueError as exc:
            state['messages'].append(('assistant', str(exc)))
            return
        a['refund_amount'] = f"{state['intake']['refund_currency']} {state['intake']['refund_amount']}"
        next_step = 'refund_method'
    elif step == "refund_amount": next_step = "refund_method"
    elif step == "refund_method": next_step = "refund_confirm"
    elif step == "refund_confirm": next_step = "refund_reference" if text == "Yes" else "finish_refund"
    elif step == "refund_reference": next_step = "finish_refund"
    elif step == "satisfaction":
        state["customer_resolution"] = {"Yes, my concern is resolved": "RESOLVED", "No, I need more help": "NOT_RESOLVED", "I’m not sure": "UNSURE"}[text]
        if text == "Yes, my concern is resolved":
            state["concern_status"] = "customer_resolved"
            state["messages"].append(("assistant", "You confirmed your concern is resolved. Your history remains saved. This does not change any policy decision or approve a refund."))
            state["step"] = "done"
            return
        state["concern_status"] = "needs_assistance"
        state["handoff_status"] = "AWAITING_CONFIRMATION"
        next_step = "handoff_confirm"
    elif step == "handoff_confirm":
        if text == "Yes, request human assistance":
            # Persistence layer must confirm queue success before any success message.
            state["step"] = "handoff_pending"
        else:
            state["handoff_status"] = "DECLINED"
            if state["review_requirement"] == "REQUIRED":
                state["concern_status"] = "review_required"
                state["messages"].append(("assistant", "Specialist review remains required. Please contact your bank through an official channel."))
            state["messages"].append(("assistant", "No human-assistance request was queued. Your notes remain saved; contact your bank if you need further help."))
            state["step"] = "done"
        return
    elif step == "confirm":
        if text == "Confirm demo intake":
            from uuid import uuid4
            state["receipt"] = "DEMO-" + uuid4().hex[:10].upper()
            state["messages"].append(("assistant", f"Session-local demo intake recorded: {state['receipt']}. No bank case was created and nobody was notified. Download the summary before ending your session."))
        else:
            state["messages"].append(("assistant", "No additional demo intake receipt was created. Your concern notes remain saved locally. You can start a new conversation whenever you’re ready."))
        state["step"] = "satisfaction"
        prompt(state)
        return
    if next_step and next_step.startswith("finish_"):
        t = next(t for t in selected_transactions(state) if t.reference == a["transaction"])
        if next_step == "finish_cancel":
            reason = "CANCELLATION_REVIEW"
            message = "Your cancellation details have been collected for review. Confirmation supplied in chat is not independently verified."
            if a["cancel_date"] == "I don’t know": message += " The cancellation date is still missing."
            elif date.fromisoformat(a["cancel_date"]) >= t.date: message += " Cancellation was on or after the transaction date; the timing needs review."
            if not t.recurring: message += " The demo record does not mark this as recurring."
        elif next_step == "finish_billing":
            reason, message = "BILLING_REVIEW", "Your billing concern needs review. Matching amounts alone do not prove duplication, and currency differences alone do not prove an error."
        else:
            reason, message = "REFUND_EVIDENCE_UNAVAILABLE", "I cannot verify whether a refund has arrived: this prototype has no refund lookup service. The bank needs to check related credits and the applicable refund policy. I cannot conclude that the refund is overdue."
        if next_step == "finish_refund" and state.get('evidence', {}).get('refunds', {}).get('status') in ('SUCCESS', 'NOT_FOUND') and state.get('evidence', {}).get('credits', {}).get('status') in ('SUCCESS', 'NOT_FOUND'):
            refunds = state['evidence']['refunds']['records']
            credits = state['evidence']['credits']['records']
            reason = "REFUND_RECORDS_REVIEW"
            if credits:
                message = f"The demo bank records contain {len(credits)} related posted credit(s). Please review their amounts in the evidence panel. This does not by itself establish that your expected refund is fully resolved."
            elif refunds:
                message = "A refund record was found, but no related posted credit was found. Applicable timing and any missing links need review; I cannot conclude it is overdue."
            else:
                message = "No linked refund or credit record was found in the demo database. This does not prove a refund was never issued. Please obtain merchant confirmation for review."
        if t.status == "Pending": message += " The selected payment is pending, so its final status also needs checking."
        finish(state, reason, message + " No eligibility or refund decision has been made.")
        return
    state["step"] = next_step
    prompt(state)
