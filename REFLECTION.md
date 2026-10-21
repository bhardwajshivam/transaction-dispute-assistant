# Engineering judgement and critical reflection

The objective was a dependable prototype of dispute intake and evidence handling,
not an autonomous dispute adjudicator. The strongest result is the separation
between what the customer reports, what an account lookup establishes, what
supported policy permits the controller to conclude, and what an explicitly
confirmed service may execute. That separation makes failures inspectable and
limits what an uncertain component can cause.

The implementation is still a prototype. Its policies are fictional, identity is
a fixed demo principal and all bank operations use a SQLite simulator. Those
limits are acceptable for demonstrating the engineering approach, but they place
a clear boundary around the conclusions supported by the results.

## What worked and what it cost

Starting with capability boundaries helped keep most of the system conventional.
Transaction search uses scoped SQL, policy applicability uses explicit dates and
supported rules, and consequential operations use a confirmed command service.
The bounded evidence loop provides a useful agentic behaviour—identifying and
filling permitted evidence gaps—without delegating action authority to a model.
No agent framework was necessary to implement that loop.

This choice has costs. Exact search can ask more questions than a tolerant
merchant matcher. Explicit branches become harder to maintain as complaint types
and exceptions grow. Templates are less flexible than generated explanations.
The current state dictionary is convenient for a prototype but does not provide
the guarantees of typed state variants or a formally checked transition model.
These are engineering debts to manage, not reasons to replace explicit controls
with an unconstrained model.

The case service is stronger than a simple demonstration button. It separates
preview from confirmation, checks permission and current evidence, persists
intent before dispatch, uses stable idempotency keys and reconciles ambiguous
outcomes. Its SQLite atomicity does not establish that a remote bank will provide
the same guarantees. The useful deliverable is an explicit contract to validate
against a future bank adapter.

## Weakest component: understanding varied customer descriptions

The weakest implemented capability is language understanding beyond the explicit
complaint choices and supported date/amount patterns. The workflow can continue
by asking questions, but that does not mean it correctly understands varied
natural language, negation, corrections, relative dates or unfamiliar merchant
phrasing. A source span can be present in a message and still have the wrong
semantic role. Grounding validation is necessary but is not full understanding.

The live local-model evaluation made this limitation measurable. On 14 fixed
synthetic statements, `smollm2:135m` returned structurally valid responses but
repeated the prompt example amount, which was absent from the statements.
Validation rejected those proposals. Validated model field recall was 0%.
Five model-only exact matches were cases where the expected extraction was empty;
they are not evidence of useful extraction. Precision was undefined because no
model fields survived validation.

Initially the combined parser/model path passed 13 of those 14 statements. That
was also insufficient evidence to endorse the model: deterministic extraction
was rescuing the pipeline. The evaluator now reports model-only and combined
results separately so a successful fallback cannot mask model failure.

The remaining failure exposed an ordinary parser bug. An overly broad named-month
pattern accepted `85 on 2026` as a date in a statement containing an amount and an
ISO date. That swallowed the amount and part of the actual date, leaving date
fragments to be considered as conflicting amounts. Restricting the pattern to
supported month names fixed the cause without changing the expected answer.
Deterministic extraction now passes all 14 unchanged development probes. The
original outputs are retained in
`data/live_extraction_evaluation/before_parser_fix/`.

The resulting design decision is to make deterministic extraction the default
and retain Ollama only as an explicit optional mode. This is not a claim that
rules solve natural language generally. It is a proportionate response to the
measured behaviour of this component. Missing or uncertain information still
requires clarification, and search criteria still require customer confirmation.
See [LIVE_VALIDATION.md](LIVE_VALIDATION.md) for the results and reproduction.

## Most important unresolved risk: confidence beyond the evidence

For interpreting the submission, the largest unresolved risk is that synthetic
conformance is mistaken for performance on real disputes. The same development
process produced the rules, scenarios and expected labels. Even when labels are
kept out of runtime inputs and evaluation customers are disjoint, shared scenario
families can reflect the implementation's assumptions rather than expose them.
Hand-authored route expectations are not independently adjudicated bank outcomes.

The activity corpus deliberately includes authorised anomalies and unauthorised
transactions that do not trigger activity signals. That is useful evidence
against interpreting anomaly as fraud, but it does not reproduce real fraud
prevalence or calibrate a probability. Clustering therefore remains a distance
signal in shadow mode by default. A low score cannot establish authorisation;
a high score cannot authorise a refund, case submission or card action.

For a real deployment, the largest operational risk is the missing bank trust
boundary: identity, entitlements, authoritative data freshness and remote action
semantics. Fixed demo identity and local permission rows do not establish real
customer authentication. A local committed action does not establish how a bank
API handles timeout-after-commit, duplicate keys or concurrent requests. The
integration report consequently says `NOT_VALIDATED`, even when all simulator
contracts pass. These are external validation requirements, not features that
can be established by adding more local mocks.

Privacy is another material limitation. Encryption, minimised exports, staff
scope and secret blocking reduce exposure, but heuristic redaction is not a
complete PII detector. The extraction regression work found a phone number that
escaped redaction when followed by a full stop. Fixing that example improves a
specific boundary; it does not establish exhaustive protection across formats,
languages or structured bank payloads. Real customer logging needs a separate
bank-approved design and review.

## Evaluation changed the implementation

The original 47-journey workflow run passed 44 cases, with two critical missed
review requirements and weighted error cost 1,070. Broad route accuracy was
46/47, approximately 97.9%. That apparently strong route score hid an unsafe
control: uncertain authorisation reached a human-review route but could still
be closed through the satisfaction question.

