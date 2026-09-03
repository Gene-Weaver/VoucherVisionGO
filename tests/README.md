# Quota and billing regression tests

Dependency-free tests for the quota, billing-credential, and model-default
logic in `app.py`. They extract the real functions from `app.py` via its AST
and run them against stubs, so no GCP/Firebase boot and no installed
requirements are needed.

Run these tests explicitly from the repository root. Their `tests_*.py` names
are intentional so standard `test_*.py` discovery does not launch them
automatically.

```bash
python3 tests/tests_model_defaults.py      # model defaults + which buckets a request charges
python3 tests/tests_pdf_quota.py           # per-page PDF metering, release, alerts, wording
python3 tests/tests_url_quota_release.py   # /process-url releases quota on every failure path
python3 tests/tests_billing_intent.py      # user-supplied Gemini/Vertex credential resolution
```

The event-analytics helper suite imports the complete application and therefore
requires the normal VoucherVisionGO runtime dependencies:

```bash
python3 tests/test_usage_events.py
```

Set `VVGO_APP=/path/to/app.py` to test a copy — used for mutation testing
(revert a fix in a copy and confirm the matching test fails).

## What they guard

| Regression | Suite |
| --- | --- |
| Omitting `engines`/`llm_model` yields an unmetered, server-funded run | `tests_model_defaults.py` |
| OCR-only / notebook runs charging for a parsing call that never happens | `tests_model_defaults.py` |
| Synchronous PDF uploads bypassing rate limits entirely | `tests_pdf_quota.py` |
| A failed PDF page keeping its reserved slot | `tests_pdf_quota.py` |
| Pro / Restricted Flash exhaustion during a PDF sending no alert | `tests_pdf_quota.py` |
| Quota messages naming an internal model key instead of the bucket label | `tests_pdf_quota.py` |
| `/process-url` leaking quota when the image never downloads | `tests_url_quota_release.py` |
| A user credential in a header or a misspelled field being silently ignored | `tests_billing_intent.py` |

## Limitations

The four `tests_*.py` suites are stubbed unit tests. They exercise real control
flow in the real functions, but not Flask routing, real HTTP status codes, or
Firestore transactions. Route-level tests need a runnable environment, which is
currently blocked by unpinned dependencies in `requirements.txt`.

Firestore composite indexes are deployment configuration, not test fixtures.
The tracked source of truth remains the root-level `firestore.indexes.json`.
