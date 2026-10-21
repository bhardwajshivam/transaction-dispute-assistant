"""Run: python -m streamlit run app.py"""
import json
import os
import sqlite3
from time import time
from concerns import list_concerns, get_concern, record_export
from review import update_review, offer_review
from privacy import sanitise, customer_export
from case_chat import options as case_options
import streamlit as st
try:
    from conversation import start, choices, prompt
except FileNotFoundError:
    st.error("Prepare data first: python3 scripts/generate_data.py then python3 scripts/load_database.py")
    st.stop()

st.set_page_config(page_title="Transaction support", page_icon="💬", layout="centered")
if time() - st.session_state.get('_last_activity', time()) > 900:
    st.session_state.clear()
    st.info('Your local session expired. Please reopen your saved concern if needed.')
st.session_state['_last_activity'] = time()
workspace = st.sidebar.radio("Workspace", ["Customer chat", "Representative workspace"])
if workspace == "Representative workspace":
    from representative_ui import render
    render()
    st.stop()
title_column, download_column = st.columns([3, 1.6], vertical_alignment="center")
with title_column:
    st.title("Transaction support")
with download_column:
    history_download = None
    concern_id = st.session_state.get('concern_id')
    if concern_id:
        try:
            saved, saved_events = get_concern(concern_id)
            saved_state = json.loads(saved['state_json'])
            history_download = json.dumps(customer_export(saved_state, concern_id, saved_events), indent=2, ensure_ascii=False)
        except (sqlite3.Error, PermissionError, FileNotFoundError, ValueError):
            st.caption("Saved history is temporarily unavailable.")
    st.download_button(
        "Download history", data=history_download or "", icon=":material/download:",
        file_name=f"{concern_id or 'concern'}-history.json", mime="application/json",
        disabled=history_download is None, on_click=record_export, kwargs={"concern_id": concern_id}, use_container_width=True,
        help="Download the saved conversation and concern summary. Available after your first reply is saved.",
    )
st.caption("Tell us what happened. We’ll work through it one question at a time.")
if os.environ.get('EVIDENCE_PROPOSER_MODE', 'deterministic') == 'ollama':
    st.info("Local Ollama evidence mode is configured. After access verification, selected synthetic transaction references and evidence-status metadata are sent to Ollama on this computer. The complaint description is processed locally by smollm2:135m for field extraction; raw bank records are excluded. Failures fall back to deterministic mode.")
if "conversation" not in st.session_state:
    st.session_state.conversation = start()
state = sanitise(st.session_state.conversation)
st.session_state.conversation = state
update_review(state)
if state['review_requirement'] == 'REQUIRED' and state.get('step') == 'recognise':
    offer_review(state)
    prompt(state)


def record_reply(text, rerun=True):
    if time() - st.session_state.get('_last_activity', time()) > 900:
        st.session_state.clear()
        st.error('Session expired. Please start again; this reply was not saved.')
        return
    from workflow import process, WorkflowError
    try:
        with st.spinner("Updating your concern…"):
            result = process(state, text, st.session_state.get('concern_id'), st.session_state.get('concern_revision', 0))
    except WorkflowError as error:
        if error.code == 'SECRET_BLOCKED':
            st.error('Please remove OTPs, PINs, CVVs, passwords or access tokens and resend. This reply has not been saved or sent to the model.')
        elif error.stage == 'card':
            st.error(f"Card protection was not confirmed ({error.code}). Reopen this concern to check the saved request before retrying. For real protection, use the bank’s official controls or urgent support.")
        elif error.stage == 'case':
            st.error(f"Case submission was not confirmed ({error.code}). Reopen the concern to check status. A new case has not been assumed.")
        else:
            st.error('Your chat update was not saved. Reopen the concern before retrying. A confirmed case may have completed independently; check its status first.')
        return
    if result.redactions:
        st.info('Unnecessary personal identifiers were redacted before processing and saving your message.')
    st.session_state.conversation = result.state
    st.session_state.concern_id = result.concern_id
    st.session_state.concern_revision = result.revision
    if rerun:
        st.rerun()

with st.sidebar:
    st.header("Conversations")
    if st.button("Start a new conversation"):
        st.session_state.conversation = start()
        st.session_state.pop("concern_id", None)
        st.session_state.pop("concern_revision", None)
        st.rerun()
    if st.button("End session"):
        st.session_state.clear()
        st.rerun()
    try:
        previous = list_concerns()
    except (sqlite3.Error, FileNotFoundError, ValueError):
        previous = []
        st.error("Concern history is unavailable.")
    if previous:
        selected_concern = st.selectbox("Previous concerns", [r["concern_id"] for r in previous],
            format_func=lambda cid: next(f"{cid} · {r['updated_at'][:19]} UTC" for r in previous if r['concern_id'] == cid))
        if st.button("Open selected concern"):
            try:
                from workflow import reopen
                restored = reopen(selected_concern)
                st.session_state.conversation = restored.state
                st.session_state.concern_id = restored.concern_id
                st.session_state.concern_revision = restored.revision
                st.rerun()
            except (sqlite3.Error, PermissionError, ValueError):
                st.error("Could not open this concern.")

if state['review_requirement'] == 'REQUIRED':
    st.warning("Specialist review required · " + ", ".join(state['review_reason_codes']))
    st.caption("Customer satisfaction or declining a handoff cannot clear this requirement.")
