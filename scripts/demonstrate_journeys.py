"""Reproduce the assignment's required journeys through the shared app services."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.scenarios import scenarios
from scripts.evaluate_workflow import run
ROOT=Path(__file__).resolve().parents[1]
IDS=('recognised','cancelled_subscription','ongoing_card_risk','policy_question',
     'search_amount_42','policy_missing','model_timeout','tool_unavailable_handoff')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/workflow_evaluation/demonstrations')
    args=parser.parse_args()
    selected={c['case_id']:c for c in scenarios()}
    result=run(args.output,cases=[selected[k] for k in IDS])
    print(f"Required journey demonstrations: {result['passed']}/{result['case_count']} pass.")
    raise SystemExit(int(result['failed']>0))
