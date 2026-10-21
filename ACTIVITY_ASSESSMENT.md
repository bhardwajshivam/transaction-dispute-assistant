# Deterministic unusual-activity assessment

The first pass assesses amount anomalies and earlier matching merchant charges.
It runs locally after evidence gathering, independently rechecks transaction and
card access, and uses no model, customer wording, scenario IDs or expected labels.
No new dependency or database reset is required.

## Boundaries and authority

`activity.assess` reads a consistent, read-only snapshot of the selected card's
transactions, scoped by `account_access`. Database records establish amounts,
merchant IDs, dates and order references. `activity.evaluate` calculates
patterns; its results are **signals**, not verified fraud or eligibility facts.
`activity.review_decision` is a separate deterministic review table. It can
recommend specialist review, but cannot create cases, block cards, approve a
refund or schedule a handoff. Those actions retain their existing confirmation
and permission boundaries.

`policies/activity_rules_v1.json` contains the versioned thresholds and separate
review-rule version. The present rules are prototype assumptions, not bank policy
or validated fraud thresholds:

| Check | Required evidence | Signal / behaviour |
|---|---|---|
| Amount | At least 10 earlier posted purchases on this card, in the same currency, within 90 days | Amount strictly greater than 3× the median AND at least 5,000 minor units recommends review |
| Repeated charge | Earlier posted purchase within 3 calendar days, same merchant ID, amount and currency | Same order reference recommends review; missing order reference recommends review with uncertainty |
| Distinct orders | Same matching charge pattern, different nonempty order references | Context only; does not independently recommend review or establish that both charges are legitimate |
| Missing/malformed evidence | Missing history, malformed values, unavailable database/rules or failed ownership check | Partial/insufficient/unavailable/forbidden result, never an assurance that the payment is safe |

These data use two-decimal GBP/INR amounts; no currency conversion occurs. The
5,000-minor-unit floor is deliberately simple and uncalibrated across currencies.
Production needs institution-approved currency-specific thresholds. Median
calculation uses exact integer/fraction arithmetic at the decision boundary.
The median is an explainable starting point; merchant-specific baselines and
learned anomaly models add calibration/data requirements beyond this first pass.

Only purchase dates strictly before the target date are eligible. Posting must
also precede that date, preventing delayed presentment from leaking future bank
knowledge into the historical baseline. The 90-day and 3-day lower boundaries
are inclusive. All same-day activity is excluded because the data cannot show
which payment happened first. This intentionally misses same-day duplicates;
the ordinary dispute questionnaire still supports those complaints. No reference
sort order is treated as a timestamp. Pending payments, older records, other
cards and other currencies do not enter the baseline.

## Recorded output and workflow

The result includes overall and per-check statuses, structured reason codes,
counts, baseline amount, matching references, window/currency, versioned rule
snapshot, limitations and a reproducible evidence ID. A compact historical fact
snapshot supports review of the calculation. `ASSESSED` means both implemented
checks completed; `PARTIAL` means only some checks completed. Even an assessed
result with no signals says nothing definitive about fraud.

A separate review recommendation records its own version and applicable reason
codes. Qualifying signals add sticky `UNUSUAL_ACTIVITY_REVIEW` to the existing
workflow. Customer satisfaction cannot clear it. Missing activity data alone
does not establish a fraud finding or automatically override other routing.

The customer sees **Transaction activity checks** with cautious template text.
Concern state, frozen handoff packages and case snapshots retain the structured
assessment under existing encryption. Staff see it in their authenticated
workspace; text summaries include it too. Customer exports include only status,
version and signal codes, excluding the historical record set. The activity
snapshot is not sent to Ollama. Existing saved concerns gain this assessment
when evidence gathering next runs; reopening alone does not rewrite historical
case or handoff snapshots.

## Reproduce and evaluate

```sh
python scripts/evaluate_activity.py
python -m unittest tests.test_activity -v
python -m unittest discover -s tests -q
```

The evaluator writes `data/activity_evaluation/cases.json` and `report.json`.
These are separate from `data/runtime`; the app never reads evaluation labels.
All 16 scenarios are constructed numeric counterfactuals, not sampled claims
about banking prevalence. Pairs vary amount by one minor unit, prior spending
level, available history count and order reference. Additional cases cover
currency isolation, same-day ambiguity, future activity, delayed presentment,
malformed history, pending targets and absent history. The report includes route
and status balance, counterfactual groups, duplicate checks and deliberate
defects. A duplicate input case was found and replaced with a distinct baseline
boundary pair. Superficial customer wording cannot determine these outcomes
because no wording is an assessor input.

On 21 October 2026, all **16/16 constructed scenarios** matched their expected
statuses, signal codes and routes, with **0 false review flags** and **0 missed
constructed review flags**. This is rule-conformance evidence, not an independent
fraud-detection accuracy estimate. The regression suite passes **109 tests**,
including 11 new activity tests. Tests also check ownership, malformed config,
read failures, duplicate history rows, fractional median boundaries, reproducible
artifacts and that a positive signal creates no case/action.

Remaining limitations include thin and unrepresentative histories, merchant-ID
quality, same-day blind spots, legitimate high-value purchases, missing order
references, lack of device/location evidence and the absence of independently
labelled fraud outcomes. Add timestamps and realistic labelled histories before
adding velocity checks or claiming detection performance.
