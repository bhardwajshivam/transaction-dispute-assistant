"""Offline privacy/failure/export checks; never exports real operational data."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from operations import summarise


def run(output):
    modules=('tests.test_operational_privacy','tests.test_privacy','tests.test_report_metadata')
    suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
    result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=2).run(suite)
    # Failure stacks can contain test canaries or local paths. Publish fixed
    # categories and test names; reproduce locally for detailed diagnostics.
    failures=[{'test':test.id(),'code':'TEST_FAILURE_OR_ERROR'} for test,_ in result.failures+result.errors]
    files=('operations.py','diagnostic_codes.py','privacy.py','secure_storage.py','concern_extraction.py','workflow.py','evidence_agent.py','representative_ui.py','tests/test_operational_privacy.py','tests/test_privacy.py','tests/test_report_metadata.py','scripts/validate_privacy_operations.py')
    report={'version':'PRIVACY-OPERATIONS-VALIDATION-1.0','scope':'Offline synthetic tests only; no working customer database scanned or exported.',
            'tests_run':result.testsRun,'passed':result.testsRun-len(failures),'failures':failures,'test_modules':modules,
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},
            'synthetic_counter_example':summarise([{'extraction_trace':[{'model':'smollm2:135m','status':'EXTRACTION_UNAVAILABLE_GUIDED_FALLBACK'}],'review_requirement':'REQUIRED','review_reason_codes':['POLICY_UNAVAILABLE']}]),
            'limits':['Canary-based checks do not establish exhaustive PII detection or compliance.',
                      'OS, proxy and third-party logs are outside this application test.',
                      'Aggregate counts remain sensitive and require staff scope; no anonymity claim.',
                      'Unknown action counts reflect current commands; replay attempts and pre-save errors are not measured.']}
    output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'tests_run':result.testsRun,'passed':report['passed'],'failures':failures},indent=2))
    return result.wasSuccessful()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/privacy_operations')
    raise SystemExit(not run(parser.parse_args().output))
