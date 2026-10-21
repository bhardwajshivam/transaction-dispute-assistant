"""Application entry point for optional model-assisted evidence gathering."""
import os

from evidence_agent import gaps, propose, run
from model_proposer import make_proposer
from review import update_review

CONFIG_FAILURES = {'INVALID_LOCAL_MODEL', 'INVALID_TIMEOUT', 'INVALID_OUTPUT_LIMIT', 'INVALID_CONFIGURATION'}


def gather(state, customer_id='C-001', database=None, mode=None, backend=None):
    _gather(state, customer_id, database, mode, backend)
    # Compare assertions with retrieved facts without replacing either source.
    # Request date and effective date have different meanings: compare only the
    # customer's request date to the merchant request date.
    cancellation=state.get('evidence',{}).get('cancellations',{})
    reported=state.get('answers',{}).get('cancel_date')
    if cancellation.get('status')=='SUCCESS' and reported and reported!='I don’t know':
        dates={r.get('requested_date') for r in cancellation.get('records',[])}
        if dates and reported not in dates:
            signals=state.setdefault('review_signals',[])
            if 'MATERIAL_EVIDENCE_CONFLICT' not in signals:
                signals.append('MATERIAL_EVIDENCE_CONFLICT')
                state['messages'].append(('assistant','Your reported cancellation request date differs from the merchant request record. Both accounts have been retained; specialist review is required.'))
    from activity import attach
    attach(state, customer_id, database)
    from clustering import attach as attach_clustering
    attach_clustering(state, customer_id, database)
    update_review(state)


def _gather(state, customer_id='C-001', database=None, mode=None, backend=None):
    """Only explicit `ollama` mode can use an local model backend.

    Transaction ownership is always checked locally first. A model failure opens
    a concern-local circuit breaker; remaining lookups use the baseline.
    `backend` is an injection boundary for offline tests, never customer input.
    """
    requested = mode if mode is not None else os.environ.get('EVIDENCE_PROPOSER_MODE', 'deterministic')
    runtime = {'requested_mode': requested if requested in ('deterministic', 'ollama') else 'invalid',
               'effective_mode': 'deterministic', 'status': 'BASELINE'}
    state['evidence_runtime'] = runtime
    if requested == 'deterministic':
        run(state, customer_id=customer_id, database=database)
        update_review(state)
        return
    if requested != 'ollama':
        runtime['status'] = 'INVALID_MODE_FALLBACK'
        run(state, customer_id=customer_id, database=database)
        update_review(state)
        return

    # Preflight is a local read-only controller operation, not a model choice.
    if gaps(state) == ['transaction']:
        def ownership_only(s):
            return propose(s) if gaps(s) == ['transaction'] else None
        run(state, proposer=ownership_only, customer_id=customer_id, database=database)
    if state.get('evidence', {}).get('transaction', {}).get('status') != 'SUCCESS':
        runtime['status'] = 'TRANSACTION_NOT_VERIFIED'
        update_review(state)
        return
    if not gaps(state):
        runtime['status'] = 'NO_REMAINING_GAPS'
        update_review(state)
        return
    if state.get('model_circuit_open'):
        runtime['status'] = 'MODEL_CIRCUIT_OPEN'
        run(state, customer_id=customer_id, database=database)
        update_review(state)
        return
    if backend is None:
        try:
            from ollama_backend import backend_from_env
            backend = backend_from_env()
        except Exception as exc:
            code = getattr(exc, 'code', None)
            runtime['status'] = code if code in CONFIG_FAILURES else 'MODEL_CONFIGURATION_FAILED'
            state['model_circuit_open'] = True
            run(state, customer_id=customer_id, database=database)
            update_review(state)
            return
    proposer = make_proposer(backend)
    runtime.update(effective_mode='model_assisted', status='ENABLED')

    def guarded_proposer(s):
        if s.get('model_circuit_open'):
            return propose(s)
        count = len(s.get('proposer_trace', []))
        result = proposer(s)
        trace = s.get('proposer_trace', [])
        if len(trace) > count:
            latest = trace[-1]
            if latest['fallback']:
                s['model_circuit_open'] = True
                runtime.update(effective_mode='deterministic_fallback', status='MODEL_CIRCUIT_OPEN')
            else:
                metadata = getattr(backend, 'last_metadata', None)
                if isinstance(metadata, dict):
                    # Persist only bounded numerical telemetry, never provider text.
                    latest['usage'] = {key: metadata[key] for key in ('input_tokens', 'output_tokens', 'elapsed_ms')
                                       if type(metadata.get(key)) is int and metadata[key] >= 0}
        return result

    run(state, proposer=guarded_proposer, customer_id=customer_id, database=database)
    update_review(state)
