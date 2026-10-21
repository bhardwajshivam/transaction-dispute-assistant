# Transaction Dispute Assistant

Streamlit guided chat, deterministic routing and SQLite concern history, with optional bounded local Ollama evidence gathering. All account and transaction records are synthetic. No real bank actions, refund adjudication or human connection occurs. Card protection is simulated and requires separate explicit confirmation.

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for detailed component, customer journey, case execution/recovery and evaluation graphs rendered directly on GitHub.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the capability map, authority boundaries, alternatives, failure controls and end-to-end flow.

See [REFLECTION.md](REFLECTION.md) for the weakest component, unresolved risks, evaluation-driven changes, next priorities and AI-assisted development disclosure. It includes the author-confirmed decision to prefer deterministic techniques first.

## Usage guide

For step-by-step installation, customer journeys, representative access, exports, simulated cases, optional Ollama configuration and troubleshooting, see [USER_GUIDE.md](USER_GUIDE.md).

## Setup

```sh
git clone https://github.com/bhardwajshivam/transaction-dispute-assistant.git
cd transaction-dispute-assistant
```

Never share personal tokens or credentials in the repository. No API key is required for the default application.

Python 3.10 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/generate_data.py --seed 42 --cards-per-customer 2 --include-inr-example
python scripts/load_database.py
python -m streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501). The setup generates two cards per customer and all account, transaction, receipt, refund and credit amounts directly in INR. The optional example adds a fixed INR 200 transaction. No currency conversion or relabelling step is required; both generated JSON and the imported database use INR.

No working database, encryption key or saved concern history is included in the submission archive. If the database already exists, skip generation/loading and launch the app to preserve saved concerns. Updated generation does not rewrite an existing database. To deliberately reset all demo data, including saved concern histories and handoff requests, stop the app, regenerate the fixtures with the command above, then run `python scripts/load_database.py --replace`. No reset is needed when updating application code; concern schema migrations are additive.

## LLM extraction and deterministic workflow

The default chat uses local **Ollama `smollm2:135m` to suggest details from the customer's description**. It does not decide which transaction is disputed, apply policy, authorise actions or generate the outcome explanation.

| Capability | Technique and control |
|---|---|
| Understand the description | Local LLM suggests exact source spans for dates, charged/expected/original/refund amounts, currencies and references. PII is screened/redacted before transport. |
| Validate reported details | Deterministic schema, source-span, date, amount and role checks; parser support and guided questions handle missing or unusable suggestions. Details remain unverified customer assertions. |
| Find the transaction | Customer confirms criteria; SQL verifies account/card scope and filters by date and actual charged amount (original purchase for refunds), or exact reference. Merchant names never filter. Known currency filters exactly; absent currency matches across currencies without FX conversion. Results show recorded currencies and require customer selection. |
| Gather evidence | A bounded deterministic controller fills evidence gaps. An optional LLM may suggest allowlisted read-only lookups; the controller validates every proposal. |
| Assess and route | Versioned policy, evidence gates and review rules are deterministic. Activity rules and clustering produce advisory signals only. |
| Explain and act | Templates use verified evidence and recorded reasons. Card protection and case creation require explicit confirmation, permissions, idempotency and audit. All bank operations are simulated. |

### Default: local extraction, deterministic evidence gathering

Install Ollama separately, start its app (or `ollama serve`), then:

```sh
ollama pull smollm2:135m
export CONCERN_EXTRACTION_MODE=ollama
export EVIDENCE_PROPOSER_MODE=deterministic
python -m streamlit run app.py
```

No API key or Python model SDK is required. The extractor uses `smollm2:135m`; `OLLAMA_MODEL` configures only the optional evidence proposer. `.env.example` is documentation and is not automatically loaded. If Ollama is unavailable or returns invalid output, the parser and guided questions keep the journey usable. Merchant/date misclassification is explicitly regression-tested.

### Fully deterministic mode

```sh
export CONCERN_EXTRACTION_MODE=deterministic
export EVIDENCE_PROPOSER_MODE=deterministic
python -m streamlit run app.py
```

