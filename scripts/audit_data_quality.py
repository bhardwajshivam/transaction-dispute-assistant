"""Reproducible offline data audit. Never queries a working database or fits runtime models."""
import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.generate_data import validate
from scripts.generate_activity_data import quality
from evaluation.scenarios import scenarios


def tokens(text):
    return re.findall(r'[a-z]+', text.lower())


def canonical(text):
    text = re.sub(r'\b(?:TX|CARD)-[\d-]+\b', ' REFERENCE ', text, flags=re.I)
    text = re.sub(r'\d+(?:[./-]\d+)*', ' NUMBER ', text)
    return ' '.join(tokens(text))


def similarities(left, right, threshold=.8, same=False):
    pairs = []
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            if same and j <= i:
                continue
            ca, cb = canonical(a['text']), canonical(b['text'])
            score = SequenceMatcher(None, ca, cb, autojunk=False).ratio()
            if score >= threshold:
                pairs.append({'left': a['id'], 'right': b['id'], 'similarity': round(score, 4),
                              'exact_normalised': ca == cb,
                              'intentional_counterfactual': bool(a.get('pair') and a.get('pair') == b.get('pair')),
                              'same_target': a['label'] == b['label']})
    return pairs


def wording_baseline(train, test):
    """Laplace-smoothed multinomial NB; words only, no IDs, steps, evidence or labels as features."""
    counts, docs = defaultdict(Counter), Counter()
    for row in train:
        counts[row['label']].update(tokens(row['text'])); docs[row['label']] += 1
    vocab = set().union(*(set(c) for c in counts.values()))
    predictions = []
    majority = sorted(docs, key=lambda label: (-docs[label], label))[0]
    for row in test:
        words = Counter(tokens(row['text']))
        scores = {label: math.log(docs[label]/len(train)) + sum(n*math.log((counts[label][w]+1)/(sum(counts[label].values())+len(vocab))) for w,n in words.items()) for label in docs}
        predicted = sorted(scores, key=lambda label: (-scores[label], label))[0]
        predictions.append({'id': row['id'], 'expected': row['label'], 'predicted': predicted})
    return {'train_count': len(train), 'test_count': len(test), 'accuracy': sum(p['expected']==p['predicted'] for p in predictions)/len(test),
            'majority_accuracy': sum(r['label']==majority for r in test)/len(test), 'predictions': predictions,
            'limit': 'Four examples per split; next-question labels, not terminal routes. Diagnostic only, no model selection or runtime training.'}


def token_associations(rows):
    counts = defaultdict(Counter)
    for row in rows:
        for token in set(tokens(row['text'])):
            counts[token][row['label']] += 1
    return sorted([{'token': word, 'support': sum(labels.values()), 'route_counts': dict(sorted(labels.items())),
                    'dominant_route_fraction': max(labels.values())/sum(labels.values())} for word,labels in counts.items() if sum(labels.values()) >= 3],
                  key=lambda row: (-row['dominant_route_fraction'], -row['support'], row['token']))


def load_runtime(path):
    return {p.stem: json.loads(p.read_text()) for p in sorted(path.glob('*.json'))}


def initial_rows(root, split):
    base = root/'data'/split
    labels = {r['scenario_id']: r['expected_next_question'] for r in json.loads((base/'expected_outcomes.json').read_text())}
    return [{'id': r['scenario_id'], 'text': r['initial_statement'], 'label': labels[r['scenario_id']]} for r in json.loads((base/'customer_statements.json').read_text())]


