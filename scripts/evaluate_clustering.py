"""Observe clustering on untouched corpus splits; do not fit/tune using labels."""
import argparse
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from clustering import evaluate,review_decision,config
from scripts.generate_data import write_json


def run(root,split='evaluation'):
    root=Path(root)
    if split not in ('development','evaluation'): raise ValueError('Unknown split')
    cases=json.loads((root/split/'activity_cases.json').read_text())
    results=[]; counts=Counter(); truth=Counter()
    for case in cases:
        assessment=evaluate(case['transaction'],case['history'])
        status=assessment['status']; counts[status]+=1
        state='abstained' if status!='ASSESSED' else 'flagged' if assessment['flagged'] else 'not_flagged'
        truth[case['authorisation_truth']+':'+state]+=1
        results.append(dict(case_id=case['case_id'],family=case['family'],status=status,reason_code=assessment['reason_code'],
                            anomaly_score=assessment.get('anomaly_score'),flagged=assessment.get('flagged'),
                            model_id=assessment.get('model_id'),route=review_decision(assessment)['route']))
    probes=[]; customers=set()
    for case in cases:
        if case['customer_id'] in customers: continue
        customers.add(case['customer_id'])
        tx=deepcopy(case['transaction'])
        tx['amount_minor']=100*max(r['amount_minor'] for r in case['history'])
        stress=evaluate(tx,case['history'])
        probes.append(dict(customer_id=case['customer_id'],construction='100x_largest_historical_amount',
                           status=stress['status'],anomaly_score=stress.get('anomaly_score'),flagged=stress.get('flagged')))
    report=dict(configuration=config(),split=split,case_count=len(cases),status_counts=dict(counts),
                authorisation_vs_cluster=dict(truth),results=results,
                separate_extreme_amount_probes=probes,
                interpretation='Descriptive synthetic results, not fraud accuracy or a calibrated probability. Case recipes and legitimate-outlier repeats are not independent observations. No thresholds were tuned using these outcomes.')
    write_json(root/'results'/f'{split}_clustering_report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[1]/'data/activity_corpus')
    parser.add_argument('--split',choices=['development','evaluation'],default='evaluation')
    args=parser.parse_args()
    r=run(args.data,args.split)
    print(json.dumps({k:r[k] for k in ('split','case_count','status_counts','authorisation_vs_cluster')},indent=2))
