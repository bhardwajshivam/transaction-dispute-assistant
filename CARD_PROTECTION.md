# Confirmed simulated card protection

Card protection is a separate safety journey. It is available through **Secure
or block my card** at the opening and as a chat reply option during another
concern. Explicit phrases such as `block card`, `block my card`, `I want to block
my card`, `can you block my card?` or `my card was stolen` also start it. Narrow
anchored rules recognise requests; negated instructions, hypothetical/advice
questions and prompt-injection prose do not silently select an action.

## Customer flow

1. Choose an accessible card. A transaction reference, amount, detailed reason or
   completed dispute investigation is not required.
2. Choose a temporary lock or permanent block, with their effects explained.
   Explicit loss/theft/compromise reports offer permanent block or cancellation,
   rather than downgrading that report to a temporary-lock recommendation.
3. Review the specific card and action. Only **Confirm simulated card protection**
   authorises execution; a plain “yes” does not. Confirmation expires after ten
   minutes and the preview can be cancelled before dispatch.
4. Show completion only when an action record establishes the simulated result.
   Ambiguous outcomes instead offer status lookup or explicit same-request retry.
5. Offer continuation of the original concern or a confirmed assistance request.
   A standalone request can finish without starting a transaction complaint.
   Lost/stolen-card review requirements remain in place after protection.

Protecting a different card does not replace the selected card or answers in an
interrupted dispute. The previous step is preserved. Normal mandatory-review
controls apply when that concern resumes. A queued human handoff is not proof
that any real card was blocked.

## Implemented service contract

`card_service.py` provides `prepare`, `execute`, `cancel`, `reconcile` and `latest`.
`card_chat.py` owns the bounded conversational interaction. `workflow.py` handles
this path before ordinary dispute/case progression and skips dispute evidence
lookups while the card-control turn is handled. No model or risk score can invoke
an action. The UI cannot bypass the independent service gates.

| Control | Behaviour |
|---|---|
| Identity | Separate demo `CardPrincipal` with `card:protect`, expiry and ownership checks; a case-create permission alone is insufficient |
| Ownership | Account-access join and selected card checked at preview and execution |
| Permissions | Durable per-customer/account `card_permissions`; additive migration never restores a revoked permission |
| Current facts | Card status and version rechecked before dispatch and at the atomic gateway; changed status requires a new preview |
| Policy | Fictional DEMO-CARD-PROTECTION v1.0, current shared reference date, exact scope/action set and administrator-approved content digest |
| Confirmation | Exact explicit confirmation, preview expiry and durable confirmed intent before dispatch |
| Idempotency | Stable command ID, unique action per command, successful replay returns existing result; a new repeated block of an already blocked card is a no-op |
| Concurrent requests | SQLite write locks and state versions prevent lost updates; committed action evidence outranks stale dispatch state |
| Unknown outcomes | Preserve command ID, reconcile committed action first, offer explicit retry; unresolved commands block replacement requests for that card across concerns |
| Audit | Prepare, confirmation, denial, cancellation, status verification and simulated action recorded; handoffs include card-action attempts |
| Recovery | Reopen restores latest durable command; an action committed before chat-save failure is not lost or submitted again |
| Retention | Concerns linked to submitting, unknown or successful card commands are excluded from the generic purge; unsubmitted/cancelled command rows are deleted before an eligible concern |

The fourth policy source is `policies/card_protection_v1.json`, with approval in
`policies/card_protection_approved.json`. Its administrator-maintained digest is
an integrity gate, not a cryptographic signature or protection against an actor
who can replace both files. It is separate from transaction intake, general
information and case-recording policy. The policy uses the shared attribution envelope with purpose, scope, sources
and action clauses. The durable command retains the policy hash; its preview records source, version, effective date and effects in concern
history. Missing/tampered/expired policy authorises no new action. Status lookup
of a committed action remains available after policy loss.

## Local data model

Additive migration creates `card_controls`, `card_permissions`,
`card_control_schema`, `card_commands` and `card_actions` in the existing database.
All generated synthetic cards are initially ACTIVE when this schema is first
installed; that is an explicit simulator initial condition, not a real bank
lookup. Missing status rows thereafter fail closed. Status is ACTIVE, LOCKED or
BLOCKED, with a version counter. Command state is PREPARED, CANCELLED,
SUBMITTING, UNKNOWN, SUCCEEDED or REJECTED. A permanently blocked simulated card
cannot be downgraded to a lock. Transaction facts are not modified.

Card command IDs, card/action/status metadata and action/audit records are local
synthetic operational metadata. Customer statements and preview/history payloads
use the existing encrypted concern storage. This is not whole-database encryption
or an independently managed bank audit trail. Existing histories are preserved;
no reset, new dependency or database reload is required.

## Limits that must remain visible

- **Simulation only:** no real bank card is changed. Urgent guidance directs the
  customer to official bank controls/support for actual protection.
- Unlock, replacement and card closure are not implemented. The temporary-lock
  explanation explicitly says unlocking is unsupported in this prototype; do not
  imply the app provides an unlock facility.
- A restriction does not cancel a subscription, reverse a payment, settle a
  dispute or guarantee every payment type is stopped. A real adapter must use
  bank-approved semantics for pending, recurring and tokenised payments.
- Fixed demo identity is not bank authentication or step-up authorisation.
  Production requires bank-approved session, entitlements and API contracts.
- The command ledger supplies tested simulator semantics; it does not establish
  that a remote bank supports idempotency, availability or reconciliation.

## Reproduce

```sh
python -m unittest tests.test_card_protection -q
python scripts/validate_bank_integration.py
python -m unittest discover -s tests -q
python -m streamlit run app.py
```

The 18 focused tests cover exact confirmation, permission/ownership/expiry,
revocation, cancellation, stale state, tampered/missing policy, loss reports,
interruption/resumption, gateway intent, concurrent replay, repeated-block no-op,
timeouts before/after commit, chat-save recovery, handoff contents, unchanged
transaction facts and the actual Streamlit path. The integration validator now
includes those tests alongside the existing evidence and case contracts.
The original 47 dispute workflow scenarios remain a separate regression suite;
they are not silently relabelled as card-control coverage.
