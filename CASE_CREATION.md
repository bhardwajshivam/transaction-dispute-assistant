# Confirmed simulated case creation

Case creation is a deterministic command service, separate from concern notes,
read-only evidence gathering and human-assistance requests. It records a dispute
for review; it does **not** decide chargeback eligibility, approve refunds,
freeze cards or contact a real bank. No model can call the action service.

## Customer example

1. Choose **I have been charged the wrong amount**, select your demo card,
   describe the issue, confirm search details and select a posted transaction.
2. Complete the follow-up questions until a review outcome appears.
3. Select **Open a dispute case** inside the chat. Review the transaction,
   amount, reported issue, statement and fictional intake-policy reference.
4. Select **Confirm and create dispute case** within ten minutes, or
   **Do not create a case now**. Only explicit confirmation submits the request.
5. A verified success displays a `CASE-…` reference. Staff can inspect its
   frozen evidence package under **Representative workspace → Simulated dispute
   cases** using the existing staff sign-in. Later concern notes remain in the
   concern history; the original case snapshot is preserved.

No database reset is necessary. Additive tables are installed on the next app
connection. Restart with `python -m streamlit run app.py` from the activated venv.

## Controls and authority

| Capability | Technique and authoritative input | Output / failure behaviour |
|---|---|---|
| Prepare | Deterministic validation of persisted concern and freshly queried card/account/transaction | Suggestion: immutable, encrypted preview; no case yet |
| Permit submission | Explicit customer principal, `case:create` permission, `account_access` and `case_permissions` | Verified permission at preparation and execution; revoked access blocks submission |
| Intake route | Versioned `policies/case_intake_v1_1.json`, shared demo policy date, validated routing-policy attribution and reason codes | Policy decision to record for review; missing/stale policy, pending payments, unsupported complaints or unresolved material evidence block automatic creation |
| Confirm | Exact chat command bound to a prepared command ID; ten-minute expiry; compare material snapshot hashes | Authorised simulated action only if complaint, transaction and policy still match |
| Execute | Durable command intent, transactional gateway, unique action idempotency key and case registry | Verified creation or link to existing case; no predictive score has authority |
| Recover | Query committed action ledger by the same command ID | `SUCCEEDED` only with committed evidence; absent response/record stays `UNKNOWN`, with status check and same-request retry |
| Explain | Templates using transaction preview and verified service result | No claimed case/reference before committed success; specialist requirements remain sticky |

`CustomerPrincipal` must be created by a trusted authentication boundary. This
prototype's `demo_customer()` grants only synthetic C-001 access; it is **not
production authentication**. A bank integration must replace that boundary with
its authenticated session and action permissions. `case_permissions` is seeded
once from fixture account access. Setting `can_create=0` persists a revocation;
opening a new connection does not silently grant it again.

Prepared payloads contain the saved customer assertions, structured routing
record, consulted evidence, selected transaction facts and exact intake policy.
Material changes invalidate consent. Chat display changes and the operational
unknown-outcome review signal do not change complaint evidence. New customer
assertions do change it. A previously committed action can always be reconciled
even if policy or evidence subsequently changes.

## Persistence and tool contract

`case_commands` records PREPARED → SUBMITTING → SUCCEEDED, or UNKNOWN/REJECTED;
CANCELLED is available before submission. Confirmation and SUBMITTING commit
before dispatch. This durable intent permits recovery after process interruption
or a failed chat-history save. Reopening a saved concern restores its latest
command and reconciles pending outcomes independently of its chat snapshot.

The simulated bank gateway atomically writes `cases`, `case_registry`,
`case_links`, `actions` and `audit_events`. A database failure rolls these writes
back together. An uncertain response does not imply a rollback. Status lookup
uses the action's unique idempotency key. An absent record after dispatch is
insufficient to claim failure, so UNKNOWN remains visible and requires review.
Retry uses the same command ID and rechecks current facts and permissions.
There is no automatic retry loop or autonomous escalation action.

Two confirmed requests for the same customer's payment share one case; their
concerns are linked and each confirmed command has an action record. Concurrent
submissions are serialised with SQLite write transactions and uniqueness
constraints. The prototype keeps one case per customer/payment indefinitely;
separate subsequent claims or reopening a closed case require a future staff
lifecycle workflow. It does not adjudicate that distinction automatically.

Unknown outcomes raise mandatory specialist review. Assistance still requires
the separate explicit handoff confirmation. Success does not clear that review.
Read-only staff views include unresolved commands as well as recorded cases.

Payloads in case/command/action/audit records use the existing authenticated
encryption key. Minimal privacy-audit events record preparation, confirmation,
gate denials, creation/linking, unknown outcomes and verified status. They are
local database audit records, not a tamper-proof bank audit system. Customer
exports expose only the saved case reference/status/reason. Retention preserves
concerns linked to cases or unresolved commands; abandoned, cancelled or rejected
unlinked proposals can be purged with their expired concerns.

## Evaluation and limits

Run `python -m unittest tests.test_case_service -v` for the focused checks and
`python -m unittest discover -s tests -v` for regression checks. Fault injection
is Python test-only (`fault=`), not a customer or language-model option.

Focused scenarios cover confirmation, decline, expiry, missing permissions,
permission revocation, ownership changes, changed transaction amounts/customer
statements/policies, stale policy, pending transactions, evidence conflicts,
timeouts before/after commit, malformed responses, atomic storage failure,
same-key retries, concurrency, duplicate concerns, interruption recovery,
encrypted persistence, scoped staff access, retention and Streamlit interaction.

On 21 October 2026, **98 tests passed**, including **22 focused case-service
tests**. The existing local database migrated with all 12 concern histories
preserved, a successful SQLite integrity check and no foreign-key violations.

Two defects exposed during implementation were corrected: a gateway replay could
reject a concurrently completed request unless its committed action was checked
first; uppercase opaque references could resemble IBANs to the privacy scrubber,
so generated references use lowercase opaque suffixes. An additional regression
checks that recording an unknown-action review signal does not invalidate a safe
retry of the original request.

These are synthetic functional tests, not external banking certification or
proof of model quality. The gateway and state store share SQLite in this demo.
A production remote gateway needs authenticated transport, matching idempotency
and status guarantees, operational reconciliation, monitored staff queues,
institution-approved policies and a complete case lifecycle. The fictional
intake policy deliberately makes no legal eligibility or refund promises.
