# Privacy and security controls

This is a synthetic-data prototype, not a production banking security certification. Do not enter real customer data. The following controls are implemented and tested; limits are stated explicitly.

## Customer input and model boundary

`privacy.py` performs deterministic minimisation. Detected email addresses, long phone/card/identifier numbers, IBAN-like strings and some explicitly labelled government identifiers, names and addresses are replaced with typed placeholders. Amounts, decimal values, supported dates and transaction references remain usable.

Detected PIN/CVV/OTP/password/access-token disclosures block the submitted message before model processing or concern persistence. The customer receives a request to resend without the secret. Other detected identifiers are redacted before conversation processing. `concern_extraction.extract()` and the local Ollama transport also apply protection when called directly. Source spans are validated against the sanitised text; placeholder values cannot become extracted search fields.

This detector is deliberately conservative and **not exhaustive**. It can miss unusual formats, unlabeled names/addresses and contextual personal information, or redact a long legitimate identifier. The customer can correct useful details. Regex checks are not an anonymity guarantee or the sole protection. Raw submission text necessarily exists transiently in browser/server memory before screening; it must not enter debug/error logs.

## Stored concerns and evidence

Current concern snapshots, customer-event text, compact event digests and handoff JSON use authenticated Fernet encryption through `cryptography==50.0.2`. Full conversation snapshots are no longer repeated in every new event. Legacy concern payloads are sanitised and sealed on access, and old full event snapshots are reduced to state/digest metadata. Migration is atomic and does not delete concerns.

Query metadata (opaque IDs, ownership, timestamps, review reason codes and audit operations) remains clear for access checks. Generated accounts/transactions/merchant fixtures are still plaintext **synthetic** records. This is not whole-database encryption. Production needs approved encrypted database/storage and backups, plus managed keys.

By default a local key is created in `data/.private/concerns.key`, with directory mode 0700 and file mode 0600; the database is also set to 0600. Tests use separate temporary keys. `.private`, keys and SQLite files are excluded from Git. `CONCERN_ENCRYPTION_KEY` can instead supply an externally managed Fernet key. After migration, changing to another key without a rotation procedure will fail. Missing, invalid or unauthenticating keys fail closed; the application does not overwrite encrypted records with plaintext.

**Preserve the key separately and securely. Losing it prevents reading existing histories.** A key stored on the same machine does not protect against compromise of that user/process or copying the key alongside the database. Production key rotation/KMS/HSM integration is not implemented. SQLite secure-delete reduces residual database pages; it cannot guarantee physical erasure on SSDs or removal from previous backups.

Migrate/harden existing records without deleting cases:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/privacy_maintenance.py
```

Restart Streamlit in this virtual environment. Do not use database `--replace` to enable privacy controls.

## Representative access

Workspace selection no longer grants access. Representative views require a server-configured high-entropy staff token, a server-issued 15-minute session principal and an allowed customer scope. Tokens are not echoed or saved; comparisons use constant-time SHA-256 checks against a configured hash. After five failed attempts a session-local cooldown applies. The gate, scope and expiry are checked in queue/read/export services, not only the screen. Session-local cooldown is not distributed brute-force protection.

For the local demo:

1. Generate/store a random 32–512 character token using your password manager.
2. Run `python scripts/staff_token_hash.py`, entering that token privately.
3. Export the returned `STAFF_ACCESS_TOKEN_SHA256` assignment in the server terminal, and optionally `STAFF_ALLOWED_CUSTOMERS=C-001`.
4. Start Streamlit and enter the token under Representative workspace. Sign out when finished.

Only internal actor/customer references appear in audit events. No default staff password is provided. This shared-token demo gate is not bank SSO/MFA or representative assignment management. Customer identity is still fixed synthetic C-001; production customer authentication must come from the bank session. The role selector is not a production authorisation boundary.

## Exports, sessions and logging

Customer history exports use an explicit allowlist: redacted messages/customer updates, reported details, confirmed criteria and routing/review status. Raw evidence payloads, model prompts and execution traces are excluded. Representative packages are redacted, access-controlled and separately scoped. Read/export-request audits contain actor/reference, operation, outcome and time, without message bodies. An export-request event does not claim a completed browser download.

Internal debug panels are hidden by default. `SHOW_INTERNAL_DEBUG=1` is for trusted synthetic-data development only. Sanitised snapshots are still sensitive financial case data. Session state can be cleared with End session; after 15 minutes of inactivity it clears on the next server interaction. This is not an immediate visual screen lock. Already-delivered downloads cannot be recalled; production requires authenticated file delivery and bank-approved endpoint controls. The application does not configure OS, reverse-proxy or third-party debug logging automatically.

Ollama is called on loopback, with no model endpoint override or automatic retries/downloads. Local inference does not make the rest of the system private. Production deployment still requires TLS, authenticated infrastructure, isolation and egress controls. No real callback or contact-profile lookup is implemented.

## Retention and preservation

There is no invented universal retention period and no automatic deletion schedule. A local administrator supplies a bank-approved period. The command defaults to a retention dry run:

```sh
# 30 is an illustrative test value, not a bank retention recommendation.
python scripts/privacy_maintenance.py --retention-days 30
# Only after reviewing and authorising that policy:
python scripts/privacy_maintenance.py --retention-days 30 --execute
```

The operation uses last-update timestamps, locks against concurrent changes and skips preservation holds. It deletes expired concern snapshots, events, review rows and handoff packages together. Minimal audit IDs remain for accountability; audit retention must be governed separately. Hold a concern explicitly:

```sh
python scripts/privacy_maintenance.py --hold-concern CON-EXAMPLE
```

Local CLI access assumes an authorised administrator with filesystem access. Exported copies, sessions, logs, attachments, operating-system snapshots and backup expiry require separate operational management. No claim of complete erasure is made.

## Verification

Run `python -m unittest discover -s tests -v` in `.venv`. Tests cover secret rejection, redaction before model/storage, preservation of INR 200 and 19-10-2026, encrypted storage/migration, missing/wrong keys, permissions, compact events, safe export fields, staff login/scope/expiry, metadata audits, dry-run retention and preservation holds. These tests do not establish exhaustive PII detection or regulatory compliance.

References: [OWASP logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html), [OWASP cryptographic storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html), [Fernet authenticated encryption](https://cryptography.io/en/stable/fernet/).
