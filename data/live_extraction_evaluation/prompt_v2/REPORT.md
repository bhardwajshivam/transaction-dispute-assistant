# Extraction prompt v2: live measurement

Actual loopback Ollama 0.33.2, `smollm2:135m`. Full source/case hashes, model digest, versions, raw synthetic responses, rejected fields and field-role metrics are retained in each run directory. Both final runs observed the same model metadata before and after; this is not cryptographic runtime pinning.

| Suite | Valid responses | Model exact | Model precision / recall | Parser exact | Combined exact | Schema/transport fallback |
|---|---:|---:|---|---:|---:|---:|
| development14 | 14/14 | 7/14 | 100.0% / 37.9% | 14/14 | 14/14 | 0 |
| robustness12 | 11/12 | 5/12 | 100.0% / 51.7% | 11/12 | 11/12 | 1 |

## Interpretation

The 14-case suite is the unchanged development probe set. The 12 robustness probes were written during this development session before execution; failures then informed validator fixes. Both sets are now development regression cases, not independent held-out evaluation. Do not pool them into a generalisation accuracy claim.

Model-only exact matches include empty expected outputs. Only two nonempty-target cases in each final suite were extracted exactly by the model. Parser support is responsible for much of combined success. Field precision describes accepted fields after validation, not the correctness of all raw model proposals. Cases with rejected proposals remain visible in each summary and failed_outputs.json.

The final robustness run is marked UNAVAILABLE_OR_INVALID, not a clean success: `corrected_amount` hit the generation length limit and required fallback. Merchant context `Northstar` was missed by both paths; the expected label was retained. Merchant is context only and never a search filter. No accepted wrong fields were observed in these final runs; this is a small, developer-authored sample, not an assurance of safety.

## Preserved failures and improvements

`before_validator_development14/` and `before_validator_robustness12/` retain first measurements. Their source fingerprints describe the code tested then. Historical reports outside prompt_v2 are unchanged.

- Development: a reference was labelled merchant; unrelated original currency was accepted. Reference-as-merchant rejection and currency-role validation restored combined exact matches from 12/14 to 14/14.
- Robustness: negated charges became positive facts and amount conflicts left orphan currencies. Conservative clarification on narrow payment negations and conflict cleanup improved combined exact matches from 8/12 to 11/12.
- Remaining misses and generation failure are retained. Expectations were not changed to match outputs. No new model training or framework was introduced.

## Reproduce

Start local Ollama with the installed model, then run each command separately:

```sh
python scripts/evaluate_live_extraction.py --output data/live_extraction_evaluation/prompt_v2/reproduction14
python scripts/evaluate_live_extraction.py --cases evaluation/extraction_challenge_cases.json --output data/live_extraction_evaluation/prompt_v2/reproduction12
```

Exit 0 requires model-only exact matches on all cases; exit 1 means measured model quality did not meet that criterion; exit 2 means unavailable/incomplete/invalid output or changed model metadata. The recorded final runs exit 1 and 2 respectively. Do not treat fallback success as a model-quality pass. Local inference can vary despite temperature 0; source/case fingerprints and actual outputs are retained.

## Trace identity and limits

Every extraction trace records prompt/schema versions and hashes, validator version, and configured/reported model tags when invoked. The chat API does not supply an immutable digest; runtime traces explicitly mark it unavailable. Live evaluations additionally record model digest and server metadata before/after. Deterministic and blocked-secret traces have no model identity. Versioning does not grant authority: all extracted details remain unverified customer assertions and transaction lookup still requires confirmation.
