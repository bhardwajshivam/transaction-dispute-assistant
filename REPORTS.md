# Reports and current validation status

Improvement steps 1–5 are implemented. Expanded evaluation (step 6) and final
documentation/clean-clone release verification (step 7) remain pending. A report
describes its recorded source/configuration; older reports are historical, not
evidence that every current change has been re-evaluated.

| Evidence | Report | Status and limits |
|---|---|---|
| Frozen baseline | [Baseline manifest](evaluation_baselines/2026-10-21-step-1/manifest.json) | Commit 84e5eee; includes historical metrics and sanitised observed merchant/date failure |
| Data quality and leakage | [Consolidated report](data/data_quality/REPORT.md) | Surface-token/template diagnostics; shared families and external label review remain limitations |
| Revised live extraction | [Before/after measurement](data/live_extraction_evaluation/prompt_v2/REPORT.md) | Model/parser/combined results separate; small development probes, one final generation-limit fallback |
| Workflow and handoff | [Contract results](data/workflow_controls/report.json) | Nine focused checks at the recorded source; not a representative usability study or formal verification |
| Privacy and operations | [Validation results](data/privacy_operations/report.json) | 22 synthetic checks; not exhaustive PII detection or production certification |
| End-to-end workflow | [Historical report](data/workflow_evaluation/latest/REPORT.md) | 47 constructed cases at recorded source; refresh/expansion scheduled in step 6 |
| Original workflow failures | [Preserved failures](data/workflow_evaluation/before_fixes/failed_outputs.json) | Before-fix outputs, retained unchanged |
| Required demonstrations | [Journey guide](DEMO_JOURNEYS.md) | Eight stored demonstrations; refresh/current LLM journey scheduled in step 6 |
| Activity, clustering and policy | [Evaluation guide](EVALUATION.md), [activity](ACTIVITY_DATA.md), [clustering](CLUSTERING.md), [live/integration guide](LIVE_VALIDATION.md) | Separate synthetic conformance and simulator evidence; no real-bank validation |
| Prior clean-directory verification | [Verification record](SUBMISSION_VERIFICATION.json) | Historical installation/archive evidence; final clean-clone check for this revision remains pending |

The step-5 source passed **240 offline regression tests**. This is distinct from
live model quality: model field recall was 37.9% on the original 14 probes and
51.7% on 12 authored robustness probes. Combined exact matches were 14/14 and
11/12; parser support accounts for much of this result. See raw failed outputs
and source fingerprints in the linked report directories.

## Reproduce completed-step checks

```sh
python -m unittest discover -s tests -q
python scripts/audit_data_quality.py
python scripts/validate_workflow_controls.py
python scripts/validate_privacy_operations.py
```

Live inference requires local Ollama and the installed model; use the separate
commands and exit-code explanation in the extraction report. Use a new output
directory when comparing results so historical evidence is preserved.

The submission builder includes these reports and the frozen baseline. Generated
ZIP files remain local under ignored `dist/`; GitHub contains their reproducible
source inputs, not working databases, encryption keys or concern histories.
