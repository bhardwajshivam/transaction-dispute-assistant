"""Verify local simulator contracts; explicitly record absent real-bank validation."""
import argparse
import contextlib
import hashlib
import io
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.generate_data import write_json

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('tests.test_case_service', 'tests.test_evidence_agent')


class RecordedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.checks = []
    def addSuccess(self, test):
        super().addSuccess(test)
        self.checks.append({'test': test.id(), 'status': 'PASS'})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.checks.append({'test': test.id(), 'status': 'FAIL', 'exception_type': err[0].__name__})
    def addError(self, test, err):
        super().addError(test, err)
        self.checks.append({'test': test.id(), 'status': 'ERROR', 'exception_type': err[0].__name__})
    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.checks.append({'test': test.id(), 'status': 'SKIPPED'})


def run(output):
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = RecordedResult()
    # Reports contain test IDs and exception types, never raw customer/provider traces.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        suite.run(result)
    passed = bool(result.testsRun) and result.wasSuccessful() and not result.skipped and not result.expectedFailures
    report = {'environment': 'ISOLATED_SQLITE_SIMULATOR', 'tests_run': result.testsRun,
              'contract_status': 'PASS' if passed else 'FAIL', 'checks': result.checks,
              'production_status': 'NOT_VALIDATED',
              'production_blockers': ['No bank sandbox endpoint or bank-approved adapter has been supplied.',
                  'No real identity provider, service credentials or bank permission contract is configured.',
                  'No bank-verified idempotency, reconciliation, timeout or audit evidence is available.'],
              'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                  ('case_service.py','evidence_agent.py','tests/test_case_service.py','tests/test_evidence_agent.py')}}
    write_json(Path(output)/'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/bank_integration_validation')
    parser.add_argument('--require-production', action='store_true', help='Fail closed until real-bank validation exists.')
    args = parser.parse_args()
    report = run(args.output)
    print(f"Simulator contracts: {report['contract_status']} ({report['tests_run']} tests). Production: NOT_VALIDATED.")
    raise SystemExit(1 if report['contract_status'] != 'PASS' else 2 if args.require_production else 0)
