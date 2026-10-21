# Submission improvement checklist

Step 1 freezes the implementation at commit `84e5eee` before further changes.
The baseline is in `evaluation_baselines/2026-10-21-step-1/`. Existing reports
are historical evidence, not freshly reproduced results for that commit.
No runtime database, customer history, keys or local machine metadata is copied.

## Sequence and acceptance gates

1. **Baseline — complete:** source/config fingerprints, fresh offline test result,
   historical reports and a sanitised observed failure are preserved.
2. **Data quality — pending:** reproducible leakage/similarity analysis, independent
   cases with expectations frozen before fixes, consolidated quality report.
3. **Extraction — pending:** versioned prompt/schema/model traces; fresh live
   model-only, parser-only and combined measurements, including failures.
4. **Workflow/handoff — pending:** explicit transition matrix and invalid/repeated/
   interrupted/reopened journey checks; representative continuation test.
5. **Privacy/visibility — pending:** failure-path logging/export checks and minimised
   operational counters, without raw customer statements in metrics.
6. **Evaluation — pending:** rerun component/workflow/demonstration suites and
   expand retrieval, counterfactual, attack and unsupported-claim checks.
7. **Release — pending:** documentation/reflection aligned with measured behaviour,
   change/rollback process, clean-clone reproduction, commit and push.

## Requirements to evidence

“Partial” means relevant evidence exists but the agreed improvement is unfinished.
Paths below identify the current implementation/report and intended evidence.

| # | Requirement | Current evidence | Remaining work / acceptance | Stage |
|---|---|---|---|---|
| 1 | Wording leakage | DATASET.md acknowledges gap | Token-label analysis and wording-only baseline, with limits | 2 |
| 2 | Split/template similarity | Activity generator checks exact input/customer overlap | Near-duplicate statement/template analysis; intentional pairs identified | 2 |
| 3 | Consolidated quality report | data/quality_report.json; data/activity_corpus/quality_report.json | Reproducible combined balance, missingness, consistency, duplicate and boundary report | 2 |
| 4 | Revised live extraction | Historical data/live_extraction_evaluation | New prompt evaluated; model/parser/combined metrics separate | 3 |
| 5 | Current end-to-end results | data/workflow_evaluation/latest | Re-run and cover merchant-independent and unknown-currency lookup | 6 |
| 6 | Retrieval relevance | tests/test_policy_service.py; policy evaluation | Measure required/irrelevant/missing clauses separately from attribution | 6 |
| 7 | Counterfactual expansion | evaluation/scenarios.py; activity pairs | Currency, merchant invariance, policy dates, availability, permissions | 6 |
| 8 | Adversarial language | Existing injection/fault scenarios | Negation, corrections, uncertainty, varied wording and hostile tool content | 3, 6 |
| 9 | Independent cases | Existing hand-authored shared-family suites | Independently reviewed expectations and unseen journeys; otherwise disclose inability to establish independence | 2 |
| 10 | Unsupported claims | evaluation/scoring.py selected assertions | Broader fact/policy provenance checks for explanations and handoffs | 6 |
| 11 | Recent failure preservation | Step-1 observed_failure.json; intake regression | Preserve fresh raw synthetic model failures where available, then compare after fixes | 1, 3 |
| 12 | Demonstrations | DEMO_JOURNEYS.md; eight stored demonstrations | Refresh and add current LLM intake/fallback evidence | 6 |
| 13 | Handoff continuation | concerns.py; representative UI tests | Colleague can identify next step from package and later updates | 4 |
| 14 | Logging privacy | SECURITY.md; privacy/report metadata tests | Exercise exception, model/tool failure, debug and export paths | 5 |
| 15 | Transition coverage | conversation.py; workflow.py; command tests | Transition table plus invalid, repeated, interrupted and reopen cases | 4 |
| 16 | Extraction versions | Model tag and trace provenance exist | Stable prompt/schema identifiers and model identity recorded | 3 |
| 17 | Change management | Source/report manifests exist | Required checks, saved-state compatibility and rollback process | 7 |
| 18 | Observability | Per-concern traces and command ledgers | Minimized failure/fallback/policy/escalation/action summary | 5 |
| 19 | Honest current reflection | REFLECTION.md; architecture docs | Remove stale default claims; include observed failure, new results and unresolved risks | 7 |

## Guardrails for subsequent work

- Never overwrite historical failures or relabel expected outcomes to pass a fix.
- Keep synthetic conformance, live extraction and real-bank validation distinct.
- Do not call agent-generated cases independently adjudicated bank labels.
- Do not reset working databases or commit keys, customer histories or model blobs.
- Preserve confirmation, ownership, policy gates, permission and action idempotency.
- Use fresh temporary databases for evaluation; record the tested commit and hashes.
