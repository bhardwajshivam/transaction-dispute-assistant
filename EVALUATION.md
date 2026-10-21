# Workflow evaluation

The offline evaluator runs 47 constructed journeys through `workflow.process` and
`workflow.reopen`, the same application services used by Streamlit. Each case
gets a fresh temporary SQLite database, two cards per generated customer and a
fixed policy date of 20 October 2026. No live database is reset. It exercises the
controller, evidence tools, policy gates, concern persistence and simulated case
service together. It does not perform real banking actions.

## Reproduce

From the repository root, after the README setup:

```sh
python scripts/evaluate_workflow.py
python -m unittest discover -s tests -q
```

The evaluator exits nonzero on any failed case. Use `--seed 42 --output data/custom_evaluation`
to write elsewhere. No Ollama server or network is required. Deterministic
extraction is the default; trusted mock adapters exercise model and tool failures.

The [latest report](data/workflow_evaluation/latest/REPORT.md) summarises results.
Its directory also contains reference cases, full sanitised synthetic traces,
failed outputs, component results, route confusion, route-specific precision,
recall, critical misses and weighted costs. The manifest fingerprints source,
policy, costs and reference cases. Metrics repeat with the same seed and source;
UUIDs and audit timestamps intentionally vary. Empty denominators are reported
as null/N/A, rather than perfect scores.

## Reference cases and success criteria

`evaluation/scenarios.py` contains explicit expected behaviours, separate from
execution in `evaluation/runner.py`. The executor accepts steps and fixture
configuration, never expected labels. Labels are hand-authored engineering
expectations against the fictional policy; they are not independently adjudicated
bank labels. No model is trained on these cases. Keep these evaluation recipes
out of generation/training inputs. Related cases and shared templates make this a
transparent conformance suite, not an independent statistical sample.

Coverage includes merchant recognition, unauthorised or uncertain activity,
cancelled subscriptions, duplicate charges, wrong amounts, refunds, card/account
scope, ambiguous matches, incomplete details, policy questions, missing/expired/
conflicting/tampered policy, injection, malformed evidence, extraction failures,
read-tool failure, handoff, case confirmation and expiry, revoked permission,
repeat submissions, timeouts before and after commit, and reopen after a failed
conversation save.

| Capability | Passing behaviour |
|---|---|
| Understanding | Reject unsupported extraction; recover safely from invalid output/timeouts |
| Transaction matching | Expected reference/candidates; ownership and selected-card scope; confirm search first |
| Evidence and policy | Relevant policy ID/version/clauses; unsupported conclusions withheld |
| Routing | Expected route and reason codes; required review cannot be closed through satisfaction |
| Action execution | Explicit valid confirmation, permission, one case/action, safe replay and reconciliation |
| Communication | No case success without committed evidence; urgent guidance when required |
| Handoff | Confirmed queue entry with missing information and attempted actions |

A correct route alone is insufficient: each applicable component assertion must
also pass. The suite checks provenance and selected dangerous positive claims;
it is not a general semantic-entailment checker. Streamlit rendering, session
expiry and staff access have separate regression tests.

Four explicit counterfactual groups preserve irrelevant details while varying
wording, authorisation, cancellation date or search amount. Expected changes
include mandatory-review controls, evidence-conflict handling and candidate sets,
even when the broad route remains unchanged. `summary.json` records the expected
and observed controls for each member.

## Cost framework

`evaluation/costs.json` versions illustrative relative engineering costs:

| Error | Cost |
|---|---:|
| Unsupported action, cross-account selection, harness crash | 1,000 |
| Missed mandatory review/urgent guidance, false success claim | 500 |
| Unsupported policy conclusion, wrong transaction, duplicate case | 200 |
| Wrong route | 50 |
| Unnecessary escalation | 20 |
| Wrong reason code or other component failure | 10 |
| Unnecessary clarification | 5 |

Each category is charged once per case; categories can overlap. These weights
express review priorities, not financial loss estimates. Critical errors are
reported separately so aggregate cost or route accuracy cannot hide them.
Grader tests deliberately inject unsafe observations to check that failures
produce nonzero costs, including when the route itself is correct.

## Failures preserved and improvements

The [original failed outputs](data/workflow_evaluation/before_fixes/failed_outputs.json)
are retained alongside the initial cases and manifest. Initially 44/47 journeys
passed, with two critical misses and weighted cost 1,070. Route accuracy alone
was 46/47 (97.9%), obscuring one mandatory-review failure.

1. Uncertain authorisation reached a human-review route but still allowed the
   satisfaction closure. `AUTHORISATION_UNCLEAR` now requires specialist review.
2. A customer cancellation date contradicted the verified merchant request date
   without mandatory review. The controller now preserves both sources and
   records `MATERIAL_EVIDENCE_CONFLICT`.
3. Tool-failure handoff lacked explicit missing-information and attempted-action
   sections. Saved handoff packages now include both and the interrupted step.

After these changes the same 47 reference journeys pass: zero observed critical
misses, unsupported actions or false success claims; weighted cost zero. The
before/after case fingerprint is unchanged, so expectations were not relaxed to
fit the fixes. The full regression suite contains 204 passing tests.

## Limits and next evidence needed

These results demonstrate the tested synthetic behaviours only. They do not
measure live small-model extraction quality, real fraud prevalence, production
bank integration or independently verified eligibility decisions. Faults are
controlled adapters, not distributed-system chaos tests. Policies are fictional
administrator-controlled assets. Repeated templates and fixed examples limit
generalisation; zero observed errors is not a production safety guarantee.

Next, independently author unseen journeys and terminal labels, evaluate live
extraction on withheld varied statements, expand contradiction and policy-boundary
coverage, and validate real identity, permissions and bank-tool contracts.

Live Ollama probes and simulator integration contract results are now separately
documented in [LIVE_VALIDATION.md](LIVE_VALIDATION.md). The 47-case workflow suite
remains offline; its results must not be presented as live model accuracy or
real-bank integration evidence.