This mode makes no LLM calls. To enable the optional read-only evidence proposer separately, set `EVIDENCE_PROPOSER_MODE=ollama` and `OLLAMA_MODEL=smollm2:135m`. Neither switch grants action or policy authority. See [LLM_INTEGRATION.md](LLM_INTEGRATION.md).

**Model quality limitation:** the previous extraction prompt achieved 0% validated model field recall on 14 fixed live probes. Fresh revised-prompt measurements show 37.9% model field recall on the original 14 probes and 51.7% on 12 developer-authored robustness probes. Combined exact matches are 14/14 and 11/12; one robustness response hit the generation limit and required fallback. Parser success does not establish model reliability. See the [current extraction report](data/live_extraction_evaluation/prompt_v2/REPORT.md). Historical failed outputs remain documented in [LIVE_VALIDATION.md](LIVE_VALIDATION.md).

## Journeys

- Secure or block a card: select the card, choose temporary lock or permanent block, then explicitly confirm the simulated action. No transaction or detailed reason is required first. This can interrupt an existing concern; see [CARD_PROTECTION.md](CARD_PROTECTION.md).

- Unrecognised payment: select a transaction, review merchant details and clarify authorisation.
- Charged after cancellation: gather type, dates, method and confirmation details.
- Multiple charges: confirm search details, select the suspected duplicate payment, then clarify purchase count and receipts.
- Wrong amount: confirm actual charged amount/date and currency when known, select the payment, then clarify the agreed amount, receipt and adjustments.
- Missing refund: gather merchant statements and check linked refund/credit records.
- Different issue: describe the concern without selecting a transaction; unsupported requests can be handed off with confirmation.

For exact reproducible interactions, see [DEMO_JOURNEYS.md](DEMO_JOURNEYS.md). Similar payments TX-1003/TX-1004 exercise ambiguity; TX-1005 is pending. The snapshot date is fixed to 20 October 2026.

Quick replies and transaction selection appear inside the latest assistant chat message; earlier messages remain as conversation history. At the opening, typing is disabled until an issue option and card are chosen. Every complaint option first asks the customer to select an accessible demo card, then asks “Can you please elaborate your concern?”; a non-empty description is required. The app extracts reported details, asks only for missing required search fields, and confirms the criteria before fetching transactions. The description is saved as a customer assertion. Questions are asked one at a time. Free text is retained as customer assertions, not silently converted into verified facts. Supported dates and amounts are parsed and validated; extracted details remain unverified assertions. Missing references do not prove an event never happened.

## Evidence and policy

After customer selection, the bounded controller verifies access and gathers merchant, policy and branch-specific records via read-only, parameterised queries. An eight-proposal budget, allowlisted tools, reference validation and stopping conditions constrain the proposer. Evidence IDs, timestamps and proposal traces are visible in an expander and persisted. Collected evidence is a snapshot; reopening does not automatically refresh it.

Transaction intake uses validated fictional DEMO-INTAKE v1.1 rules; general information uses the approved versioned corpus, and case recording uses DEMO-CASE-INTAKE v1.1. They share a policy clock, attribution schema and conclusion gates. These support bounded intake outcomes, not real bank eligibility, fraud adjudication or refund approval. See [POLICY_GATING.md](POLICY_GATING.md).

## Persistent concerns and handoff

The first reply creates a concern; further replies append timestamped notes. Open a prior concern from the sidebar to resume it. New conversations never automatically merge into earlier concerns. Updates use revision checks; conflicting sessions must reopen. Customer identity is fixed demo identity, not production authentication.

Required specialist review, customer satisfaction and handoff status are independent. Reported unauthorised payments, card risk, evidence-verification failures and policy conflicts retain required review even if assistance is declined. Ordinary concerns receive a resolution question and optional assistance. Only explicit confirmation queues a simulated handoff. The queue and concern update commit atomically, with one queue entry per concern. Later updates remain in history but do not automatically replace the queued summary.

