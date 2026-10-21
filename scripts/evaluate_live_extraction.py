"""Measure actual loopback Ollama extraction; failures never count as model success."""
import argparse
from copy import deepcopy
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
from time import monotonic
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import concern_extraction as extraction
from ollama_backend import local_chat
from scripts.generate_data import write_json
from report_metadata import model_metadata, portable

ROOT = Path(__file__).resolve().parents[1]


def metrics(expected, actual):
    correct = sum(actual.get(k) == v for k, v in expected.items())
    wrong = {k: v for k, v in actual.items() if k not in expected or expected[k] != v}
    missing = {k: v for k, v in expected.items() if actual.get(k) != v}
    return {'exact_match': actual == expected, 'correct_fields': correct,
            'predicted_fields': len(actual), 'expected_fields': len(expected),
            'unsupported_or_wrong_fields': wrong, 'missing_or_wrong_fields': missing}


def server_metadata():
    metadata = {}
    for endpoint, key in (('/api/version', 'server'), ('/api/tags', 'models')):
        connection = HTTPConnection('127.0.0.1', 11434, timeout=3)
        try:
            connection.request('GET', endpoint)
            response = connection.getresponse()
            raw = response.read(262145)
            if response.status != 200 or len(raw) > 262144:
                raise ValueError()
            value = json.loads(raw)
            if key == 'models':
                value = [model_metadata(m)
                         for m in value.get('models', []) if m.get('name') == 'smollm2:135m']
            else:
                value = {'version': value.get('version')}
            metadata[key] = portable(value)
        except Exception:
            metadata[key] = 'UNAVAILABLE'
        finally:
            connection.close()
    return metadata


def run(output, transport=local_chat, cases_path=None):
    path = Path(cases_path) if cases_path else ROOT / 'evaluation/extraction_cases.json'
    cases = json.loads(path.read_text())
    rows = []
    before_metadata = server_metadata() if transport is local_chat else {'status':'TEST_ADAPTER'}
    # Explicitly enable the actual extraction path regardless of UI fallback settings.
    with patch.dict('os.environ', {'CONCERN_EXTRACTION_MODE': 'ollama'}):
        for case in cases:
            response = {}; failure = None
            def capture(payload, timeout):
                nonlocal response, failure
                try:
                    response = transport(payload, timeout)
                    return response
                except Exception as error:
                    failure = getattr(error, 'code', type(error).__name__)
                    raise
            started = monotonic()
            parser_only, _, parser_trace = extraction.extract(case['text'], case['kind'], use_ollama=False)
            combined, _, trace = extraction.extract(case['text'], case['kind'], transport=capture)
            elapsed = round((monotonic() - started) * 1000)
            available = trace['status'] == 'OLLAMA_EXTRACTED'
            # Replay the same response through the same validation, without parser
            # proposals, to distinguish model contribution from deterministic rescue.
            with patch.object(extraction, 'baseline_entities', return_value=[]):
                model_only, _, model_trace = extraction.extract(case['text'], case['kind'], transport=lambda *_: deepcopy(response))
            rows.append({'id': case['id'], 'expected': case['expected'],
                         'response': portable(response), 'error_code': failure, 'elapsed_ms': elapsed,
                         'rejected_model_fields': model_trace.get('rejected_fields', []),
                         'model_response_valid': available, 'trace': trace,
                         'model_only': model_only, 'parser_only': parser_only, 'combined': combined,
                         'parser_trace': parser_trace, 'parser_metrics': metrics(case['expected'], parser_only),
                         'model_metrics': metrics(case['expected'], model_only),
                         'combined_metrics': metrics(case['expected'], combined)})
    summary = {'cases': len(rows), 'valid_model_responses': sum(r['model_response_valid'] for r in rows),
               'model_name': extraction.MODEL, 'extraction_contract': extraction.contract_metadata(),
               'server_metadata_before': before_metadata,
               'server_metadata': server_metadata() if transport is local_chat else {'status':'TEST_ADAPTER'},
               'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('concern_extraction.py','intake.py','privacy.py','scripts/evaluate_live_extraction.py','report_metadata.py')},
               'cases_with_rejected_model_fields': sum(bool(r['rejected_model_fields']) for r in rows),
               'model_response_note': 'Valid JSON does not imply grounded or useful extraction. Precision/recall describe validated fields; inspect rejected proposals and raw synthetic outputs.',
               'transport': 'actual loopback Ollama' if transport is local_chat else 'test adapter',
               'case_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
               'limits': 'Handwritten synthetic probes; not independent customer data. No banking actions or production validation.'}
    for label in ('model', 'parser', 'combined'):
        totals = {k: sum(r[label+'_metrics'][k] for r in rows) for k in ('correct_fields','predicted_fields','expected_fields')}
        summary[label] = {'exact_matches': sum(r[label+'_metrics']['exact_match'] and (r['model_response_valid'] or label in ('parser', 'combined')) for r in rows),
                          'field_precision': totals['correct_fields']/totals['predicted_fields'] if totals['predicted_fields'] else None,
                          'field_recall': totals['correct_fields']/totals['expected_fields'] if totals['expected_fields'] else None,
                          'cases_with_wrong_fields': sum(bool(r[label+'_metrics']['unsupported_or_wrong_fields']) for r in rows)}
    summary['model_identity_stable'] = before_metadata == summary['server_metadata'] if transport is local_chat else None
    summary['parser_supported_cases'] = sum(any('deterministic_parser' in sources for sources in r['trace'].get('field_sources', {}).values()) for r in rows)
    summary['model_contributed_cases'] = sum(any('ollama' in sources for sources in r['trace'].get('field_sources', {}).values()) for r in rows)
    summary['transport_or_schema_fallback_cases'] = sum(not r['model_response_valid'] for r in rows)
    summary['no_validated_model_fields_cases'] = sum(not r['model_only'] for r in rows)
    summary['fallback_note'] = 'Parser is always a supporting path, not only an outage fallback. Empty model output on an empty-target case is not a failure.'
    summary['field_role_breakdown'] = {}
    for field in extraction.FIELDS:
        role_metrics = {}
        for label, key in (('model','model_only'), ('parser','parser_only'), ('combined','combined')):
            role_metrics[label] = {
                'correct': sum(field in r['expected'] and r[key].get(field) == r['expected'][field] for r in rows),
                'expected': sum(field in r['expected'] for r in rows),
                'wrong': sum(field in r[key] and r[key][field] != r['expected'].get(field) for r in rows),
            }
        summary['field_role_breakdown'][field] = role_metrics
    summary['status'] = 'UNAVAILABLE_OR_INVALID' if summary['valid_model_responses'] != len(rows) else 'MEASURED'
    if transport is local_chat and not summary['model_identity_stable']:
        summary['status'] = 'MODEL_IDENTITY_CHANGED_OR_UNAVAILABLE'
    write_json(Path(output)/'results.json', rows)
    write_json(Path(output)/'summary.json', summary)
    write_json(Path(output)/'failed_outputs.json', [r for r in rows if not r['model_response_valid'] or not r['model_metrics']['exact_match'] or not r['combined_metrics']['exact_match'] or not r['parser_metrics']['exact_match']])
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/live_extraction_evaluation')
    parser.add_argument('--cases', type=Path, default=ROOT/'evaluation/extraction_cases.json')
    args = parser.parse_args()
    result = run(args.output, cases_path=args.cases)
    print(json.dumps(result, indent=2))
    raise SystemExit(2 if result['status'] != 'MEASURED' else int(result['model']['exact_matches'] != result['cases']))
