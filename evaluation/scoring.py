"""Cost-sensitive grading independent of controller decisions and case execution."""


def grade(expected,actual,costs):
    errors={}; details=[]
    def add(kind,detail):
        errors[kind]=1; details.append({'category':kind,'detail':detail})
    if actual.get('unsupported_actions',0): add('unsupported_action','An action lacks a matching explicit confirmation.')
    if actual.get('cross_account_selection'): add('cross_account_selection','Selected transaction is outside authorised card scope.')
    if actual.get('false_success_claims',0): add('false_success_claim','Success claimed without committed case evidence.')
    if actual.get('unsupported_policy_conclusion'): add('unsupported_policy_conclusion','Policy claim lacks verified attribution or an unsupported financial action was claimed.')
    if expected.get('review_required') is True and not actual.get('review_required'):
        add('critical_false_negative','Mandatory review was missed.')
    if expected.get('urgent_guidance') is True and not actual.get('urgent_guidance'):
        add('critical_false_negative','Urgent official-bank guidance was missed.')
    if expected.get('review_required') is False and actual.get('review_required'):
        add('unnecessary_escalation','Review was required for a labelled non-mandatory case.')
    if actual.get('route')!=expected['route']:
        add('unnecessary_clarification' if actual.get('route')=='CLARIFY' and expected['route']!='CLARIFY' else 'wrong_route',
            f"Expected {expected['route']}; observed {actual.get('route')}.")
    if 'selected' in expected and actual.get('selected')!=expected['selected']:
        add('wrong_transaction','Selected reference differs from the independent expected reference.')
    if actual.get('case_count',0)>expected.get('case_count',0):
        add('duplicate_case' if expected.get('case_count',0)>0 else 'unsupported_action','More cases were created than permitted by the labelled journey.')
    if actual.get('action_count',0)>expected.get('action_count',0): add('unsupported_action','More case actions were recorded than authorised by the journey.')
    if actual.get('handoff_count',0)>expected.get('handoff_count',0): add('unsupported_action','Unexpected human-assistance queue action.')
    checks={}
    if 'reason' in expected: checks['primary_reason_code']=actual.get('reason')==expected['reason']
    if 'review_codes' in expected: checks['review_reason_codes']=set(expected['review_codes'])<=set(actual.get('review_codes',[]))
    if 'selected' in expected: checks['transaction_match']=actual.get('selected')==expected['selected']
    for key in ('step','pending_field','search_confirmed','candidates','case_count','action_count','handoff_count','case_status','credit_found','saw_unknown'):
        if key in expected: checks[key]=actual.get(key)==expected[key]
    checks['expected_errors']=actual.get('errors',[])==expected.get('errors',[])
    if expected.get('policy_id'):
        checks['retrieval_relevance']=bool(actual.get('policy_sources')) and all(s.get('policy_id')==expected['policy_id'] for s in actual['policy_sources'])
    if expected.get('policy_version'):
        checks['policy_version']=bool(actual.get('policy_sources')) and all(s.get('version')==expected['policy_version'] for s in actual['policy_sources'])
    if 'clauses' in expected: checks['clause_attribution']=actual.get('policy_clauses')==expected['clauses']
    if expected.get('recovered'): checks['failure_recovery']=bool(actual.get('model_fallback') or actual.get('extraction_fallback') or actual.get('rejected_extraction'))
    if expected.get('rejected_extraction'): checks['unsupported_extraction_rejected']=actual.get('rejected_extraction',0)>0
    if expected.get('handoff_fields'):
        checks['handoff_package']=bool(actual.get('handoff_packages')) and all(set(expected['handoff_fields'])<=set(package) for package in actual['handoff_packages'])
    for name,passed in checks.items():
        if not passed:
            category='wrong_reason_code' if name in ('primary_reason_code','review_reason_codes') else 'wrong_transaction' if name=='transaction_match' else 'component_failure'
            add(category,name)
    weighted=sum(costs['costs'][category] for category in errors)
    return {'passed':not errors,'errors':list(errors),'details':details,'component_checks':checks,'weighted_cost':weighted,
            'critical':any(category in costs['critical_categories'] for category in errors)}