Summaries distinguish customer assertions from synthetic bank facts and include policy references, reasons and traces. No real representative is contacted. Use **Download history** at the top right to export an allowlisted, redacted history as JSON; internal tool payloads and traces are excluded. It is disabled until a concern is saved; no history/handoff-summary panel is shown below the chat. Do not enter real personal data. Prototype redaction, encrypted concern storage, staff gating and explicit retention tools are implemented; bank authentication and production security remain required.

## Reproducible datasets

```sh
python scripts/generate_data.py --seed 42 --customers 3 --transactions-per-customer 30
```

The same arguments reproduce JSON and checksums. Runtime data, scenario labels and failure fixtures are separated. Load JSON into `data/disputes.sqlite` before running; only account-authorised records are queried by the app. Generated tables include customers/accounts, transactions, merchants, receipts, cancellations, refunds/credits and fictional policies. [DATASET.md](DATASET.md) records assumptions and remaining coverage gaps.

## Main modules

| File | Responsibility |
|---|---|
| `app.py` | Streamlit interface |
| `conversation.py` | Question graph and routing suggestions |
| `review.py` | Sticky required-review rules |
| `concerns.py` | Concern history, revision checks and simulated handoff queue |
| `domain.py` | Account-scoped transaction loading |
| `evidence_agent.py` | Read-only tools and bounded validation loop |
| `model_proposer.py` | Proposal contract and fallback |
| `ollama_backend.py` | Local structured generation transport |
| `intake.py` | Must-know checklists, date/money validation and confirmation |
| `concern_extraction.py` | Source-grounded local 135M extraction and conservative parser fallback |
| `orchestration.py` | Deterministic/local-model mode integration |
| `scripts/` | Data generation and constrained SQLite import |

## Tests and limits

```sh
python -m unittest discover -s tests -v
```

Current result: **240 tests pass**, including 18 shared-policy-gating tests, 17 versioned-policy/journey tests, 15 clustering tests, 22 focused case-service tests, 11 activity-assessment tests and 7 richer-corpus tests. Tests are offline functional checks, not proof of banking readiness or model reliability. Confirmed simulated case creation, idempotent retries and outcome reconciliation are now implemented; see [CASE_CREATION.md](CASE_CREATION.md) for controls, examples and evaluation. Major remaining work includes broader extraction coverage, richer contradictions/counterfactual datasets, independent terminal labels, complete eligibility policy execution, production bank adapters and independent evaluation on realistic bank data. Simulated tools and handoffs must not be presented as real operations.


## Card selection and scope

Opening flow: complaint option → select accessible card → elaborate concern → provide missing required fields → confirm search → select a matching payment on that card. Card choices and transaction search appear inside the assistant message. The database currently models one card per account; a customer can have multiple card-linked accounts. Demo card IDs are displayed rather than invented real card digits. New replies cannot select another customer's card; tools and concern storage reject transactions inconsistent with the selected card. Existing saved transactions infer their card from an access-checked database record on reopen.

The generator defaults to one card per customer; the recommended setup above explicitly generates two. To generate multiple cards for a fresh demo, use `python scripts/generate_data.py --cards-per-customer 2`. The legacy `--transactions-per-customer` option now controls history length per card when multiple cards are requested. Load into a new database using `--database`, or explicitly reset an expendable demo database using `--replace` (which deletes saved histories). Do not reset existing data simply to enable card selection.


## Confirmed transaction search

See [INTAKE_FLOW.md](INTAKE_FLOW.md) for the per-issue must-know list. Dates are requested as DD-MM-YYYY and displayed that way in confirmation (stored as ISO internally). Charged, expected, original-purchase and refund amounts are distinct. Only charged/original-purchase amounts can filter payments; merchant names are context only. Currency is optional: missing or ambiguous currency allows matching the nominal amount across currencies, with each result displaying its recorded currency. No FX conversion or currency inference is performed. `$` alone does not establish currency. The fixed demo snapshot rejects dates after 20-10-2026.

