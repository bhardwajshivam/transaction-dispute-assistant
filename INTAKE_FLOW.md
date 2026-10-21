# Must-know details and confirmed search

Flow: issue → accessible card → description → suggested extraction → missing-field clarification → explicit confirmation → card-scoped SQL candidates → customer selection → evidence and policy workflow.

## Checklist

| Issue | Required to search | Optional facts retained for later |
|---|---|---|
| Unrecognised | Payment date/range + charged amount/currency or merchant | Expected amount, reference |
| After cancellation | Charge date/range + charged amount/currency or merchant | Cancellation date, expected amount |
| Multiple charges | Charge date/range + charged amount/currency or merchant | Other reported details |
| Wrong amount | Charge date/range + amount actually charged + charged currency | Expected amount/currency, merchant |
| Missing refund | Original purchase date/range + original purchase amount/currency or merchant | Expected refund amount/currency, reported processing date |
| Different issue | Description, then whether a transaction is involved | If yes, collect date and identifier; otherwise no search |

A selected card is required for all current transaction searches. An exact TX reference is an alternative to the date/amount checklist. Search-by-reference is explicitly identified in confirmation. All supplied search details remain customer assertions until checked against bank records.

## Extraction boundary

A conservative deterministic parser recognises explicit amounts, references and dates by default. Optional Ollama `smollm2:135m` extraction proposes typed fields with exact source spans only when explicitly enabled. Known deterministic spans and valid model spans are combined; disagreements on a field are clarified rather than resolved by arbitrary overwrite. Model values cannot authorise an action or change review requirements.

Dates are normalised only from explicit dates; uncertain/relative dates are not invented. A cancellation date never supplies the charge date; a refund date never supplies the original-purchase date. A date fragment cannot become a charged amount. Money uses decimal strings and integer minor units for SQL matching. Current search supports listed two-decimal currencies; broader currency minor-unit rules remain future work. Currencies are not inferred from account currency or a bare `$`.

Required missing fields are asked one at a time. A date range can be supplied as `15-10-2026 to 17-10-2026`. Exact TX references can be entered instead of unknown date details. Unknown required details can route to assistance. The date snapshot is fixed to 20-10-2026.

## Search gate

The backend returns no candidates until `search_confirmed` is true and the current fields/card exactly match the recorded confirmation. Query filters are parameterised, permission-scoped and exact. Expected amounts and refund amounts never filter original debits. Multiple candidates are shown without automatically selecting one; no matches do not cause silent date/amount relaxation. Search failure is reported separately from a successful empty result.

Edit resets current search fields and confirmation, while earlier statements remain in concern events. Already-provided expected amounts/currencies and cancellation/refund dates are reused in downstream questions. Other evidence answers still follow the guided workflow; broad natural-language understanding of every answer is not implemented.

## Validation and observed model defect

Offline tests cover missing fields, amount roles, date roles, partial refunds, date ranges, ambiguous currency, exact references, corrections, pre-query confirmation, cross-card access, empty results, lookup failure, hallucinated spans, model failure and the complete Streamlit confirmation sequence.

Historical smoke checks (combined parser/model results, not model-only accuracy) were run after downloading smollm2:135m:

- “I was charged £10 instead of £8” produced charged GBP 10 and expected GBP 8, leaving the payment date missing.
- “I cancelled on 01-10-2026 but was charged GBP 12.99 on 16-10-2026” retained the correct two dates and charge. The model also proposed an incorrect amount-role span; validation rejected it, retaining the supported parser result.

These checks demonstrate a real failure being contained, not general model accuracy. Source-span checks cannot prove every semantic interpretation correct; customer confirmation and later evidence verification remain necessary. Merchant matching uses literal trading-name/descriptor matching, not a general semantic retrieval system. Refund evidence is synthetic, and full eligibility policy execution remains incomplete.

The later 14-case evaluation supersedes those smoke checks as extraction evidence: model-only validated recall was 0%; after the parser correction, deterministic extraction passes all 14 fixed probes. See [LIVE_VALIDATION.md](LIVE_VALIDATION.md).

### Search identifiers

Merchant names and descriptors are context only and never search filters. Searches use the selected owned card, payment date/date range, actual charged amount and currency (original purchase amount for refunds), or an exact transaction reference. Merchant-only descriptions require the missing amount. Customer confirmation precedes lookup. The transaction-list filter uses reference, amount and date.

Currency is optional for lookup. When absent or ambiguous, confirmation explicitly states that the nominal amount will be matched across currencies without FX conversion. Known currency remains an exact filter. Every candidate displays its bank-recorded currency; the customer must choose a transaction. Missing currency does not establish currency agreement for any later eligibility assessment. Older saved search-currency questions allow “I don’t know / need help” to proceed to confirmation.
