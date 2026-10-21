# Consolidated data-quality audit

Reproduce: `python scripts/audit_data_quality.py`. Full counts, pairs, token associations and input hashes: `report.json`.

- Base transactions: 181; richer transactions: 2225.
- Structural/reference errors: 0.
- Activity customer overlap: 0; normalised exact cross-split input overlap: 0.
- Activity repeated inputs within split: {'development': 6, 'evaluation': 6} (intentional authorisation non-identifiability).
- Richer missing receipts: 417; missing order references: 79.
- Workflow similar-description pairs: 567; explicitly tagged counterfactual pairs: 3. Untagged pairs require review, not automatic deletion.
- Initial four-case text-only NB accuracy: 50.00%; majority: 25.00%. Too small for generalisation claims; the target is next question, not terminal route.

## Interpretation and action

Shared scenario families and templates remain. Customer-disjoint splits and no exact evidence overlap do not establish independent generalisation. Similarity is lexical, not a semantic duplicate detector. Token associations are reported as diagnostic signals, not proof of label leakage. No classifier from this audit is used by the application. Route balance and boundary family counts are in JSON; they are coverage inventories rather than evidence of complete policy coverage.

Structural and reference checks run on the actual generated JSON, not only copied reports. Labels remain hand-authored: this audit cannot establish independent policy correctness. Frozen new challenges have not been executed and require external review before any independence claim.

## Defects found and corrected

Previously observed: random missingness could erase supporting anchor records; constructed anchors are now protected. An accidentally repeated positive control was made temporally distinct. ISO date parsing once swallowed amount digits; supported month matching corrected it. Most recently, model extraction labelled a date phrase as merchant and hid valid transactions; merchant semantic validation and removal of merchant search filters fixed the failure. These are documented development observations, not newly discovered by this audit. See ACTIVITY_DATA.md, LIVE_VALIDATION.md and the step-1 observed_failure.json.

## Remaining limitations

External label adjudication, semantic paraphrase review, broader language coverage and complete policy-boundary coverage remain open. New live-model and end-to-end results belong to later stages. Do not interpret an empty structural error list as complete submission compliance.