Descriptions are screened/redacted and sent to local `smollm2:135m` by default. Set `CONCERN_EXTRACTION_MODE=deterministic` to avoid model processing. The 14 historical live probes of the previous prompt exposed 0% validated model field recall; source-span rejection prevents the observed invented values from entering intake. This setting is separate from `EVIDENCE_PROPOSER_MODE`. See [LIVE_VALIDATION.md](LIVE_VALIDATION.md).

The fully deterministic mode requires no model or API key. In the default LLM extraction mode, incomplete/malformed output falls back; accepted spans must appear in the customer text and pass date/money/role checks. Extracted values remain unverified assertions. With `SHOW_INTERNAL_DEBUG=1`, the **Reported details and extraction checks** expander shows accepted/rejected fields and their parser/model provenance. These records persist with concern history and handoff packages.

Search requires **Confirm and search**. **Edit details** asks for a corrected description and invalidates the previous criteria. No-match and unavailable-service states are distinguished. Confirmation states when currency is unspecified and matching will span currencies; the app does not silently relax supplied criteria. **Change search details** and human assistance are offered when needed. An exact TX reference is an alternate search path; confirmation explicitly states that other reported details will be compared after selection. Older saved concerns without confirmed criteria are redirected to collect them before a new search.


## Representative workspace

Select **Workspace → Representative workspace** in the sidebar to inspect confirmed assistance requests. Each request shows the original handoff package (description, answers, selected transaction, evidence, policy/routing and traces), its conversation snapshot, and a separate Later updates tab. Download the frozen handoff JSON or latest concern history. Queued requests are read from `handoff_requests`; subsequent notes come from `concern_events`. The original package is never silently replaced.

Successful requests explain that, in a live bank, a representative would contact the registered mobile number shortly. The following sentence explicitly states that no callback is scheduled and no real representative is notified. No phone number is invented or displayed. Queue failure does not produce this message.

This is a local read-only representative demonstration for synthetic C-001 data. A configured staff token and customer scope are required; selecting the workspace alone does not grant access. Deploying real representative access requires a separate authenticated staff role and case-assignment permissions.


## PII protection

See [SECURITY.md](SECURITY.md) for implemented controls, staff-token setup, key backup, retention commands and limitations. Input is screened before model calls and persistence; detected authentication secrets are blocked and unnecessary identifiers redacted. Concern payloads are encrypted, staff views are gated, customer exports are minimised and internal debug panels are hidden by default. Existing demo concern records were migrated without resetting the database. Install updated dependencies and restart using `.venv`.

## Create a case

After a supported complaint reaches a review outcome, select **Open a dispute case** in the chat. Review the transaction and reported concern, then choose **Confirm and create dispute case**. The deterministic service rechecks ownership, permission, current facts and its versioned fictional intake policy before creating a simulated case. Duplicate requests reuse the same case. Unknown outcomes offer status lookup and retry using the same request. Representatives see cases and linked concerns in their existing authenticated workspace. This records a case for review; no real bank case, refund or card action is performed. Existing histories are preserved; no database reload is required.

## Unusual activity checks

The assistant now runs deterministic amount-anomaly and earlier matching-charge checks against verified, card-scoped history. A separate review table can recommend specialist review; signals never authorise a case, refund or card action. View the result under **Transaction activity checks**. Rules, evidence limits, reproduction commands and the 16-case counterfactual evaluation are documented in [ACTIVITY_ASSESSMENT.md](ACTIVITY_ASSESSMENT.md). No database reset or extra dependency is needed.

## Richer activity data

A separate seeded corpus now provides 2,225 transactions across 12 customers and 24 cards, realistic spending variation, monthly subscriptions, timestamps, delayed posting, legitimate anomalies and 156 constructed scenario variants. It is available in `data/activity_corpus` and can be imported into a separate `data/activity.sqlite`; working databases are excluded from the package. See [ACTIVITY_DATA.md](ACTIVITY_DATA.md) for generation, quality results, evaluation limits and the command to launch against this database.

## Clustering signal

