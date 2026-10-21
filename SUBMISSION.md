# Submission and clean-room verification

The source archive is `dist/transaction-dispute-assistant.zip`; its adjacent
`.zip.sha256` file contains the archive checksum. Build/rebuild it with:

```sh
python scripts/package_submission.py
```

The builder uses an explicit allowlist: Python source/tests, documentation,
requirements, policy/config JSON, synthetic fixture JSON and evaluation reports.
It includes `.env.example` and `.streamlit/config.toml`, not personal settings.
It excludes `.venv`, caches, `.env`, staff secrets, `.private`, encryption keys,
SQLite databases and journals, symlinks and the output directory itself.
`SUBMISSION_MANIFEST.json` hashes every included source/fixture/report file.
Archive member timestamps are fixed so unchanged inputs produce the same archive.

Do not submit the entire development folder or copy your existing database/key
into the archive. Regenerate runtime data and create a new local database/key.
Live model weights are external and optional; the default flow and main results
need no Ollama server. Python dependencies require package-index access or an
independently provisioned wheelhouse; dependencies are not bundled.

## Fresh-directory procedure

Extract the archive into an empty directory and enter `transaction-dispute-assistant`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python scripts/generate_data.py --seed 42 --cards-per-customer 2 --include-inr-example
python scripts/load_database.py
python scripts/convert_demo_currency.py data/disputes.sqlite
python -m unittest discover -s tests -q
python scripts/evaluate_deterministic_extraction.py
python scripts/evaluate_workflow.py
python scripts/evaluate_policy.py
python scripts/demonstrate_journeys.py
python scripts/validate_bank_integration.py
python scripts/generate_activity_data.py
python scripts/evaluate_activity_corpus.py --split development
python scripts/evaluate_activity_corpus.py --split evaluation
python scripts/evaluate_clustering.py --split evaluation
python -m streamlit run app.py
```

Run the generation/loader on a fresh directory. A second loader run intentionally
refuses to overwrite an existing database; skip it when reopening the app.
`--replace` is only for deliberately discarding an expendable demo database.
JSON remains the generator's original currency; relabelling the demo database
changes nominal currency codes, not amounts or FX values. Activity corpus JSON
retains its documented GBP/INR mix.

Expected results: 204 regression tests pass; deterministic extraction 14/14;
workflow 47/47 with zero observed critical errors; policy 14/14; demonstration
journeys 8/8; simulator contracts 46/46; activity rules 78/78 in each split.
Clustering reports descriptive status/signal counts, not fraud accuracy.
See [DEMO_JOURNEYS.md](DEMO_JOURNEYS.md) for the required demonstrations.

The optional live command `python scripts/evaluate_live_extraction.py` requires
a separately installed local model/server. Its current exit code is deliberately
1 because model quality failed, despite successful parser rescue. Likewise
`python scripts/validate_bank_integration.py --require-production` exits 2:
real bank validation is absent. These are documented limitations, not commands
to suppress from the report.

## Verification evidence

`SUBMISSION_VERIFICATION.json` records the actual clean-directory verification,
including commands, exit codes and archive content checks. Dependency installation,
generation and tests must be exercised in that fresh environment; a copied
`.venv` or an environment using system site packages is not a clean setup test.
The verified source-content fingerprint excludes that verification record to
avoid a self-referential hash. The archive manifest remains the authority for
the final packaged files. Synthetic metrics are not a production-readiness claim.

The initial clean run exposed a representative UI-test timeout at Streamlit’s
three-second default; that test now allows 15 seconds without changing its
assertions. Reproducibility review also found the base manifest included unrelated
reports; generation now hashes only owned outputs, with an extended regression
check. These changes are included in the verified package.
