# Richer synthetic activity corpus

This corpus strengthens transaction-history evidence and supports the implemented
optional k-means distance assessment described in CLUSTERING.md. It is separate from the original interactive fixtures and does
not replace `data/disputes.sqlite` or its concern histories.

## Reproduce and launch

```sh
source .venv/bin/activate
python scripts/generate_activity_data.py
python scripts/load_database.py --source data/activity_corpus/runtime --database data/activity.sqlite
python scripts/evaluate_activity_corpus.py --split development
python scripts/evaluate_activity_corpus.py --split evaluation
CONCERNS_DATABASE="$PWD/data/activity.sqlite" python -m streamlit run app.py
```

The submission excludes working databases. Create `data/activity.sqlite` using
the loader above. On a later run, skip the loader when it exists; do not use `--replace` on a database containing histories you
want to keep. To regenerate and import a new experiment, select a new database
path. Generation refuses an output directory containing operational SQLite
files. No new Python dependencies, network access or LLM are required.

Default seed: **20261021**; snapshot: **20 October 2026**. Generator controls:
`--seed`, `--customers` (even, at least four), `--history-size` (at least 80) and
`--output`. Defaults are 12 customers with two cards each and about 120 sampled
purchases per primary card. Transaction references are random opaque six-digit
IDs drawn without replacement; their sequence does not encode scenario labels.

## What was strengthened

| Component | Generation assumption |
|---|---|
| Customer variation | Lower, mixed and higher nominal spending scales, each with seeded individual variation |
| Card context | Two separate card-linked accounts per customer; secondary cards have about 35% of primary-card activity |
| Amounts | Category-specific lognormal distributions with a 0.48 log-scale standard deviation and positive minor-unit floors |
| Time | 180-day purchase window; coffee/transport favour weekdays, groceries/dining/travel favour weekends; morning coffee timestamps |
| Posting | Sampled 0/1/2/5-day lags with probabilities 50/32/15/3%; posting beyond the snapshot stays pending |
| Recurrence | Six monthly subscription payments on the third of each month, May–October, with stable amount per card |
| Merchant ambiguity | 14 merchants, including similar Express trading names and unfamiliar descriptors; category/MCC and domestic merchant country |
| Currency | GBP and INR histories with explicit nominal scales; no FX conversion or currency-normalised score is implied |
| Legitimate exceptions | Planned large purchases with matching receipts; matching charges for separate orders |
| Review candidates | Matching merchant/amount/currency charges sharing an order reference, without asserting confirmed duplicate processing |
| Missingness | About 20% of receipts and 3.5% of sampled order references omitted; pending posting fields are null |

These are transparent constructed assumptions, not estimates fitted to actual
banking data. Large-purchase and repeated-order anchors are constructed by hand;
background histories are sampled. Anchor facts are protected from subsequent
random missingness. Receipts for constructed legitimate large purchases always
exist and agree with the purchase. The supporting cancellation/refund generator
remains simplified: recurring records have pre-purchase cancellations, and each
selected refund has a matching credit. This corpus does not claim to strengthen
terminal cancellation/refund evaluation.

## Schema and separation

`runtime/` uses the existing importer-compatible accounts, merchants,
transactions, receipts, cancellations, refunds, credits and policy schemas.
Case/action/audit collections start empty. Additional transaction fields are
`occurred_at` and `posted_at` (UTC ISO timestamps), `merchant_country` and
`merchant_category` (MCC). The importer retains them in `evidence_json`; it does
not add timestamp columns or enable velocity rules. Existing activity assessment
still conservatively uses prior dates and excludes same-day payments.

`design/profiles.json` records sampling parameters.
`design/runtime_exceptions.json` records intended exceptional-case behaviour.
Neither is imported or exposed as a runtime predictor feature.

`development/activity_cases.json` and `evaluation/activity_cases.json` each
contain **78 cases**, from **six disjoint customers** per split. Each includes a
target transaction, historical evidence, construction family/variant, expected
activity status, signal codes and review route, rationale and separate
constructed authorisation truth. Only transaction/history facts are passed to
the assessor. Expected labels, profiles, construction names and authorisation
truth never enter runtime tables or model inputs.

Pairs change amount at the median-based threshold, order reference or evidence
availability date. Cases also include nine-record histories, invalid historical
amounts, legitimate outliers and ordinary-looking unauthorised payments. The
last two illustrate that authorisation cannot be inferred from patterns alone.
An identical observed input can have different unobserved authorisation truth;
those deliberate repeated inputs are counted and documented rather than
presented as independent samples.

`testing/history_tool_responses.json` documents unavailable, forbidden and
malformed states. Malformed input values live in evaluation cases, where they
can exercise abstention without weakening runtime SQL constraints.

The manifest hashes generator-owned source files. Evaluator results are separate
and cannot change regeneration checksums. Generation is deterministic for the
same seed/configuration. Case families deliberately recur across customer-disjoint
splits; this is a rule-conformance suite, **not a family-held-out benchmark**.
No learning or threshold tuning has been performed on either split.

## Quality and evaluation results

Default generation produces:

| Check | Result |
|---|---:|
| Transactions / customers / cards | 2,225 / 12 / 24 |
| GBP / INR transactions | 1,454 / 771 |
| Missing receipts | 417 |
| Missing order references | 79 |
| Posting lags of at least three days | 48 |
| Pending transactions with null posting fields | 2 |
| Same-order matching pairs within three days | 24 |
| Distinct-order matching pairs within three days | 121 |
| Unexpected schema/reference/date errors | 0 |
| Customer overlap and normalised exact-input overlap across splits | 0 |

`quality_report.json` records field missingness, counts by card/currency/channel,
route/family/truth balance, duplicate-looking groups and near-neighbour pairs.
Normalised duplicate detection removes opaque IDs, account identity and
incidental timestamp differences while preserving meaningful order-reference
relationships, amounts and dates. Cross-split overlap fails generation.

Quality checks verify references, card/account consistency, amount and posting
constraints, timestamp/date alignment and receipt currency. Tests introduce
scope and timestamp defects and verify rejection. During implementation,
missingness was found capable of removing receipts/order references supporting
the constructed anchors; those anchors are now protected. An accidentally
repeated positive control across two families was made temporally distinct.

Each split contains **48 no-additional-route** and **30 review-recommendation**
cases. The unchanged deterministic assessor matches **78/78 expected outcomes
in each split**. Results are in `results/development_report.json` and
`results/evaluation_report.json`. These include six authorised transactions
that are flagged and six unauthorised transactions that are not flagged per
split. That result is intentional: it exposes why these signals must not be
treated as fraud probabilities. The other 66 cases have unknown authorisation.

At the activity-corpus milestone, 116 regression tests passed, including seven
new corpus tests. The current complete suite passes 207 tests. Matching synthetic expected routes is not
evidence of real-world fraud detection performance.

## What this enables next

This is a better basis for testing historical features, scaling choices and
anomaly explanations. Clustering is now implemented with a feature contract and earlier training/later
calibration windows; see CLUSTERING.md. Evaluate on disjoint customers
and a separate temporal/family challenge set. Bank-approved, independently
labelled outcomes are still needed to calibrate any probability of fraud.
Device/location signals, overseas behaviour, FX, real prevalence and realistic
terminal cancellation/refund outcomes remain outside this corpus.
