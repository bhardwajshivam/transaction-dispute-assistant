"""One-command end-to-end evaluation against isolated synthetic bank databases."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import platform
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.scenarios import scenarios
from evaluation.runner import execute_case
from evaluation.scoring import grade
from scripts.generate_data import write_json

ROOT=Path(__file__).resolve().parents[1]


def run(output,seed=42,cases=None):
    cases=scenarios() if cases is None else cases
    costs=json.loads((ROOT/'evaluation/costs.json').read_text())
    results=[]
    for case in cases:
        try:
            actual=execute_case(case['steps'],case.get('fixture'),seed)
            scoring=grade(case['expected'],actual,costs)
        except Exception as error:
            # Never turn a harness crash into a passing abstention or expose raw
            # exceptions that could contain customer/provider data.
            actual={'route':'HARNESS_ERROR','exception_type':type(error).__name__}
            scoring={'passed':False,'critical':True,'errors':['harness_error'],
                     'details':[{'category':'harness_error','detail':type(error).__name__}],
                     'component_checks':{},'weighted_cost':costs['costs']['harness_error']}
        results.append({'case_id':case['case_id'],'family':case['family'],'expected':case['expected'],
                        'actual':actual,**scoring})
    by_route={}; confusion=defaultdict(Counter); components=defaultdict(Counter)
    for result in results:
        confusion[result['expected']['route']][result['actual']['route']]+=1
        for name,passed in result['component_checks'].items(): components[name]['passed' if passed else 'failed']+=1
    labels=sorted({r['expected']['route'] for r in results}|{r['actual']['route'] for r in results})
    for route in labels:
        tp=sum(r['expected']['route']==route and r['actual']['route']==route for r in results)
        support=sum(r['expected']['route']==route for r in results)
        predicted=sum(r['actual']['route']==route for r in results)
        group=[r for r in results if r['expected']['route']==route]
        by_route[route]={'support':support,'predicted':predicted,'correct':tp,
                         'precision':tp/predicted if predicted else None,'recall':tp/support if support else None,
                         'cases_passed':sum(r['passed'] for r in group),
                         'critical_false_negatives':sum('critical_false_negative' in r['errors'] for r in group),
                         'unsupported_actions':sum('unsupported_action' in r['errors'] for r in group),
                         'weighted_error_cost':sum(r['weighted_cost'] for r in group)}
    errors=Counter(e for r in results for e in r['errors'])
    pairs=defaultdict(list)
    for case,result in zip(cases,results):
        if case.get('counterfactual_group'):
            pairs[case['counterfactual_group']].append({'case_id':case['case_id'],'material_change':case.get('material_change'),
                         'expected_route':case['expected']['route'],'actual_route':result['actual']['route'],
                         'expected_controls':case['expected'],
                         'actual_controls':{k:result['actual'].get(k) for k in ('review_required','reason','candidates','selected','step','pending_field')},
                         'passed':result['passed']})
    source_paths=list(ROOT.glob('*.py'))+list((ROOT/'evaluation').glob('*.py'))+list((ROOT/'policies').rglob('*.json'))+[
        ROOT/'evaluation/costs.json',ROOT/'scripts/generate_data.py',ROOT/'scripts/load_database.py',Path(__file__)]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(source_paths))}
    summary={'case_count':len(results),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),
             'critical_case_count':sum(r['critical'] for r in results),'error_counts':dict(errors),
             'critical_false_negatives':errors['critical_false_negative'],'unsupported_autonomous_actions':errors['unsupported_action'],
             'false_success_claims':errors['false_success_claim'],'weighted_error_cost':sum(r['weighted_cost'] for r in results),
             'cost_version':costs['version'],'route_metrics':by_route,'route_confusion':{k:dict(v) for k,v in confusion.items()},
             'component_results':{k:dict(v) for k,v in components.items()},'counterfactual_groups':dict(pairs),
             'model_evaluation':'Deterministic extraction by default; mocked model failure/invalid-output adapters. This does not measure live smollm2 extraction accuracy.',
             'limits':['Constructed synthetic functional journeys, not real bank prevalence or independent policy adjudication.',
                       'Shared app turn/reopen services are exercised; browser rendering, session expiry and staff login have separate tests.',
                       'No fitted model is trained on scenario labels. Cases/fault recipes are transparent and related, not independent samples.',
                       'Costs are illustrative relative severities, not currency estimates; categories can overlap.',
                       'Unsupported-claim checks cover provenance and selected dangerous positive assertions, not general semantic entailment.']}
    output=Path(output)
    write_json(output/'cases.json',cases); write_json(output/'costs.json',costs)
    write_json(output/'results.json',results); write_json(output/'summary.json',summary)
    write_json(output/'failed_outputs.json',[r for r in results if not r['passed']])
    write_json(output/'manifest.json',{'seed':seed,'python':platform.python_version(),'dataset':'generate_data(cards_per_customer=2), directly generated INR fixtures',
               'policy_as_of':'2026-10-20','model_transport':'offline mocks only','source_sha256':hashes,
               'cases_sha256':hashlib.sha256(json.dumps(cases,sort_keys=True).encode()).hexdigest(),
               'reproducibility':'Metrics and outcomes repeat for the same seed/source; UUIDs and audit timestamps in full traces intentionally vary.'})
    lines=['# Workflow evaluation',f"Cases: {summary['case_count']}; passed: {summary['passed']}; failed: {summary['failed']}.",
           f"Critical cases: {summary['critical_case_count']}; mandatory-review false negatives: {summary['critical_false_negatives']}; unsupported actions: {summary['unsupported_autonomous_actions']}; false success claims: {summary['false_success_claims']}.",
           f"Weighted error cost: {summary['weighted_error_cost']} ({costs['version']}; not monetary loss).",'',
           '| Expected route | Cases | Correct route | Precision | Recall |','|---|---:|---:|---:|---:|']
    for route,metrics in by_route.items():
        precision='N/A' if metrics['precision'] is None else f"{metrics['precision']:.3f}"
        recall='N/A' if metrics['recall'] is None else f"{metrics['recall']:.3f}"
        lines.append(f"| {route} | {metrics['support']} | {metrics['correct']} | {precision} | {recall} |")
    lines+=['','Failures:']+[f"- {r['case_id']}: {', '.join(r['errors'])}; cost {r['weighted_cost']}." for r in results if not r['passed']]
    lines+=['','These are engineered synthetic functional results. Route correctness alone does not establish safe behaviour. See summary.json for component checks, critical errors and limitations.']
    lines.insert(1,'')
    output.mkdir(parents=True,exist_ok=True); (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/workflow_evaluation/latest')
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args(); summary=run(args.output,args.seed)
    print(json.dumps({k:summary[k] for k in ('case_count','passed','failed','critical_case_count','critical_false_negatives','unsupported_autonomous_actions','false_success_claims','weighted_error_cost')},indent=2))
    raise SystemExit(0 if summary['failed']==0 else 1)
