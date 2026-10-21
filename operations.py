"""Staff-scoped operational counts; no statement, ID, amount or raw payload output."""
import json
from access import require_staff
from concerns import connection, codec_for, audit

VERSION='DISPUTE-OPERATIONS-1.0'
COUNTERS=(
    'concerns','extraction_attempts','extraction_fallbacks','extraction_rejected_proposal_cases',
    'evidence_tool_failures','policy_failure_concerns','required_review_concerns',
    'queued_handoffs','unknown_case_commands','unknown_card_commands',
    'existing_case_links','card_noop_commands',
)


def summarise(states,case_commands=(),card_commands=(),audit_operations=(),card_actions=(),queued_handoffs=0):
    """Fixed output dimensions only; no attacker-controlled label/cardinality keys."""
    counts=dict.fromkeys(COUNTERS,0)
    counts['concerns']=len(states)
    for state in states:
        for trace in state.get('extraction_trace',[]):
            counts['extraction_attempts']+=int(trace.get('model') is not None)
            counts['extraction_fallbacks']+=int(trace.get('status')=='EXTRACTION_UNAVAILABLE_GUIDED_FALLBACK')
            counts['extraction_rejected_proposal_cases']+=int(bool(trace.get('rejected_fields')))
        counts['evidence_tool_failures']+=sum(t.get('result_status') in ('UNAVAILABLE','MALFORMED','FORBIDDEN_OR_NOT_FOUND') for t in state.get('agent_trace',[]))
        counts['policy_failure_concerns']+=int(any(code in {'POLICY_STALE','POLICY_UNAVAILABLE','POLICY_CONFLICT','POLICY_OUT_OF_SCOPE','POLICY_PRECONDITION_UNVERIFIED'} for code in state.get('review_reason_codes',[])))
        counts['required_review_concerns']+=int(state.get('review_requirement')=='REQUIRED')
    counts['queued_handoffs']=queued_handoffs
    counts['unknown_case_commands']=sum(r.get('status') in ('UNKNOWN','SUBMITTING') for r in case_commands)
    counts['unknown_card_commands']=sum(r.get('status') in ('UNKNOWN','SUBMITTING') for r in card_commands)
    counts['existing_case_links']=sum(op=='CASE_EXISTING_LINKED' for op in audit_operations)
    counts['card_noop_commands']=sum(r.get('changed')==0 for r in card_actions)
    return {'version':VERSION,'counts':counts,
            'scope':'AUTHORISED_CUSTOMER_SCOPE_ONLY',
            'interpretation':'Snapshot counters, not anonymous statistics or all-request telemetry. No customer identifiers or statements are exported.',
            'limits':['Pre-persistence failures and blocked secrets are not counted.',
                      'Existing-case links and no-op card commands are partial duplicate-prevention indicators; replay attempts are not counted.',
                      'Retention changes counts; no time-series, latency SLO or production monitoring is claimed.']}


def staff_summary(principal,customer_id='C-001',database=None):
    require_staff(principal,customer_id)
    with connection(database) as db:
        codec=codec_for(db)
        states=[json.loads(codec.open(r['state_json'])) for r in db.execute('SELECT state_json FROM concerns WHERE customer_id=?',(customer_id,))]
        cases=[dict(r) for r in db.execute('SELECT status FROM case_commands WHERE customer_id=?',(customer_id,))]
        cards=[dict(r) for r in db.execute('SELECT status FROM card_commands WHERE customer_id=?',(customer_id,))]
        actions=[dict(r) for r in db.execute('SELECT a.changed FROM card_actions a JOIN card_commands c USING(command_id) WHERE c.customer_id=?',(customer_id,))]
        ops=[r[0] for r in db.execute('SELECT p.operation FROM privacy_audit p JOIN concerns c USING(concern_id) WHERE c.customer_id=?',(customer_id,))]
        queued=db.execute('SELECT count(*) FROM handoff_requests WHERE customer_id=?',(customer_id,)).fetchone()[0]
        report=summarise(states,cases,cards,ops,actions,queued)
        audit(db,None,principal.actor_id,'OPERATIONAL_SUMMARY_READ')
        return report