A deterministic k-means component now reports a cluster-distance anomaly score from earlier, ownership-verified card history. It fits scaling/centres on an earlier training window and sets its threshold on a separate later historical window. Default observation mode displays the score without changing routing; it never reports a fraud probability. Open **Spending-pattern clustering** after selecting a transaction. No extra dependency or database reset is required. See [CLUSTERING.md](CLUSTERING.md) for feature definitions, routing controls, runnable examples and evaluation limitations.

## General policy questions

Select **I have a question about dispute policy** in the opening chat. Four evidence-collection topics retrieve a verified, attributed fictional policy version, with superseded records excluded by effective date. Answers cite individual clauses; unsupported eligibility/deadline questions and missing/conflicting policy produce abstention and human-assistance confirmation. No card, model or account lookup is required. See [POLICY_CORPUS.md](POLICY_CORPUS.md) for scope, trust boundaries, version handling and the reproducible 14-scenario evaluation. This new information corpus does not yet replace the separate transaction- or case-intake engines.

## Shared policy gates

Policy-backed outcomes require validated sources, matching scope/effective dates, supported rule premises and complete attribution. Missing, conflicting or stale authority produces abstention and review. Active saved conclusions are revalidated on read/save; case preparation and execution recheck routing policy independently. Historical events and committed-action reconciliation remain available. No database reset is needed; older unverified conclusions may be withdrawn on reopen. See [POLICY_GATING.md](POLICY_GATING.md) for contracts, version changes and verification.

## End-to-end workflow evaluation

Run `python scripts/evaluate_workflow.py` for 47 isolated, offline journeys through the same turn and reopen services used by the app. The suite checks routes, evidence, policy attribution, mandatory review, explicit confirmation, duplicate prevention and failure recovery. See [EVALUATION.md](EVALUATION.md) for costs, preserved failures, counterfactuals and limitations; [latest results](data/workflow_evaluation/latest/REPORT.md) record 47/47 passing journeys.

## Live model and integration checks

See [LIVE_VALIDATION.md](LIVE_VALIDATION.md). `python scripts/evaluate_live_extraction.py` measures actual local Ollama responses separately from parser fallback and preserves failures. `python scripts/validate_bank_integration.py` runs 46 simulator contract checks; `--require-production` fails closed because a real bank sandbox/adapter is not configured. Live model probes exposed 0% validated model field recall, so the model is not validated as a dependable extractor.

## Submission package and clean verification

See [SUBMISSION.md](SUBMISSION.md) for the archive, checksum, clean-room verification steps and expected results. The archive is built by `python scripts/package_submission.py` using an explicit allowlist; it excludes environments, secrets, keys, caches and working databases.

## Data-quality audit

Run `python scripts/audit_data_quality.py` to reproduce the consolidated [quality report](data/data_quality/REPORT.md), template-similarity and surface-token diagnostics. See [DATASET.md](DATASET.md) for methodology and frozen challenge cases. Shared templates, tiny wording-baseline samples and pending external label review limit generalisation claims.

All retained reports, source-version limits and reproduction commands are indexed
in [REPORTS.md](REPORTS.md). Improvement steps 1–5 are implemented; the expanded
evaluation and final release verification are still pending.

## Workflow controls and colleague continuation

See [WORKFLOW_CONTROLS.md](WORKFLOW_CONTROLS.md) for the explicit ordinary
transition table, action-service boundaries and versioned handoff task list.
Run `python scripts/validate_workflow_controls.py` to reproduce the package-level
continuation and invalid/repeated/interrupted/reopened journey checks. This is
synthetic contract validation; actual representative usability remains untested.

## Privacy checks and operational counts

The authenticated representative workspace includes fixed, scoped operational
counts without customer statements or identifiers. See [PRIVACY_OPERATIONS.md](PRIVACY_OPERATIONS.md)
for definitions and limitations. Run `python scripts/validate_privacy_operations.py`
to reproduce failure-path, debug/export, storage and access checks on synthetic
fixtures. Counts omit pre-save errors and are not anonymous public telemetry.
