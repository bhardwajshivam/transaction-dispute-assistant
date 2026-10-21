# Versioned policy corpus and general question journey

The new corpus is authoritative **only inside this fictional prototype**. It
describes evidence collection and safe intake behaviour. It is not real bank,
card-scheme or legal policy and does not establish eligibility, liability,
refund entitlement or legal deadlines.

## Corpus

Source: `policies/corpus/dispute_information.json`.
Approved-content digest: `policies/corpus/manifest.json`.

| Identifier | Topic | Current source clauses |
|---|---|---|
| DEMO-CANCEL | Evidence after cancelling a recurring payment | C1–C4 |
| DEMO-REFUND | Evidence and linked credits for a missing refund | R1–R4 |
| DEMO-RECOGNITION | Merchant recognition, authorisation and safe escalation | U1–U4 |
| DEMO-BILLING | Multiple charges and wrong amounts | B1–B4 |

Every topic has v1.0 effective **2026-01-01 ≤ date < 2026-10-01**, marked
superseded, and v2.0 effective **2026-10-01 onward**, marked published. v2.0
explicitly supersedes v1.0. Records contain title, topic, scope, identifiers,
effective dates, publication status, approval reference, fictional authority,
stable source URI and individual clause identifiers/text.

The date-only effective interval is start-inclusive/end-exclusive. The default
applicable date is the reproducible demo snapshot, **20 October 2026**, not the
computer's current date. Responses explicitly display this date; they must not
claim current real-world policy. The retrieval API also supports a trusted
explicit historical `as_of` parameter and labels superseded-but-applicable
versions `HISTORICAL_APPLICABLE`. The chat does not infer historical dates from
arbitrary customer wording.

## Retrieval contract and trust boundary

`policy_service.retrieve(topic, as_of, scope)` uses exact, allowlisted topics and
scope. No embeddings, model or keyword ranking over arbitrary documents is
needed for four topics. It verifies the source bytes against the manifest,
checks structured metadata, versions, dates, source locators and clauses, then
requires exactly one applicable policy. All reads use fixed local paths.

Successful retrieval preserves the corpus digest, policy/version, authority,
approval reference, effective dates, supersession link, applicability date and
each clause's `policy://IDENTIFIER/VERSION#CLAUSE` locator. Other versions are
listed separately with their exclusion reason. Source locators are internal
identifiers, not externally fetched URLs.

Two applicable versions produce CONFLICT and no answer clauses. No applicable
version produces NOT_FOUND, with no silent fallback to superseded material.
Unsupported topic/scope produces OUT_OF_SCOPE. Missing, malformed or modified
unapproved content produces UNAVAILABLE. These statuses never produce a policy
conclusion. Historical version selection is explicit; retrieval never simply
chooses the largest version number.

The manifest is a local change-control guard, not a digital signature or a bank
approval system. Policy content and the manifest are trusted repository assets;
an actor able to replace both compromises this boundary. A legitimate change
requires reviewing the text, adding a new version/effective interval, checking
supersession and updating the approved digest with regression evidence. Do not
automatically regenerate the digest at application startup. Prompt-like text in
a customer message cannot update either file or select an arbitrary path.

## Try the policy-dependent journey

Restart the existing Streamlit app; no data reload or database migration is needed.

1. Select **I have a question about dispute policy** in the first chat message.
2. Choose **What evidence do I need after cancelling a subscription?**
3. The system retrieves DEMO-CANCEL v2.0 for the demo date.
4. It displays the applicable date, effective interval, superseded version and
   evidence guidance. Every guidance clause has its own source locator.
5. The normal resolution question follows, with **Ask another policy question**
   available before closing the concern.

This general-information journey does not require a card or query account facts.
The other three corpus topics have corresponding guided questions. A small
deterministic recogniser accepts a limited set of equivalent evidence questions;
it is not a general policy assistant. Ambiguous questions stay at clarification.
Questions about eligibility, deadlines, other product scopes or an inferred
historical policy are refused and offered human assistance.

Example unsupported input: **Am I eligible for a refund?** It must not answer
yes/no. Missing, conflicting or out-of-scope policy marks review required;
queueing a handoff still requires the existing explicit confirmation. A general
policy answer never exposes the case-creation action.

## Explanation, storage and injection controls

Answers render only fixed explanatory framing and the verified retrieved clause
text. No language model composes policy conclusions or sees the corpus. User
instructions are never promoted to policy, tool names, SQL, source paths or
authority. The existing privacy screening runs before persistence; source
integrity failure prevents modified policy clauses from being displayed.

Stored concern state contains the structured question result, source evidence
and history of attempts. Handoff snapshots and the representative workspace
include that history. Customer exports include the current policy result and
attribution; account facts remain separate. Reopening preserves the historical
answer snapshot rather than rewriting it to a different version.

The legacy transaction-intake `finish` function now obtains its policy reference
from successful retrieved records instead of stamping DEMO-INTAKE v1.1 on every
outcome. No retrieved policy now means no invented consulted-policy reference.

**Scope of this change:** the existing transaction-routing policy in SQLite and
the separate case-intake JSON service remain separate, simpler policy domains.
This corpus does not replace those engines or complete eligibility execution.
Their policy clocks, attribution contracts and conclusion gates are now shared;
see [POLICY_GATING.md](POLICY_GATING.md). Activity rules and clustering remain
separate from policy Q&A.

## Reproduce the evaluation

```sh
python scripts/evaluate_policy.py
python -m unittest tests.test_policy_service -v
python -m unittest discover -s tests -q
```

The evaluator writes cases, complete actual results and failed-output artifacts
to `data/policy_evaluation/`. Fourteen constructed scenarios cover every topic,
the version boundary, historical selection, ambiguity, unsupported questions,
customer injection, missing material, expired material, overlapping versions
and corpus tampering. Conflict/expiry fixtures intentionally update a temporary
approved manifest to simulate governance mistakes; the tampering fixture retains
the old digest. None modifies the shipped corpus.

Result: **14/14 scenarios pass**, with **0 unsupported conclusions under these
checks**. Here that metric checks that failed retrieval produces no conclusion
and that successful answers include retrieved clauses and attribution. It is
not a general semantic-entailment metric or an end-to-end safety score.

Seventeen focused tests also exercise metadata/path validation, claim/source
presence, no account lookup, no case action, explicit handoff confirmation,
encrypted concern persistence, report reproducibility and the Streamlit journey.
At the information-corpus milestone, 150 regression tests passed; the current complete suite passes 208 tests. The subsequent workflow evaluation and cost-sensitive report are documented in [EVALUATION.md](EVALUATION.md).
