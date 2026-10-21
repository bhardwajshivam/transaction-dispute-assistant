"""Deterministic colleague task list; never grants authority or invents facts."""
VERSION = 'DISPUTE-HANDOFF-1.1'


def continuation(package):
    tasks=[]
    unknown=[a['command_id'] for a in package.get('actions_attempted',[]) if a.get('status') in ('UNKNOWN','SUBMITTING')]
    if unknown:
        tasks.append({'code':'RECONCILE_EXISTING_ACTION','references':unknown,
                      'instruction':'Check these existing command outcomes with the authoritative service before any retry. Do not create a replacement request.'})
    tasks.append({'code':'REVIEW_LATER_UPDATES','references':[],
                  'instruction':'Check later concern updates before proceeding; this package is an immutable snapshot.'})
    if package.get('missing_information'):
        tasks.append({'code':'RESOLVE_RECORDED_GAPS','references':package['missing_information'],
                      'instruction':'Verify the recorded evidence gaps or ask the customer for the missing information. NOT_FOUND is not proof that an event never occurred.'})
    tasks.append({'code':'COMPARE_ASSERTIONS_WITH_FACTS','references':package.get('review_reason_codes',[]),
                  'instruction':'Compare customer assertions with verified bank evidence, preserving contradictions and the reason for escalation. Activity scores do not establish fraud.'})
    tasks.append({'code':'REVALIDATE_POLICY_AND_AUTHORITY','references':[],
                  'instruction':'Verify current applicable policy and your permissions before giving a conclusion or taking an action. This task list authorises no action.'})
    return {'version':VERSION,'owner':'Authorised human representative','interrupted_step':package.get('outstanding_step_at_escalation'),
            'tasks':tasks,'authority':'ADVISORY_CONTINUATION_ONLY','callback_status':'NOT_SCHEDULED_SIMULATION'}
