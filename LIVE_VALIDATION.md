# Live extraction and bank integration validation

## Live Ollama probes

```sh
ollama serve
# In another terminal, if the model is not already installed:
ollama pull smollm2:135m
python scripts/evaluate_live_extraction.py
```

Only 14 explicitly synthetic statements are sent to the fixed loopback Ollama
endpoint. There is no cloud provider, automatic model download or banking action.
The shipped app extraction configuration is exercised, including privacy filtering,
normalisation and source-span validation. This is a small development probe set,
not an independent customer-data benchmark; do not tune and report it as withheld
accuracy. Expected labels are separate from the model prompt.

The evaluator captures one real response per statement, then replays that response
through validation with deterministic proposals removed. This separates validated
model-only performance from combined extraction; fallback cannot take credit as
model success. Valid JSON alone is not counted as correct extraction. Outage or
invalid response exits 2; incomplete model exact-match coverage exits 1; full
model exact-match coverage exits 0. Exact-match scores include empty expected
outputs, so field recall and rejected proposals must also be inspected.

Reports under `data/live_extraction_evaluation/` retain synthetic raw outputs,
rejected fields, expected and actual values, timings, failures, source hashes,
server version and installed model digest where available. Do not reuse this raw
output retention policy for real customer messages.

Observed first run: 14 structurally valid responses, but the model repeated the
prompt example `£10`, which was absent from the customer statements and was
rejected. Validated model field recall was 0%; model exact matches were 5/14,
all empty expected outputs. Field precision was undefined because no model
fields survived validation. Combined extraction achieved 13/14 exact matches,
100% field precision and 89.7% field recall. The ISO-date case lost purchase
amount/date details in the existing pipeline and is preserved as a failure.
These findings do not support relying on this model for extraction. Missing
fields must continue to be clarified and search details confirmed by the user.
The original results are retained under `data/live_extraction_evaluation/before_parser_fix/`. No expected labels were relaxed. The generated summary is authoritative for subsequent reruns.

## Bank contracts versus real integration

```sh
python scripts/validate_bank_integration.py
python scripts/validate_bank_integration.py --require-production
```

The first command runs 28 existing evidence/case-service tests against fresh
isolated SQLite databases and writes `data/bank_integration_validation/report.json`.
Checks include ownership, permission revocation, confirmation, expiry, changed
evidence/policy, same-key replay, concurrent duplicate requests, atomic failure,
timeout before/after commit, reconciliation, encrypted storage and scoped staff
access. The current contract suite passes. Reports contain test IDs and exception
types rather than raw exception messages.

The second command deliberately exits 2 even when simulator contracts pass.
Production status is **NOT_VALIDATED**: this repository has no bank-provided
sandbox adapter, real identity provider or bank-issued service credentials.
The existing SQLite gateway remains the only action adapter; this work does not
silently wire an untested remote service into the chatbot.

Actual integration requires a bank-approved sandbox and adapter, then repeatable
bank-side evidence for:

- Authenticated customer identity and ownership derived from trusted bank claims;
  expired sessions and revoked permissions denied at execution time.
- Transaction lookup schema, currency/amount/date semantics, stale records,
  missing fields and bounded timeout/rate-limit behaviour.
- Durable idempotency keys and business-duplicate semantics under retries and
  concurrent requests; authoritative status lookup after ambiguous outcomes.
- Confirmed action creation versus pending/rejected/unknown outcomes, bank audit
  correlation IDs and recovery after local persistence failure.
- Bank-approved policy versions, privacy controls, retention, secret management,
  monitoring and change approval.

Use test accounts and test transactions only; a bank sandbox passing these
checks still does not authorise production deployment. Credentials must never be
placed in datasets or debug reports. Real-bank validation remains blocked on
those external facilities, rather than being claimed from mock tests.

## Parser correction and default choice

The ISO-date failure came from accepting any alphabetic word as a month:
`85 on 2026` was parsed as a date, concealing the amount and the start of the
real ISO date. Restricting that pattern to supported month names fixes the
cause. All 14 unchanged probes now pass with deterministic extraction alone.
This is a regression result on known development examples, not unseen accuracy.

```sh
python scripts/evaluate_deterministic_extraction.py
```

`CONCERN_EXTRACTION_MODE` now defaults to `deterministic` in code and the example
configuration. Unknown modes also make no model call. Existing shell exports
of `CONCERN_EXTRACTION_MODE=ollama` remain explicit opt-ins; unset the variable or
export `CONCERN_EXTRACTION_MODE=deterministic` to use the recommended path.
Model provenance is null when no model is called. The live evaluator explicitly
enables Ollama so it continues to measure the actual model, independently of the
new default. The original failed outputs remain available for comparison.

Regression tests cover ISO, DD-MM-YYYY and named-month formats; date-only inputs
that must not produce amounts; amount counterfactuals; default no-network
behaviour; and PII mixed with transaction details. They also exposed an existing
phone-redaction boundary bug at a sentence-ending full stop. That boundary now
permits punctuation while still excluding decimal continuations; the privacy
suite passes. The PII detector remains heuristic and is not exhaustive.

After the fix, the actual Ollama rerun also achieved 14/14 combined exact matches
with 100% field precision/recall. Model-only validated field recall remained 0%
and all 14 responses contained rejected model fields. The live evaluator therefore
still exits 1 intentionally: parser success does not satisfy model-quality checks.
The full regression suite passes 186 tests; all 47 workflow journeys still pass.
