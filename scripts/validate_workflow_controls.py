"""Reproduce step-4 shared-service and handoff continuation contract checks."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workflow_contract import EDGES, VERSION
from report_metadata import portable


def run(output):
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_workflow_controls')
    tests=[test.id() for group in suite for test in group]
    result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=2).run(suite)
    failures={test.id():portable(trace) for test,trace in result.failures+result.errors}
    names=('workflow_contract.py','workflow.py','concerns.py','handoff_continuation.py','representative_ui.py','conversation.py','tests/test_workflow_controls.py','scripts/validate_workflow_controls.py')
    report={'version':'WORKFLOW-CONTROLS-EVALUATION-1.0','workflow_version':VERSION,
            'tests_run':result.testsRun,'passed':result.testsRun-len(failures),'failures':failures,
            'tests':tests,'ordinary_transitions':{key:sorted(value) for key,value in EDGES.items()},
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names},
            'limits':['Synthetic temporary databases and deterministic modes only.',
                      'Continuation test checks package facts/tasks, not a real representative usability study.',
                      'Not formal verification or exhaustive coverage of all transition pairs.',
                      'Case/card services retain explicit confirmation, permission and idempotency guards.']}
    output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'tests_run':result.testsRun,'passed':report['passed'],'failure_count':len(failures)},indent=2))
    return result.wasSuccessful()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/workflow_controls')
    raise SystemExit(not run(parser.parse_args().output))
