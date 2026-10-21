# Using the Transaction Dispute Assistant

This guide is for running and reviewing the synthetic prototype locally. It does
not connect to a bank, issue refunds, block cards or arrange real callbacks.
Use synthetic information only. The demo reference date is 20 October 2026;
future dates relative to that snapshot are intentionally rejected.

## 1. Install and prepare the demo

Requirements: Python 3.10 or newer, a terminal and a browser. Python 3.10 was used
for the recorded clean-environment verification. The default application needs
no model server or API key. Package installation requires an internet connection
or a separately provisioned wheelhouse.

After cloning this repository, enter its directory and run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python scripts/generate_data.py --seed 42 --cards-per-customer 2 --include-inr-example
python scripts/load_database.py
python scripts/convert_demo_currency.py data/disputes.sqlite
```

On Windows, use `py -m venv .venv` and activate with
`.venv\Scripts\Activate.ps1` in PowerShell. The remaining Python commands are the
same. The recorded clean-room run was on macOS; Windows-specific installation
and browser behaviour have not been validated.

Generation writes fictional account/transaction/evidence JSON. Loading creates
`data/disputes.sqlite`; the final command relabels synthetic GBP financial fields
to INR without changing nominal amounts. This is not FX conversion. The optional
anchor is TX-999001 for INR 200.00 on 19 October 2026.

Run the loader only when creating a new database. It deliberately refuses to
overwrite an existing database. Do not use `--replace` just to restart the app:
it discards saved concern, handoff and case state in an expendable demo database.

## 2. Start and stop the application

```sh
source .venv/bin/activate
export CONCERN_EXTRACTION_MODE=deterministic
export EVIDENCE_PROPOSER_MODE=deterministic
python -m streamlit run app.py
```

Open the URL printed by Streamlit, normally `http://localhost:8501`. The exports
make the intended mode explicit; both modes already default to deterministic.
On PowerShell, use `$env:CONCERN_EXTRACTION_MODE="deterministic"` and
`$env:EVIDENCE_PROPOSER_MODE="deterministic"` instead of `export`.

To stop the server press Ctrl+C in its terminal. To return later, reactivate the
virtual environment and run Streamlit again; do not regenerate or reload data.
The sidebar's **End session** clears the current UI session; it does not erase
saved database records. **Start a new conversation** starts another concern.

If port 8501 is occupied, use:

```sh
python -m streamlit run app.py --server.port 8502
```

## 3. Raise a concern in the customer chat

Choose **Customer chat** in the workspace selector. Complaint options include an
unrecognised payment, charged after cancellation, multiple charges, wrong amount,
missing refund and a different issue. General policy information is a separate
opening option that does not need a card or transaction.

For a transaction concern:

1. Choose the complaint type and an accessible demo card.
2. Describe the concern when prompted. Typing is enabled after the opening
   choices. Dates can be entered as DD-MM-YYYY or an explicit supported ISO date;
   include currency with monetary amounts.
3. Answer only the required details that are still missing. Reported charge,
   agreed amount, original purchase and refund amount have different roles.
4. Review the displayed criteria and select **Confirm and search**. Editing
   criteria invalidates that confirmation. No transaction search occurs before
   confirmation.
5. Choose the relevant payment from the candidates. Multiple matches are not
   automatically collapsed to a single choice. With no matches, revise the
   details rather than assuming a payment or silently broadening the search.
6. Answer the branch-specific questions. The controller retrieves scoped
   evidence, checks applicable fictional policy and explains the supported route.

An exact transaction reference such as `TX-1001` can replace unknown date/amount
search details. It still needs explicit search confirmation and an accessible
selected card. `$` alone does not identify a currency. Relative or uncertain
dates are not silently converted into exact dates.

### Examples to enter

| Journey | Card and description | What to expect |
|---|---|---|
| Merchant recognition | CARD-001; `Please investigate payment TX-1001.` | Confirm search, select payment, then recognition/authorisation questions and merchant evidence |
| Wrong amount with ambiguity | CARD-001; `I was charged INR 42 instead of INR 40 on 15-10-2026.` | TX-1003 and TX-1004 both appear; choose the actual payment |
| Subscription cancellation | CARD-001; `Please investigate payment TX-1002.` | Select payment, recurring subscription, reported cancellation date and confirmation questions |
| Explicit INR fixture | CARD-001; `I do not recognise a payment of INR 200 on 19-10-2026.` | Search includes the generated INR anchor TX-999001 |

For cancellation, `13-10-2026` matches the constructed merchant request date.
A different reported date can correctly trigger material-conflict review.
See [DEMO_JOURNEYS.md](DEMO_JOURNEYS.md) for the eight required demonstrations
and exact automated references, including urgent-risk and failure paths.

## 4. Understand an outcome

Merchant details and historical spending signals are evidence, not proof of
permission or fraud. An anomaly signal cannot approve a refund or submit a case.
A low anomaly score cannot prove a transaction is safe. The model does not
execute policy or authorise an action.

Missing/conflicting policy or unverified evidence can cause clarification,
abstention or required specialist review. If specialist review is required,
customer satisfaction and declining assistance do not clear that requirement.
The application may interrupt ordinary follow-up questions to offer review.

General policy questions retrieve a small fictional, versioned corpus of
**evidence-collection guidance**. They do not establish real bank eligibility,
legal liability or refund deadlines. Unsupported questions should produce
clarification or referral rather than an invented conclusion.

## 5. Save history, request assistance or record a case

