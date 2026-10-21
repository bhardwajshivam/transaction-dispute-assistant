# Synthetic dataset v1

For the newer, separate activity-history corpus (2,225 transactions, 24 cards and
156 customer-disjoint scenario variants), see [ACTIVITY_DATA.md](ACTIVITY_DATA.md).
The original fixtures documented below remain available for regression examples.

All records are fictional. Generator: `scripts/generate_data.py`. Snapshot: 20 October 2026. No Faker, network access or LLM required.

## Functions and outputs

| Function | Output | Contents |
|---|---|---|
| `generate_accounts` | runtime/accounts.json | Synthetic customers, accounts, cards, authorised customer IDs |
| `generate_merchants` | runtime/merchants.json | Five curated descriptor/trading-name mappings |
| `generate_transactions` | runtime/transactions.json | Account histories, amounts in minor units, dates, channels, statuses and order links |
| `generate_supporting_records` | runtime/receipts.json | Agreed amounts, currency and order references |
| same function | runtime/cancellations.json | Request/effective dates, cancellation methods and confirmations |
| same function | runtime/refunds.json | Processed refunds linked to original payments and destination cards |
| same function | runtime/credits.json | Posted credits linked to refund and account |
| `generate_policies` | runtime/policies.json | Explicitly fictional intake policy and three routing rules |
| `generate_scenarios` | development/ and evaluation/ | Customer assertions and separately stored expected initial questions |
| initial empty collections | runtime/cases.json, actions.json, audit_events.json | Empty initial operational state, not fabricated completed actions |
| `generate_tool_fixtures` | testing/tool_responses.json | Starter success/error status fixtures, not executable API contracts |
| `validate` | quality_report.json | Reference checks, amount/date checks, status counts and duplicate-looking groups |
| `generate` | manifest.json | Seed, configuration, generator version and file checksums |

## Sampling versus construction

A local seeded PRNG samples merchants uniformly, transaction ages uniformly from 1–90 days, and non-subscription GBP amounts uniformly from 250–25,000 minor units. Streamwave amounts are fixed at 1,299 minor units. Payments older than two days are posted; newer sampled payments may be pending. These are transparent demo assumptions, not empirically calibrated distributions.

The first five account-A-001 transactions are constructed anchors to preserve the interactive examples, including a duplicate-looking pair and pending payment. Recurring indicators follow merchant identity. Every transaction receives a matching receipt; recurring transactions receive a cancellation before purchase. Every seventh posted transaction receives a fully processed refund and a matching credit. These deliberately simple supporting-record patterns are unsuitable for evaluating cancellation/refund routing and must be diversified before that evaluation.

Development and evaluation each contain four hand-constructed initial-question scenarios with different wording and disjoint customer transactions. They share scenario families; this is not a held-out generalisation benchmark. Expected outcomes are never read by runtime code.

## Initial quality report and limitations

Default run: 90 payments, 88 posted, 2 pending, 18 recurring, one duplicate-looking group, two expected missing posting dates, zero validation errors. Counts are reproducible for seed 42.

Design corrections: money is stored as integer minor units; pending records have null posting dates; account filtering prevents the demo loader displaying another account's payments. Validation tests deliberately introduce a broken account reference and verify detection. This original fixture report is not a broad empirical defect-discovery study; later evidence-driven corrections are documented in ACTIVITY_DATA.md, EVALUATION.md and LIVE_VALIDATION.md.

Current coverage is distributed across three complementary suites:

| Suite | What it establishes | Limit |
|---|---|---|
| Original fixtures (this document) | Stable interactive anchors and initial-question checks | Simple supporting evidence; not terminal routing labels |
| [Activity corpus](ACTIVITY_DATA.md) | Richer recurrence, missingness, near-neighbour analysis, customer-disjoint splits and data-quality defects/corrections | Shared families and simplified refund/cancellation support |
| [Workflow evaluation](EVALUATION.md) | 47 constructed terminal/intermediate behaviours including contradictions, stale/conflicting policy, malformed data, counterfactuals and tool/model/action failures | Hand-authored expectations, not independently adjudicated labels |

Independently reviewed terminal labels, family-held-out generalisation, systematic
superficial-token leakage analysis and richer terminal cancellation/refund
populations remain outstanding. The initial-question reference set is not final
routing evaluation. Runtime code never reads expected labels.

The evidence controller retrieves scoped policy and supporting records. The app
queries only accounts accessible to the fixed demo customer and the selected
card, rather than hard-coding a single account. This is still demo identity,
not production authentication. Fresh generation uses GBP fixtures (plus the
optional INR anchor); the README explicitly relabels the loaded demo database to
INR without changing nominal amounts. Generation and relabelling are distinct;
no FX conversion is claimed.

## SQLite import

`scripts/load_database.py` imports runtime fixtures into typed relational tables and preserves evidence payloads as JSON text. The importer excludes development/evaluation labels and testing fixtures. See README for import, reset and query commands. JSON generation and SQLite import are separate reproducible steps.

Generator v1.1 adds optional `--cards-per-customer` (default 1). Extra cards use separate accounts with the same synthetic customer and access membership. History size is per card; existing base account/card references remain stable. This simplifies the prototype and does not model multiple cards on a single account.

Optional INR example: `python scripts/generate_data.py --include-inr-example` includes TX-999001, INR 200.00, dated 19-10-2026 on CARD-001. This is an explicit synthetic currency fixture; FX conversion to account currency is not modelled. The recommended setup includes it; the submission does not ship a working database.
