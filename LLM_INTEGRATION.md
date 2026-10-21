# Local Ollama integration

## Start the assistant

Install Ollama from https://ollama.com/download if needed. Start the Ollama app, or run `ollama serve` in a separate terminal if the service is not already running. Download the model once:

```sh
ollama pull smollm2:135m
```

Then, from the project directory:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
export EVIDENCE_PROPOSER_MODE=ollama
export OLLAMA_MODEL=smollm2:135m
python -m streamlit run app.py
```

An already-installed local model can be used instead, for example:

```sh
export EVIDENCE_PROPOSER_MODE=ollama
export OLLAMA_MODEL=llama3.2:1b
export OLLAMA_TIMEOUT_SECONDS=60
python -m streamlit run app.py
```

No API key or optional Python SDK is required. The app does not download models or start Ollama automatically. A missing model/service causes deterministic fallback. Use a new concern after fixing the service because the concern-local failure circuit is persistent. The first request may take longer while Ollama loads the model.

To use the deterministic workflow:

```sh
export EVIDENCE_PROPOSER_MODE=deterministic
export CONCERN_EXTRACTION_MODE=deterministic
python -m streamlit run app.py
```

`.env.example` documents configuration; `.env` is not automatically loaded. The old `openai` mode is no longer supported and falls back as an invalid mode. Existing concern records are preserved, including historical execution metadata.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CONCERN_EXTRACTION_MODE` | `ollama` | Local description extraction; `deterministic` disables model processing |
| `EVIDENCE_PROPOSER_MODE` | `deterministic` | `ollama` enables the local proposer |
| `OLLAMA_MODEL` | `smollm2:135m` | Installed local model tag; cloud-labelled model names rejected |
| `OLLAMA_TIMEOUT_SECONDS` | `30` | Finite transport-operation timeout from 1–120 seconds |
| `OLLAMA_MAX_OUTPUT_TOKENS` | `256` | Generation limit from 128–1024 tokens |

Endpoint is fixed to `http://127.0.0.1:11434/api/chat`; no remote endpoint configuration, environment proxies or redirects are used. No automatic retries or model pulls occur. Timeouts are transport-operation timeouts, not an absolute deadline for a complete multi-call evidence loop. A timed-out inference may continue inside the Ollama server.

## Architecture and controls

1. `model_proposer.py` builds bounded metadata context and a strict proposal contract.
2. `ollama_backend.py` calls the native chat API with `format` set to JSON Schema, `stream=false`, `temperature=0` and a generation-token limit.
3. `orchestration.py` verifies ownership locally before calling a proposer, and the evidence controller independently validates every returned tool proposal.
4. Allowed read-only tools gather synthetic evidence; decisions, mandatory review and actions remain deterministic.
5. A failed/rejected proposal opens the concern-local circuit; remaining calls use the baseline. No live connection to a bank or human representative is implied.

The backend rejects incomplete output, malformed/oversized JSON, unexpected tool calls and proposals outside the supplied choices. Server errors are sanitised; raw server messages are not persisted. A fixed loopback address and rejection of cloud-labelled names support local deployment, but the operator must still use genuine local model weights and an appropriately configured Ollama installation.

The model sees the selected synthetic transaction reference, workflow step, evidence statuses and permitted proposals. The evidence proposer excludes complaint text, identity, credentials and raw bank evidence. The separate intake extractor screens and redacts the customer description before local processing; detected authentication secrets are blocked. See SECURITY.md. Trace metadata persists with concern notes and handoff packages. Evidence proposals and complaint extraction use separate schemas and authority boundaries. `concern_extraction.py` attempts local smollm2:135m extraction by default, with deterministic parser support and guided fallback; `intake.py` validates them and requires confirmation before searching.

SmolLM2 135M is small; structured output validation does not establish semantic reliability. Invalid proposals must continue to fall back rather than weakening validation.

## Implementation stages

- Step 1 complete: bounded model contracts and deterministic fallback.
- Step 2 complete: local Ollama transport, replacing the earlier API adapter.
- Step 3 complete: application/controller integration with local ownership preflight.
- Configuration is intentionally environment-based; an interactive mode switch is not part of the submission scope.
- Step 5 complete within synthetic scope: 47 shared-service workflow journeys and separate live extraction probes; see EVALUATION.md and LIVE_VALIDATION.md.

## Verify

```sh
python -m unittest discover -s tests -v
```

Transport tests use mocked local HTTP responses and need neither a model nor a running server. Model availability/inference requires a separate local check. Tests cover malformed output, wrong references, timeout, missing models, no retries, loopback routing, controller fallback, required review and persistence.

References: [Ollama chat API](https://docs.ollama.com/api/chat), [SmolLM2 135M model](https://ollama.com/library/smollm2:135m).

Historical connectivity smoke check: the already-installed `llama3.2:1b` returned a valid proposal for synthetic transaction metadata in approximately 31 seconds (60-second timeout). This checks connectivity and response shape only, not model reliability. `smollm2:135m` was subsequently installed and checked with two synthetic extraction descriptions; see INTAKE_FLOW.md.

Historical live validation found 0% validated model field recall on the old prompt. The current local extraction default is Ollama with parser support. Fresh versioned measurements and retained failures are in [prompt_v2/REPORT.md](data/live_extraction_evaluation/prompt_v2/REPORT.md); useful model contribution is still limited. Deterministic-only mode remains available.

## Extraction trace contract

`DISPUTE-EXTRACTION-PROMPT-2.0`, `DISPUTE-EXTRACTION-SCHEMA-1.0` and `DISPUTE-EXTRACTION-VALIDATOR-1.3` identify the current contract. Prompt hashes cover system instructions and per-issue guidance; schema hashes cover the structured output contract. New traces retain those identifiers on deterministic, model, failure and blocked-secret paths. Existing saved traces are historical and are not rewritten.

Model identity records the configured tag and matching returned tag when available; unexpected returned identities and tool calls cause fallback. Runtime chat responses do not include a model digest, so the trace states that limitation explicitly. The live evaluator additionally captures model digest before and after each suite. Update the relevant version whenever its behaviour changes and rerun evaluation.

Validator 1.3 additionally allowlists diagnostic codes; step-3 live reports retain the measured 1.2 source fingerprints. This diagnostic change is covered by privacy regression checks, not a new claim of live model quality.
