# Workflow transitions and human continuation

The shared `workflow.process` service validates known state shapes before tools
or storage, then checks ordinary controller transitions before saving a turn.
Unknown steps and illegal jumps fail closed with structured WorkflowError codes.
New saved turns carry `DISPUTE-WORKFLOW-1.0`; existing concerns are not rewritten
or reset. Reopen validates known state before restoring durable action status.

## Ordinary transition table

Self-loops preserve invalid/incomplete answers. Any known state may enter
`handoff_confirm` when review is required or assistance is offered. Policy
handling has explicit edges below. `finish_*` branches are transient controller
branches, not persisted states; their stored destinations are satisfaction or
review. `handoff_pending` becomes done only after atomic queue persistence.

| Current step | Ordinary next steps (besides self-loop/review) |
|---|---|
| `issue` | `card`, `policy_topic` |
| `card` | `elaborate` |
| `elaborate` | `other_transaction`, `search_confirm`, `search_details` |
| `different_issue` | `satisfaction` |
| `other_transaction` | `satisfaction`, `search_confirm`, `search_details` |
| `search_details` | `search_confirm` |
| `search_confirm` | `elaborate`, `search_details`, `transaction` |
| `transaction` | `cancel_type`, `duplicate`, `elaborate`, `expected_amount`, `expected_currency_only`, `receipt`, `recognise`, `refund_status`, `satisfaction` |
| `recognise` | `other_user`, `resolved` |
| `resolved` | `other_user`, `satisfaction` |
| `other_user` | `permission` |
| `permission` | `safety`, `satisfaction` |
| `safety` | `satisfaction` |
| `cancel_type` | `cancel_date`, `cancel_method` |
| `cancel_date` | `cancel_method` |
| `cancel_method` | `cancel_confirm` |
| `cancel_confirm` | `cancel_reference`, `satisfaction` |
| `cancel_reference` | `satisfaction` |
| `billing_type` | `duplicate`, `expected_amount`, `expected_currency` |
| `duplicate` | `purchase_count` |
| `purchase_count` | `receipt` |
| `expected_amount` | `receipt` |
| `expected_currency_only` | `receipt` |
| `receipt` | `adjustment`, `satisfaction` |
| `adjustment` | `satisfaction` |
| `expected_currency` | `currency_receipt` |
| `currency_receipt` | `satisfaction` |
| `refund_status` | `refund_amount`, `refund_currency_only`, `refund_date`, `refund_method` |
| `refund_date` | `refund_amount`, `refund_currency_only`, `refund_method` |
| `refund_amount` | `refund_method` |
| `refund_currency_only` | `refund_method` |
| `refund_method` | `refund_confirm` |
| `refund_confirm` | `refund_reference`, `satisfaction` |
| `refund_reference` | `satisfaction` |
| `satisfaction` | `done`, `handoff_confirm`, `policy_topic` |
| `handoff_confirm` | `done`, `handoff_pending` |
| `handoff_pending` | `done` |
| `confirm` | `satisfaction` |
| `policy_topic` | `satisfaction` |
| `done` | `satisfaction` |

## Card and case controls

Card requests are explicit interrupts. Card states are protect_card, protect_kind,
protect_confirm, protect_unknown, protect_after and protect_failed. The card
service owns card selection, preview, confirmation, permission, state/version,
idempotency and reconciliation. Cancel/resume restores the saved ordinary step
and original dispute answers/card. Reported loss preserves mandatory review.
The graph does not itself authorise an action.

Case controls are available only when case_chat.options permits them and the
case service rechecks its own policy/permission/confirmation contract. Ordinary
transition checks do not replace these service controls. Durable action ledgers
recover committed actions after chat-save failure. A stale conversation revision
cannot overwrite a newer snapshot; repeated action requests use stable keys.

The contract rejects unknown states, but is not a typed-state implementation or
formal verification. Existing independent service checks remain essential. The
persistence helper is not a public customer endpoint: callers must use the shared
workflow service, and direct command services still enforce their own guards.

## Handoff continuation package

New packages carry `DISPUTE-HANDOFF-1.1`, workflow version and an advisory
`continuation` section. Existing frozen packages retain their original content.
The package separately preserves customer assertions, selected synthetic bank
facts, retrieved evidence/policy, missing information, review reasons, attempted
actions and the interrupted step. Proposed colleague work is derived only from
these fields; it does not generate a new eligibility decision or authorise action.

The task ordering is:

1. Reconcile existing UNKNOWN/SUBMITTING commands before retry or replacement.
2. Inspect later updates; the package itself is an immutable snapshot.
3. Resolve listed evidence gaps and incomplete questions.
4. Compare assertions with bank facts while preserving contradictions.
5. Revalidate applicable policy and colleague permissions before proceeding.

The representative UI displays these tasks and keeps later events separate.
The callback is explicitly unscheduled in this simulation. No human notification,
card change or banking action is inferred from the checklist.

## Reproduce and assess

```sh
python scripts/validate_workflow_controls.py
python -m unittest tests.test_workflow_controls -v
```

The report is `data/workflow_controls/report.json`, including source hashes,
transition inventory and test names. Nine contract tests cover illegal jumps,
unknown states, early confirmation, foreign cards, repeated search, out-of-order
selection, stale writes, interruption/reopen/cancellation, conflicting-evidence
handoff, later corrections and unknown-action reconciliation. Existing case/card
suites separately cover action replay, concurrent submission and commit/save
failure recovery.

The continuation check verifies a colleague can see the disputed INR 99 assertion
and verified INR 8.50 transaction separately, identify the material conflict and
find actionable next steps without reading the transcript. Another check verifies
an unknown card-action command is the first reconciliation task. This is an
engineering contract check, not evidence of actual colleague usability; a real
representative review remains outstanding.
