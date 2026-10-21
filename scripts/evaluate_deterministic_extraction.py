"""Offline extraction probes, with no model or fallback dependency."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concern_extraction import extract
from scripts.evaluate_live_extraction import metrics
from scripts.generate_data import write_json
ROOT = Path(__file__).resolve().parents[1]


def run(output):
    source = ROOT/'evaluation/extraction_cases.json'
    rows = []
    for case in json.loads(source.read_text()):
        fields, _, trace = extract(case['text'], case['kind'], use_ollama=False)
        rows.append({'id':case['id'], 'expected':case['expected'], 'actual':fields,
                     'trace':trace, **metrics(case['expected'], fields)})
    summary = {'mode':'deterministic', 'cases':len(rows), 'passed':sum(r['exact_match'] for r in rows),
               'case_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
               'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                for name in ('concern_extraction.py','intake.py','privacy.py', 'scripts/evaluate_deterministic_extraction.py')},
               'limits':'Fixed synthetic development probes, not independent customer-data accuracy.'}
    write_json(Path(output)/'results.json', rows)
    write_json(Path(output)/'summary.json', summary)
    write_json(Path(output)/'failed_outputs.json', [r for r in rows if not r['exact_match']])
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/deterministic_extraction_evaluation')
    result = run(parser.parse_args().output)
    print(json.dumps(result, indent=2))
    raise SystemExit(int(result['passed'] != result['cases']))