Replies save an encrypted concern with timestamped updates. Reopen a concern
through **Previous concerns → Open selected concern**. New conversations are
not automatically merged into an earlier concern, even if their wording matches.

**Download history**, at the top right, exports a minimised JSON conversation
record after a concern has been saved. Internal raw tool payloads are excluded.
Concurrent sessions updating the same concern must respect revision checks;
reopen after a conflict rather than assuming both updates were saved.

A human-assistance request needs its own explicit confirmation. It queues a
**simulated** handoff with assertions, evidence, policy, escalation reasons,
missing information and attempted actions. No actual representative receives a
message or calls the customer. Later notes remain separately visible to staff.

Where the narrow case-recording rules permit it, choose **Open a dispute case**,
review the preview, then **Confirm and create dispute case**. This records a
simulated case for review, not an approved chargeback or refund. Confirmation,
permission, current facts and policy are rechecked by the service. If the outcome
is unknown, check status and retry using the existing request; do not create new
requests in an attempt to bypass uncertainty.

## 6. Use the representative workspace

The representative view is locked until a server-side token hash is configured.
There is no default staff password. Create a random 32–512 character token in a
password manager, then run:

```sh
python scripts/staff_token_hash.py
```

Enter the token privately when prompted. Export the hash assignment printed by
the script in the terminal that starts Streamlit, and set the scope:

```sh
export STAFF_ALLOWED_CUSTOMERS=C-001
python -m streamlit run app.py
```

Switch to **Representative workspace** and authenticate with the original token.
Inspect confirmed assistance requests, the frozen initial handoff, later updates
and linked simulated cases. Sign out afterwards. Do not commit a token, its hash,
a `.env` file, `.streamlit/secrets.toml`, a database or an encryption key.

This is a shared-token demonstration gate, not bank SSO, customer authentication
or production role management. See [SECURITY.md](SECURITY.md) for the full access,
key backup, retention and privacy limitations.

## 7. Reproduce results

```sh
python -m unittest discover -s tests -q
python scripts/evaluate_deterministic_extraction.py
python scripts/evaluate_workflow.py
python scripts/evaluate_policy.py
python scripts/demonstrate_journeys.py
python scripts/validate_bank_integration.py
```

Recorded results: 186 regression tests, 14/14 deterministic extraction probes,
47/47 workflow cases, 14/14 policy cases, 8/8 demonstration journeys and 28/28
simulator contract checks. Reports are JSON/Markdown under `data/`; workflow
reports include source fingerprints, component checks, critical errors, weighted
costs and failure traces. These are synthetic development/conformance results,
not independently validated real-customer accuracy.

For richer history and clustering, follow [ACTIVITY_DATA.md](ACTIVITY_DATA.md)
and [CLUSTERING.md](CLUSTERING.md). Generate/load a separate database rather than
replacing saved demo histories. Rule evaluation has 78 constructed cases per
split; clustering defaults to shadow mode and reports distance, not probability.

## 8. Optional local Ollama mode

The recommended default requires no Ollama installation. If evaluating the
optional model, install Ollama separately and download its local weights:

```sh
ollama pull smollm2:135m
ollama serve
```

Start the service only if it is not already running. In another terminal:

```sh
source .venv/bin/activate
export CONCERN_EXTRACTION_MODE=ollama
export EVIDENCE_PROPOSER_MODE=ollama
python -m streamlit run app.py
```

The two settings are independent: extraction handles complaint text; the evidence
proposer suggests permitted read-only lookups. Neither controls actions. The
fixed endpoint is local loopback, and the app never downloads models itself.
`.env.example` documents settings but is not loaded automatically.

Run `python scripts/evaluate_live_extraction.py` for actual local-model probes.
The recorded 135M model had **0% validated field recall** and its invented spans
were rejected. Deterministic parsing rescued the combined result. The evaluator
therefore deliberately exits 1 for failed model quality; an unavailable/invalid
model response exits 2. Do not interpret successful fallback as model success.
Return to deterministic mode by unsetting those exports or setting both modes
to `deterministic`. Details are in [LIVE_VALIDATION.md](LIVE_VALIDATION.md).

## 9. Troubleshooting and safe reset

| Symptom | Resolution |
|---|---|
| `FileExistsError` from the loader | The database already exists; skip loading and start the app. Use `--replace` only for an explicitly disposable reset. |
| Missing database or tables | Run the generation and loading commands from the repository root using the active venv. |
| `ModuleNotFoundError` | Activate the venv, install requirements and use `python -m streamlit`, not an unrelated system Streamlit executable. |
| Wrong currency in manual examples | Run the README demo relabelling step on the fresh demo database; it does not convert amounts. |
| No matching transaction | Check selected card, purchase date, actual amount/currency and confirmed criteria; do not use expected/refund amount as the original charge. |
| Representative view locked | Configure the staff token hash in the server's environment, restart and enter the original token. |
| Cannot decrypt saved history | Restore the original key or correct external-key configuration. Do not generate a replacement key over existing encrypted history. |
| Ollama unavailable | Use deterministic modes, or start the local service and install the model explicitly. |
| Port already in use | Use another Streamlit port or stop the earlier server. |
| Session expired or save conflict | Reopen the saved concern and check case status before retrying; an action may have committed independently of chat saving. |

Resetting an expendable demo with `python scripts/load_database.py --replace`
erases operational database state. Back up any needed database and its matching
encryption key securely before doing so. Never publish either in GitHub.
