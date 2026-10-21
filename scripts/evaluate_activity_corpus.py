"""Evaluate richer activity data without importing labels into the application."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from activity import evaluate,review_decision
from scripts.generate_data import write_json


def run(root,split='evaluation'):
    root=Path(root)
    if split not in ('development','evaluation'):
        raise ValueError('Unknown split')
    cases=json.loads((root/split/'activity_cases.json').read_text())
    results=[]; truth=Counter()
    for case in cases:
        # Only numerical/categorical bank facts cross this boundary. Labels,
        # construction family, truth and customer statements are not inputs.
        result=evaluate(case['transaction'],case['history'])
        route=review_decision(result)
        actual=dict(status=result['status'],reason_codes=sorted(s['reason_code'] for s in result['signals']),route=route['route'])
        passed=actual==case['expected']
        flag=route['route']=='RECOMMEND_SPECIALIST_REVIEW'
        truth[f"{case['authorisation_truth']}:{'flagged' if flag else 'not_flagged'}"]+=1
        results.append(dict(case_id=case['case_id'],family=case['family'],variant=case['variant'],passed=passed,actual=actual,expected=case['expected']))
    report=dict(split=split,case_count=len(cases),passed=sum(r['passed'] for r in results),
                family_balance=dict(Counter(c['family'] for c in cases)),
                failures=[r for r in results if not r['passed']],results=results,
                authorisation_vs_anomaly=dict(truth),
                interpretation='A flagged authorised purchase is a legitimate anomaly, not proven fraud. A non-flagged unauthorised purchase demonstrates why complaint routing must remain independent. These are constructed cases, not calibrated fraud prevalence.',
                leakage_control='Customer-disjoint splits; numerical facts only; opaque random references; no model fitting or threshold tuning.')
    write_json(root/'results'/f'{split}_report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[1]/'data/activity_corpus')
    parser.add_argument('--split',choices=['development','evaluation'],default='evaluation')
    args=parser.parse_args()
    result=run(args.data,args.split)
    print(json.dumps({k:result[k] for k in ('split','case_count','passed','authorisation_vs_anomaly')},indent=2))
    raise SystemExit(0 if result['passed']==result['case_count'] else 1)