def audit(root=ROOT):
    data = load_runtime(root/'data/runtime')
    rich = load_runtime(root/'data/activity_corpus/runtime')
    splits = {s:json.loads((root/f'data/activity_corpus/{s}/activity_cases.json').read_text()) for s in ('development','evaluation')}
    rich_report = quality(rich, splits)
    dev, test = initial_rows(root,'development'), initial_rows(root,'evaluation')
    workflow = scenarios()
    rows = [{'id':c['case_id'], 'text':c['steps'][2] if len(c['steps'])>2 else '', 'label':c['expected']['route'], 'pair':c['counterfactual_group']} for c in workflow if len(c['steps'])>2 and c['steps'][1].startswith('CARD-')]
    txids = {t['transaction_id'] for t in data['transactions']}
    reference_errors = []
    for split in ('development','evaluation'):
        for r in json.loads((root/f'data/{split}/expected_outcomes.json').read_text()):
            if r['transaction_id'] not in txids: reference_errors.append(r['scenario_id'])
    comparisons = similarities(dev,test)
    within = similarities(rows,rows,same=True)
    inputs = [root/'evaluation/scenarios.py',root/'evaluation/data_challenges.json',root/'scripts/audit_data_quality.py',root/'scripts/generate_data.py',root/'scripts/generate_activity_data.py']
    for folder in ('data/runtime','data/development','data/evaluation','data/activity_corpus/runtime','data/activity_corpus/development','data/activity_corpus/evaluation'):
        inputs += sorted((root/folder).glob('*.json'))
    challenges = json.loads((root/'evaluation/data_challenges.json').read_text())
    return {'version':'DATA-AUDIT-1.0','input_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)},
            'base_quality':validate(data),'base_field_missingness':{key:sum(t.get(key) in (None,'') for t in data['transactions']) for key in sorted(set().union(*(set(t) for t in data['transactions'])))},'activity_quality':rich_report,
            'label_consistency':{'initial_transaction_reference_errors':reference_errors, 'limit':'Structural/reference consistency is checked. Independent correctness of terminal policy labels is not established by this audit; evaluator comparison belongs to step 6.'},
            'initial_text':{'development_labels':dict(Counter(r['label'] for r in dev)), 'evaluation_labels':dict(Counter(r['label'] for r in test)),
                            'cross_split_pairs_at_0_8':comparisons, 'pair_count':len(dev)*len(test), 'near_pair_rate':len(comparisons)/(len(dev)*len(test)), 'shared_label_families':sorted(set(r['label'] for r in dev)&set(r['label'] for r in test)),'normalisation':'Lowercase words; remove specific reference and numeric values. SequenceMatcher ratio >=0.8. This detects surface overlap, not semantic equivalence.',
                            'word_only_baseline':wording_baseline(dev,test)},
            'workflow_text':{'sample_count':len(rows),'route_balance':dict(Counter(c['expected']['route'] for c in workflow)),
                             'pairs_at_0_8':within,'possible_pair_count':len(rows)*(len(rows)-1)//2,'near_pair_rate':len(within)/(len(rows)*(len(rows)-1)//2), 'exact_normalised_pair_count':sum(p['exact_normalised'] for p in within), 'literal_label_in_text':[r['id'] for r in rows if r['label'].lower() in r['text'].lower()], 'token_route_associations':token_associations(rows),
                             'limit':'Description only, excluding opening UI labels and subsequent replies. Token associations can be legitimate issue cues; neither high nor low association proves leakage.'},
            'boundary_coverage':{'activity_families':rich_report['evaluation_family_balance'], 'workflow_families':dict(Counter(c['family'] for c in workflow)),
                                 'limit':'Counts of constructed families, not proof every policy threshold is covered.'},
            'frozen_challenges':{'count':len(challenges['cases']),'status':'EXPECTED_BEHAVIOURS_FROZEN_NOT_EXECUTED','independent_review':'PENDING_EXTERNAL_REVIEW','sha256':hashlib.sha256((root/'evaluation/data_challenges.json').read_bytes()).hexdigest()},
            'findings':['Shared family recipes remain across splits; no held-out-family generalisation claim.',
                        'Within-workflow similar descriptions often end in different routes because evidence/replies differ. Text alone cannot establish terminal route.',
                        'Normalised similarity ignores amounts/dates deliberately to expose repeated templates; this is separate from exact evidence-signature overlap.',
                        'New challenges were authored during this development session; they are not independently adjudicated labels.',
                        'Activity labels exclude construction metadata at runtime; zero exact overlap does not rule out template leakage.'],
            'errors':validate(data)['errors']+rich_report['errors']+reference_errors}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'data/data_quality');args=parser.parse_args()
    report=audit();args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    near=report['workflow_text']['pairs_at_0_8']; baseline=report['initial_text']['word_only_baseline']; q=report['activity_quality']
    text=f'''# Consolidated data-quality audit

Reproduce: `python scripts/audit_data_quality.py`. Full counts, pairs, token associations and input hashes: `report.json`.

- Base transactions: {report['base_quality']['transaction_count']}; richer transactions: {q['transaction_count']}.
- Structural/reference errors: {len(report['errors'])}.
- Activity customer overlap: {len(q['customer_split_overlap'])}; normalised exact cross-split input overlap: {q['exact_cross_split_inputs']}.
- Activity repeated inputs within split: {q['repeated_inputs_within_split']} (intentional authorisation non-identifiability).
- Richer missing receipts: {q['missing_receipt_count']}; missing order references: {q['missing_order_references']}.
- Workflow similar-description pairs: {len(near)}; explicitly tagged counterfactual pairs: {sum(p['intentional_counterfactual'] for p in near)}. Untagged pairs require review, not automatic deletion.
- Initial four-case text-only NB accuracy: {baseline['accuracy']:.2%}; majority: {baseline['majority_accuracy']:.2%}. Too small for generalisation claims; the target is next question, not terminal route.

## Interpretation and action

Shared scenario families and templates remain. Customer-disjoint splits and no exact evidence overlap do not establish independent generalisation. Similarity is lexical, not a semantic duplicate detector. Token associations are reported as diagnostic signals, not proof of label leakage. No classifier from this audit is used by the application. Route balance and boundary family counts are in JSON; they are coverage inventories rather than evidence of complete policy coverage.

Structural and reference checks run on the actual generated JSON, not only copied reports. Labels remain hand-authored: this audit cannot establish independent policy correctness. Frozen new challenges have not been executed and require external review before any independence claim.

## Defects found and corrected

Previously observed: random missingness could erase supporting anchor records; constructed anchors are now protected. An accidentally repeated positive control was made temporally distinct. ISO date parsing once swallowed amount digits; supported month matching corrected it. Most recently, model extraction labelled a date phrase as merchant and hid valid transactions; merchant semantic validation and removal of merchant search filters fixed the failure. These are documented development observations, not newly discovered by this audit. See ACTIVITY_DATA.md, LIVE_VALIDATION.md and the step-1 observed_failure.json.

## Remaining limitations

External label adjudication, semantic paraphrase review, broader language coverage and complete policy-boundary coverage remain open. New live-model and end-to-end results belong to later stages. Do not interpret an empty structural error list as complete submission compliance.
'''
    (args.output/'REPORT.md').write_text(text)
    print(json.dumps({'errors':report['errors'],'workflow_similar_pairs':len(near),'initial_text_accuracy':baseline['accuracy'],'new_challenges':report['frozen_challenges']['count']},indent=2))
    return bool(report['errors'])

if __name__=='__main__':
    raise SystemExit(main())
