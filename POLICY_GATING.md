# Consistent attribution and policy-conclusion gates

Policy questions, transaction routing and case recording now share
`policy_contract.py`, contract **policy-evidence-v1** and the same demo clock.
The sources remain separate, bounded policy domains; no source can authorise a
conclusion belonging to another domain.

| Purpose | Authoritative simulation source | Permitted conclusion |
|---|---|---|
| policy_information | Approved, digest-checked dispute-information corpus | General evidence guidance from cited clauses |
| transaction_intake | Validated DEMO-INTAKE record in the selected SQLite database | EXPLAIN or HUMAN_REVIEW under P-01/P-02/P-03 |
| case_intake | `policies/case_intake_v1_1.json` | Permission to record a simulated case, after all other action gates pass |

None decides fraud, liability, legal eligibility or refund entitlement. Activity
rules and clustering remain advisory/workflow signals, not financial policy or
action authority.

## One evidence format

Every active policy-backed decision records:

- `policy_context`: contract version, purpose, scope, applicable date, status,
  reason code, allowed flag, attributed sources and applied clauses.
- `policy_records_consulted`: only validated sources actually supporting the
  conclusion, rather than candidates that could not be selected.
- `policy`: a display label derived from those sources, never a hardcoded claim.
- `policy_conclusion`, `decision_type` and `policy_reason_code`: distinguish an
  authorised policy-backed intake outcome from an operational referral.

Source entries include identifier, version, scope, effective interval, applicable
date, authority, source URI, content SHA-256 and hash scope. Information policy
uses its approved corpus digest; transaction/case policy uses a canonical JSON
document digest. Supersession metadata is preserved where present. Applied
clauses carry individual source locators. Case previews/results expose the same
structure under `policy_attribution`, separately from command/action status.

All three use **20 October 2026**, the explicit reproducible demo snapshot.
Effective intervals are start-inclusive/end-exclusive. Consent expiration,
session expiry, audit timestamps and idempotency operations still use real time:
the frozen policy clock does not extend a ten-minute confirmation window.

## Transaction conclusion gate

At `finish`, the controller reads the policy source again rather than trusting
cached SUCCESS metadata. It requires exactly one effective DEMO-INTAKE policy
in the expected scope. Database identifiers, versions, dates and scope must
match the JSON body. The source must identify itself as fictional. The rule set
must match the supported deterministic condition/outcome definitions; unfamiliar
rules or prompt-like substituted conditions are not executed.

The controller checks the corresponding rule premise in collected assertions:

- P-01: the customer answered that they recognised the payment and that this
  resolved the concern.
- P-02: the customer reported that the payment was made without permission.
- P-03: the relevant cancellation, billing or refund intake details were collected.

These are customer assertions, not verification of authorisation or entitlement.
The only policy-backed outcome is the bounded intake route. Transaction outcome
text cites the applied rule and applicable date. Source hashes enter its evidence
IDs; cached policy evidence is not silently included as current authority.

Missing, expired, conflicting, malformed or out-of-scope policy, or an unmet
premise, produces **no policy conclusion** and no supporting-policy citation.
The route is safe human review. `intended_reason` preserves the attempted journey
outcome while the primary reason identifies abstention. A reported unauthorised
payment retains its safety reason, with the policy failure recorded separately.
Urgent guidance and safe referrals are still possible without policy; neither
claims that policy approved an outcome.

## Information and case gates

The information renderer and journey both check the common attribution contract.
It verifies topic scope, applicable date, source identity, digest and clause
locators. The historical retrieval API accepts an explicit trusted date; the
active chat uses the demo date. Candidate versions in a conflict remain available
in the raw retrieval result for investigation, not as applied policy sources.

Case creation checks fresh transaction-routing policy in the same SQLite
transaction as its permission checks. Its result must match the stored decision's
source, hash, date, clauses and citation fields. A policy-valid preview cannot
bypass a routing decision that is unverified, forged or stale. Execution repeats
these checks. Changed policy blocks execution and requires a new review/decision.
The case-intake clause is applied only after the service's preconditions pass.
Action/audit records preserve both routing and case-intake contexts.

The tightened case policy is explicitly **v1.1**, effective 20 October 2026,
superseding v1.0 for new commands. The original `case_intake_v1.json` is retained
as an archival source; it is not a fallback for new submissions. Previously
recorded action snapshots retain their original policy. The prototype does not
implement a historical case-policy selection API.

## Reopening, persistence and recovery

Concern reads and saves revalidate active policy-backed decisions. A changed
source/digest, unavailable policy, mismatched citation, unsupported rule or missing
legacy attribution withdraws the active conclusion. It becomes historical only,
with a visible explanation and mandatory review. Original messages/events are
preserved; `previous_decision` retains the prior conclusion. Policy-question
history also remains intact while its active result is marked stale.

Read-time validation is an in-memory view, not a silent rewrite of immutable
history. A subsequent explicit update saves the new state. Existing legacy
concerns may therefore require fresh review after this upgrade. Case-open and
confirmation/retry controls are hidden when the active conclusion is withdrawn;
status lookup and cancellation remain available. Service checks enforce the
same restrictions independently of the UI.

A committed case is different from a proposed action: its result may still be
reconciled by its original idempotency key after policy changes. Current policy
does not erase historical committed evidence or authorise a replacement action.
Thus timeout-after-commit recovery can return confirmed success without creating
a second case or asserting a new policy decision.

## Verification and remaining limits

```sh
python -m unittest tests.test_policy_gating -v
python scripts/evaluate_policy.py
python -m unittest discover -s tests -q
```

The gating milestone added 18 tests and brought the suite to 168. The current complete suite passes 208 tests. New coverage
includes the shared attribution schema/clock; missing/conflicting/expired/wrong-
scope policy; metadata mismatch; unsupported rule prose; unmet premises; cached
success after source loss; changed-content and forged-citation withdrawal;
reopening policy answers after corpus failure; case execution after policy change;
restricted UI controls; and committed-action reconciliation after policy removal.
The 14-scenario general-policy evaluator still passes with no unsupported
conclusions under its documented checks.

This is not a complete explanation-entailment verifier or a banking eligibility
engine. Transaction explanations are fixed controller templates, and the gate
checks supported rules/routes and provenance; arbitrary model-written financial
conclusions are not enabled. SQLite/file policy sources are trusted administrator-
controlled assets, not digitally signed bank policy. The corpus manifest protects
against source-only tampering, not an actor who can replace trusted source and
manifest together. The constructed cost-sensitive workflow evaluation is now available in [EVALUATION.md](EVALUATION.md); independent banking validation remains outstanding.