Three improvements followed from the preserved failures:

1. Uncertain authorisation now creates a sticky review requirement. Satisfaction
   and assistance preferences cannot clear it.
2. A reported cancellation request date that conflicts with the merchant request
   record now preserves both accounts and requires material-conflict review.
3. Handoff packages now explicitly record missing information, attempted actions
   and the interrupted step, rather than requiring staff to infer them from a
   conversation transcript.

The unchanged 47 journeys now pass, with no observed critical misses,
unsupported actions or false success claims. That result supports the tested
controls; it does not estimate a production incident rate. Costs are illustrative
relative severities, not financial loss estimates. Original failed outputs and
case fingerprints are retained so reviewers can see what improved without
assuming the expected outcomes were relaxed.

The full regression suite currently passes 186 tests. A test count alone is not
an assurance argument. The important checks are the invariants they exercise:
scoped references, mandatory review, withheld unsupported conclusions, explicit
confirmation, duplicate prevention, unknown-outcome recovery and truthful status
reporting. The current claim checks cover provenance and selected dangerous
assertions; they are not a general semantic-entailment metric.

## What to do next, in order

| Priority | Work | Evidence required before relying on it |
|---|---|---|
| 1 | Independently author unseen journeys and review terminal labels | Bank/domain reviewer agreement, explicit ambiguous cases and failures reported by route and severity; no tuning on the withheld set |
| 2 | Challenge deterministic intake with varied descriptions | Unseen corrections, negation, date/amount roles, locale/currency formats and multilingual statements; measure wrong assertions, omissions and clarification burden separately |
| 3 | Validate the bank identity and action adapter in a sandbox | Ownership/permission revocation, expiry, duplicate/concurrent requests and timeout-before/after-commit evidence from the bank side, with authoritative status lookup |
| 4 | Extend governed policy coverage narrowly | Approved sources, effective-date boundaries, rule-premise tests, version conflict cases and reviewed customer explanations for each new supported conclusion |
| 5 | Harden state and operational controls | Typed state contracts, broader invalid-transition tests, controlled policy/config changes, bank-approved observability, secret management and retention |

A larger language model would not be the first next step. The present evidence
first calls for stronger unseen evaluation and dependable guided collection.
Any later model change should demonstrate incremental value over that baseline
without moving confirmation, policy execution or action authority into the model.

## AI-assisted development disclosure

Codex was used interactively to draft and edit Python implementation, synthetic
scenario generators, tests, evaluation scripts and documentation, and to run
checks in the local workspace. The conversation also guided iterative changes to
the Streamlit journey, evidence controls, policy gates and failure handling.
AI assistance was therefore substantial; this is not represented as a codebase
written entirely without generated contributions.

AI-generated implementation is not an authoritative policy or correctness
source. Generated labels and scenarios are development artefacts, not bank
adjudication. Tests can reproduce shared assumptions, so passing generated tests
is weaker evidence than independent review. The retained parser failure and
mandatory-review failures demonstrate why generated code and polished workflows
needed challenge rather than acceptance based on appearance.

This document distinguishes the use of AI to build the prototype from the use of
a model inside the product. During application runtime, both extraction and
evidence proposal default to deterministic code. Optional local model output is
validated and remains advisory. Policy execution, review requirements and
consequential action checks remain explicit code.

### Personal judgement example: choosing deterministic techniques first

The author confirmed the personal design judgement as “prefer deterministic
first.” The following account reflects that choice and the recorded project
direction; the evaluation findings are subsequent evidence, not a claim that the
author predicted the model's measured performance in advance.

> I used AI assistance to develop the system, but I set a deterministic-first
> constraint on the design. My direction was depth over breadth, evidence over
> assumption and control over autonomy. I wanted the system to collect and verify
> evidence, ask questions when it was uncertain and make consequential behaviour
> explicitly testable.
>
> I therefore narrowed the role of the language model in the AI-assisted design.
> Transaction identification, policy execution, workflow control and case creation
> use deterministic code. A language model may suggest extracted details or a
> permitted read-only evidence lookup, but it cannot establish account facts,
> decide eligibility or authorise an action. This was a deliberate design choice,
> rather than treating the availability of an LLM as a reason to use it throughout
> the journey.
>
> The later extraction evaluation reinforced that judgement. The 135M model
> produced structurally valid outputs but contributed no validated fields on the
> fixed probes. The combined path initially looked much stronger because the
> deterministic parser was doing the useful work. Separating those measurements
> made the limitation visible. The implementation was then changed so extraction
> defaults to deterministic logic and the model remains an explicit optional mode.
>
> The trade-off is more explicit rules and potentially more clarification for
> unsupported phrasing. I accept that cost in this prototype because a visible
> question is preferable to an unsupported assertion entering the dispute
> workflow. The decision should be revisited only with evidence of incremental
> benefit while preserving the same policy and action controls.

This is an example of materially constraining an AI-assisted design. It does not
claim that a particular earlier generated message proposed fully autonomous
banking actions, or that the author manually wrote every resulting code change.
The author supplied the design priority; Codex assisted with implementation and
validation. The recorded results support that priority within the tested scope.

## Submission claim

The defensible claim is a reproducible, controlled synthetic prototype whose
evaluation exposed real defects and led to specific improvements. The design
makes uncertainty and action authority visible. It is not yet a validated bank
dispute service, a reliable general language interpreter or a calibrated fraud
system. The next gains should come from independent evidence and bank contract
validation, rather than expanding autonomy.