if state.get('unusual_activity'):
    assessment = state['unusual_activity']
    with st.expander('Transaction activity checks'):
        st.caption('Rules examine earlier activity on the selected card. Patterns do not prove fraud; no signal does not establish safety.')
        st.write('Assessment:', assessment['status'])
        for signal in assessment.get('signals', []):
            messages = {
                'AMOUNT_ABOVE_HISTORICAL_BASELINE': 'This amount is above the configured historical-spending threshold.',
                'REPEATED_CHARGE_SAME_ORDER': 'An earlier payment has the same merchant, amount, currency and order reference. Review is recommended.',
                'REPEATED_CHARGE_ORDER_UNKNOWN': 'An earlier payment matches the merchant, amount and currency, but order references are incomplete. Review is recommended.',
                'MATCHING_CHARGES_DISTINCT_ORDERS': 'Matching payment amounts have different order references. This alone does not trigger specialist review.',
            }
            st.write(messages.get(signal['reason_code'], 'A historical pattern was recorded.'))
        if assessment['status'] != 'ASSESSED':
            st.write('Some checks could not be completed. Missing or unavailable history is not a clean result.')
        st.caption('Same-day payments, device signals and location checks are excluded from this first version.')

if state.get('clustering'):
    cluster = state['clustering']
    with st.expander('Spending-pattern clustering'):
        st.caption('Cluster distance measures unusualness, not the probability of fraud. A low score does not establish safety.')
        st.write('Assessment:', cluster['status'])
        if cluster['status'] == 'ASSESSED':
            st.metric('Cluster-distance score', f"{cluster['anomaly_score']:.3f}")
            st.write('Above the configured distance threshold:', 'Yes' if cluster['flagged'] else 'No')
            st.caption(f"Fitted on {cluster['training_count']} earlier payments; threshold set using {cluster['calibration_count']} later historical payments. Values above 1 flag unusualness.")
            if cluster['mode'] == 'shadow':
                st.write('Observation mode: this score does not change your dispute route.')
        else:
            st.write('A reliable clustering score could not be produced:', cluster.get('reason_code'))

def render_replies():
    options = choices(state)
    from card_chat import active as card_active, OPEN as CARD_OPEN
    extra = [] if card_active(state) else case_options(state)
    if not card_active(state) and (state.get('case_command') or {}).get('status') == 'PREPARED':
        options = extra
    else:
        options = extra + options
    if not card_active(state) and CARD_OPEN not in options:
        options.append(CARD_OPEN)
    if state["step"] in {"transaction", "duplicate"}:
        search = st.text_input("Filter transactions", key=f"search_{state['step']}_{len(state['messages'])}", placeholder="Merchant, descriptor or TX reference")
        from domain import selected_transactions, search_transactions
        try:
            candidates = search_transactions(state) if state["step"] == "transaction" and "intake" in state else selected_transactions(state)
        except sqlite3.Error:
            candidates = ()
            state['search_status'] = 'UNAVAILABLE'
        allowed = {t.reference for t in candidates if search.strip().casefold() in f"{t.reference} {t.merchant} {t.descriptor}".casefold()}
        options = [o for o in options if o.split(" · ")[0] in allowed or o in ("I can’t find it", "Change search details", "Request human assistance", CARD_OPEN)]
        if state.get('search_status') == 'UNAVAILABLE':
            st.warning("Transaction lookup is unavailable. This is not evidence that no payment exists. Please retry later or request human assistance.")
        elif not candidates:
            st.info("No transactions match the confirmed details on this card. You can change the details or request human assistance; filters have not been broadened.")
    for index, option in enumerate(options):
        st.button(option, key=f"choice_{state['step']}_{len(state['messages'])}_{index}", use_container_width=True, on_click=record_reply, args=(option, False))


last_assistant = next((i for i in range(len(state['messages']) - 1, -1, -1) if state['messages'][i][0] == 'assistant'), None)
# Keep the active reply container stable while history grows above it.
with st.container():
    for index, (role, message) in enumerate(state["messages"]):
        if index != last_assistant:
            with st.chat_message(role):
                st.write(message)
if last_assistant is not None:
    with st.chat_message("assistant"):
        st.write(state['messages'][last_assistant][1])
        render_replies()

if os.environ.get('SHOW_INTERNAL_DEBUG', '0') == '1' and state.get('extraction_trace'):
    with st.expander("Reported details and extraction checks"):
        st.caption("Local model suggestions are customer assertions. Search requires your explicit confirmation; extraction cannot establish bank facts.")
        st.json(state.get('intake', {}))
        st.json(state['extraction_trace'])

if os.environ.get('SHOW_INTERNAL_DEBUG', '0') == '1' and state.get('agent_trace'):
    with st.expander("Evidence gathered and controller trace"):
        st.caption("Read-only tools; fixed tool allowlist, access checks and an eight-proposal budget. Tool records are synthetic bank evidence, not proof of customer authorisation.")
        st.json(state.get('evidence', {}))
        st.json(state['agent_trace'])
        st.json(state.get('evidence_runtime', {}))
        if state.get('proposer_trace'):
            st.json(state['proposer_trace'])
        st.caption(f"Controller stop: {state.get('agent_stop_reason')}")

if os.environ.get("SHOW_INTERNAL_DEBUG", "0") == "1" and state["decision"]:
    with st.expander("Decision and evidence record"):
        st.json(state["decision"])
        st.caption("All chat answers are customer assertions. Read-only tool records are demo bank facts. No document verification or authoritative eligibility policy is connected.")
        st.json(state["answers"])
if text := st.chat_input("Describe your concern, answer, or add a follow-up update…", max_chars=2000, disabled=state["step"] in ("issue", "card", "protect_card")):
    record_reply(text)
