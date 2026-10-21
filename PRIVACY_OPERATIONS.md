# Failure-path privacy and operational visibility

This is an application-level synthetic validation, not a compliance certification
or evidence that all personal information formats are detected.

## Failure boundaries

Model exception text and arbitrary exception codes are excluded from extraction
traces. Only a fixed extraction-code allowlist is retained. Action boundary codes
also use an explicit allowlist before the chat may display them. Generic failures
use fixed fallback codes; raw exceptions are not appended to customer messages,
concern snapshots, handoff packages or operational reports.

Evidence adapters convert unexpected exceptions to UNAVAILABLE and malformed
response envelopes to MALFORMED. Policy conflict/stale/scope statuses are retained
so privacy hardening does not collapse a meaningful policy failure into a generic
success or absence. Unexpected orchestration failures return a fixed WorkflowError
and do not save an unconfirmed turn. No action completion is inferred from these
error states; durable commands remain the authority for action recovery.

Extraction validator version 1.3 adds diagnostic-code minimisation to the measured
1.2 validation behaviour. The retained step-3 live reports describe their original
source fingerprints and are not rewritten to claim measurements of this revision.
A fresh end-to-end evaluation is scheduled in step 6.

## Operational summary

Authenticated representative users can open **Operational counts — authorised
customer scope** in their workspace. `operations.staff_summary` enforces staff
scope and expiry before reading snapshots. It returns fixed numeric dimensions:

| Counter | Meaning |
|---|---|
| concerns | Current saved snapshots in authorised customer scope |
| extraction_attempts | Saved extraction traces with an invoked/configured model |
| extraction_fallbacks | Saved traces reporting unavailable/invalid model fallback |
| extraction_rejected_proposal_cases | Extraction traces containing rejected fields |
| evidence_tool_failures | Recorded unavailable/malformed/forbidden tool attempts |
| policy_failure_concerns | Snapshots retaining a known policy-failure review reason |
| required_review_concerns | Current snapshots requiring specialist review |
| queued_handoffs | Confirmed simulated queue records |
| unknown_case_commands / unknown_card_commands | Current UNKNOWN or SUBMITTING commands |
| existing_case_links | Durable CASE_EXISTING_LINKED audit events |
| card_noop_commands | Recorded card commands that made no state change |

No names, email addresses, card/customer/transaction/concern identifiers, amounts,
statements, raw tool/model payloads or dynamic label dimensions are returned.
There is no customer-facing metrics panel or unauthenticated export endpoint.
The read is audited with staff actor metadata, as other representative reads are.
Scope is customer-based in this prototype, not a production role/assignment model.

Each concern is read once from its latest snapshot, avoiding counting cumulative
traces again for every saved event. Tool/extraction counts can still exceed
concern count because multiple attempts can exist. Required-review and failure
reasons can remain sticky after recovery. Unknown commands reflect current status,
not the number of timeouts ever seen. Retention changes the population.

This is snapshot observability, not request-rate or latency monitoring. Rejected
secrets and failures before persistence are intentionally not saved and cannot
be counted here. Replayed requests that return an existing result without a new
audit event are not measured; the partial duplicate-prevention indicators must
not be advertised as all prevented duplicates. Small scoped counts are still
sensitive and are not anonymous public statistics.

## Reproduce the privacy checks

```sh
python scripts/validate_privacy_operations.py
python -m unittest tests.test_operational_privacy -v
```

The report at `data/privacy_operations/report.json` contains source fingerprints,
22 focused test results and an explicitly synthetic counter example. It never
queries or exports the working database. Failure reports contain test identifiers
and fixed failure categories; stack traces and test canaries are not published.

Checks include canaries in model exceptions/codes and tool exceptions; safe
recovery/review; malformed tool envelopes; nested evidence redaction; actual
Streamlit debug rendering; customer/representative history minimisation; encrypted
storage; staff scope and expiry; fixed counter dimensions and snapshot counting.
Existing privacy and metadata suites also cover key failures, retention holds,
secret blocking and removal of machine-local model metadata.

The application does not configure or certify OS, proxy, framework or external
service logs. Unrecognised names/addresses, unusual number formats, prompt
injection embedded in otherwise valid evidence and contextual personal data need
broader bank-approved review. Real deployment additionally requires production
identity, key management, authenticated infrastructure and governed retention.
