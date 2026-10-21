"""Read-only local demonstration of a representative's handoff workspace."""
import json
import sqlite3
import streamlit as st
from concerns import list_handoffs, staff_concern, summary, record_export
from access import authenticate_staff, require_staff
from time import time
from privacy import sanitise


def render():
    st.title('Representative workspace')
    st.caption('Local staff demo · Token sign-in and customer scope checks · Production requires bank SSO/MFA.')
    principal = st.session_state.get('staff_principal')
    try:
        require_staff(principal, 'C-001')
    except PermissionError:
        st.session_state.pop('staff_principal', None)
        def login():
            token = st.session_state.pop('staff_token_input', '')
            if time() < st.session_state.get('staff_retry_after', 0):
                st.session_state['staff_login_error'] = 'Please wait before retrying.'
                return
            try:
                st.session_state.staff_principal = authenticate_staff(token)
                st.session_state.pop('staff_login_error', None)
                st.session_state['staff_failures'] = 0
            except PermissionError:
                failures = st.session_state.get('staff_failures', 0) + 1
                st.session_state['staff_failures'] = failures
                if failures >= 5:
                    st.session_state['staff_retry_after'] = time() + 60
                st.session_state['staff_login_error'] = 'Sign-in unavailable or credentials invalid. Contact the demo administrator.'
        with st.form('staff_sign_in'):
            st.text_input('Staff access token', type='password', key='staff_token_input', max_chars=512)
            st.form_submit_button('Sign in', on_click=login)
        if st.session_state.get('staff_login_error'):
            st.error(st.session_state.staff_login_error)
        return
    if st.button('Sign out'):
        st.session_state.pop('staff_principal', None)
        st.rerun()
    if st.button('Refresh queue'):
        st.rerun()
    from operations import staff_summary
    try:
        with st.expander('Operational counts — authorised customer scope'):
            st.json(staff_summary(principal))
    except (sqlite3.Error, FileNotFoundError, PermissionError, ValueError):
        st.error('Operational counts are unavailable.')
    from case_service import staff_cases
    try:
        cases, pending = staff_cases(principal)
        with st.expander('Simulated dispute cases', expanded=bool(cases or pending)):
            st.caption('Recorded for review only. No refund, chargeback or real bank submission is authorised here.')
            if not cases:
                st.write('No simulated dispute cases recorded.')
            for case in cases:
                st.write(f"{case['case_id']} · {case['transaction_id']} · {case['status']}")
                st.write('Linked concerns:', case['concern_ids'])
                st.json(case['record'])
            if pending:
                st.warning('Unconfirmed submission outcomes require reconciliation; do not create replacement requests.')
                st.json(pending)
    except (sqlite3.Error, FileNotFoundError, PermissionError, ValueError):
        st.error('The simulated case register is unavailable.')
    try:
        requests = list_handoffs(principal=principal)
    except (sqlite3.Error, FileNotFoundError, PermissionError, ValueError):
        st.error('The assistance queue is unavailable. Please try again.')
        return
    if not requests:
        st.info('No confirmed assistance requests have been queued yet.')
        return
    request_id = st.selectbox('Assistance request', [r['request_id'] for r in requests],
        format_func=lambda rid: next(f"{r['request_id']} · {r['concern_id']} · {r['created_at'][:19]} UTC" for r in requests if r['request_id'] == rid))
    request = next(r for r in requests if r['request_id'] == request_id)
    try:
        saved, events = staff_concern(request['concern_id'], principal)
        current = json.loads(saved['state_json'])
        package = sanitise(json.loads(request['summary_json']))
        report = summary(request['concern_id'])
    except (sqlite3.Error, PermissionError, ValueError):
        st.error('The selected concern cannot be loaded.')
        return
    st.caption(f"{request['status']} · Requested {request['created_at']} · Concern last updated {saved['updated_at']} (UTC)")
    st.download_button('Download handoff package', json.dumps(package, ensure_ascii=False, indent=2),
                       f'{request_id}-handoff.json', 'application/json', on_click=record_export, kwargs={'concern_id': request['concern_id'], 'principal': principal})
    st.download_button('Download latest concern history', report, f"{request['concern_id']}-history.txt", 'text/plain', on_click=record_export, kwargs={'concern_id': request['concern_id'], 'principal': principal})
    summary_tab, conversation_tab, updates_tab = st.tabs(['Handoff summary', 'Conversation', 'Later updates'])
    with summary_tab:
        st.subheader('Reason for assistance')
        st.write(package.get('reason_for_handoff', 'Customer requested assistance'))
        st.write('Required review:', current.get('review_requirement', 'Not recorded'))
        st.write('Review reasons:', current.get('review_reason_codes', []))
        st.write('Missing information / outstanding work:', package.get('missing_information', []))
        if package.get('continuation'):
            st.subheader('Suggested continuation — requires representative judgement')
            for task in package['continuation']['tasks']:
                st.write(task['instruction'])
                if task['references']:
                    st.write('References:', task['references'])
        st.write('Case actions attempted and recorded outcomes:')
        st.json(package.get('actions_attempted', []))
        st.subheader('Customer account of the issue — unverified')
        answers = package.get('answers', {})
        st.write(answers.get('elaborate') or answers.get('different_issue') or 'No initial description recorded.')
        st.json(answers)
        st.subheader('Demo bank facts at handoff')
        st.json(package.get('demo_bank_facts'))
        st.subheader('Routing and policy recorded at handoff')
        st.json(package.get('decision'))
        st.caption('Policy attribution and conclusion gate at handoff')
        st.json(package.get('policy_context'))
        st.subheader('General policy questions and retrieved source clauses')
        st.json(package.get('policy_qa_history', []))
        st.subheader('Unusual activity signals — not fraud findings')
        st.json(package.get('unusual_activity'))
        st.json(package.get('activity_review'))
        st.subheader('Cluster-distance assessment — not fraud probability')
        st.json(package.get('clustering'))
        st.json(package.get('clustering_review'))
        st.subheader('Outstanding step and limitations')
        st.write('Current workflow step:', current['step'])
        st.write(package.get('limitations', 'Evidence and policy are synthetic.'))
        with st.expander('Evidence, search confirmation and execution traces'):
            for key in ('evidence', 'intake_assertions', 'search_confirmation', 'controller_trace', 'proposer_trace', 'extraction_trace'):
                st.write(key.replace('_', ' ').title())
                st.json(package.get(key))
    with conversation_tab:
        st.caption('Conversation snapshot when assistance was requested. Later customer notes appear in Later updates.')
        for role, text in package.get('conversation', []):
            with st.chat_message(role):
                st.write(text)
    with updates_tab:
        later = [e for e in events if e['recorded_at'] > request['created_at']]
        if not later:
            st.info('No later updates recorded.')
        for event in later:
            st.caption(f"{event['recorded_at']} · {event['question_key']}")
            st.write(event['customer_statement'])
        st.caption('The original handoff package is preserved. Latest notes do not silently overwrite it.')
