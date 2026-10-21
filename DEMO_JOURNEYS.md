# Required journey demonstrations

Run the README setup first. The GUI uses the generated two-card demo database
and deterministic modes. All effects are simulated; use synthetic statements.
For reproducible evidence independent of manual clicking, run:

```sh
python scripts/demonstrate_journeys.py
```

This runs eight selected reference journeys through the same turn/reopen services
as the chat. Each has its own generated temporary database and a fixed reference
date. Reports are written to `data/workflow_evaluation/demonstrations/`, including
inputs, full actual traces, structured decisions, policy sources and case/handoff
counts. It does not automate a browser; separate Streamlit regression tests
exercise UI interactions.

| Required behaviour | Reference case | What to inspect |
|---|---|---|
| Unrecognised payment with merchant resolution/history | `recognised` | Verified merchant evidence and historical activity checks; customer recognition produces an attributed explanation |
| Cancelled recurring payment | `cancelled_subscription` | Reported cancellation plus merchant request/effective dates; unresolved concern referred for review |
| Potentially unauthorised activity and urgent guidance | `ongoing_card_risk` | Required review and official-bank safety guidance; no autonomous card blocking |
| Policy-dependent question | `policy_question` | Relevant current policy ID/version, clause attribution and bounded evidence guidance |
| Ambiguity | `search_amount_42` | Two matching payments remain candidates; neither is automatically selected |
| Policy evidence missing | `policy_missing` | No policy conclusion; explicit abstention/referral |
| Model failure | `model_timeout` | Trusted failure adapter exercises safe deterministic recovery; no live model required |
| Tool failure and human continuation | `tool_unavailable_handoff` | Required review, explicit handoff confirmation, missing-information and attempted-action sections |

The first case includes historical assessment, but history does not establish
customer authorisation; recognition is a customer assertion. Failure fixtures
are evaluator-owned adapters, never customer-controlled switches.

## Try in Streamlit

1. **Merchant recognition:** choose unrecognised transaction, select CARD-001,
   enter `Please investigate payment TX-1001.`, confirm search and select TX-1001.
   Follow the recognition/authorisation questions. Review merchant information
   and the activity assessment without interpreting a signal as fraud.
2. **Cancellation:** choose charged after cancellation, CARD-001, describe
   `Please investigate payment TX-1002.`, confirm search and select TX-1002.
   Choose recurring subscription, report cancellation on `13-10-2026`, then
   provide Email and confirmation details when asked. A different request date
   can instead produce material-conflict review, intentionally.
3. **Ambiguous amount:** choose wrong amount, CARD-001, enter
   `I was charged INR 42 instead of INR 40 on 15-10-2026.` Confirm search.
   TX-1003 and TX-1004 should both be offered. Do not infer a duplicate solely
   from the matching date and amount.
4. **Policy question:** use the opening policy-question option. Choose one of the
   supported evidence questions; check the cited policy version and clauses.
   Eligibility/deadline questions outside that corpus must not receive a
   definitive account conclusion.

For urgent-risk, failure recovery and handoff, use the reference traces above
or the corresponding `evaluation/scenarios.py` steps as the exact sequence.
Required-review interruptions deliberately prevent some ordinary follow-up
questions. Do not alter labels to force a desired route.
