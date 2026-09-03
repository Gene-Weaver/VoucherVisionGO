# Quota, billing, and CORS regression tests

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
python3 tests/tests_error_envelope.py      # error payload/response builders and the taxonomy
python3 tests/tests_error_sites.py         # every processing-route error uses the envelope
python3 tests/tests_fetch_classification.py # URL fetch failures map to the right status
```

The web-UI error-display suite needs Node:

```bash
node tests/tests_webpage_error_display.js
```

`tests_guarded_fetch.py` drives the real fetch path against an in-process httpx
mock transport, so it needs the Flask/httpx virtualenv:

```bash
./.venv_cors/bin/python tests/tests_guarded_fetch.py
./.venv_cors/bin/python tests/tests_smart_fetch_e2e.py
```

`tests_smart_fetch_e2e.py` is the only suite that invokes the **complete**
`smart_fetch_image_as_filestorage()` and `/process-url` paths rather than
stubbing a layer. Every other suite mocks something; a dead code path or a
missing name shows up only here.

`tests_error_envelope.py` runs dependency-free as above, covering the payload
builder. Run it under the Flask virtualenv below to additionally exercise
`_error_response`; without Flask those checks report as skipped rather than
silently passing.

`tests_cors_policy.py` is the exception to "dependency-free": it drives real
OPTIONS and POST requests, so it needs Flask and Flask-CORS. It extracts
`app.py`'s actual CORS configuration and request hooks and mounts them on a
bare Flask app, keeping it isolated from the heavy runtime dependencies:

```bash
python3 -m venv .venv_cors && ./.venv_cors/bin/pip install flask flask-cors
./.venv_cors/bin/python tests/tests_cors_policy.py
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
| An error body reporting a payer when no provider call was ever made | `tests_error_envelope.py` |
| The `payment_inference` marker drifting from the provider call to function entry | `tests_error_envelope.py` |
| A legacy compatibility field shadowing `error` / `error_code` / `host` | `tests_error_envelope.py` |
| An unknown `error_code` raising instead of degrading to `INTERNAL_ERROR` | `tests_error_envelope.py` |
| `_error_payload` returning a Flask response and breaking helper `(dict, status)` contracts | `tests_error_envelope.py` |
| An error builder writing a CORS header and suppressing the real policy | `tests_error_envelope.py` |
| A processing route or helper regressing to a hand-built `{'error': ...}` dict | `tests_error_sites.py` |
| A dead image URL answered with HTTP 200 and an empty result | `tests_fetch_classification.py` |
| A blocked host retried or falling through to the fallback fetcher | `tests_fetch_classification.py` |
| A timeout misreported as a generic 502 because the cause chain was ignored | `tests_fetch_classification.py` |
| Raw exception text leaking into a fetch-failure message | `tests_fetch_classification.py` |
| A wrapped unreadable image reported as 502 instead of 415 | `tests_fetch_classification.py` |
| A filesystem `PermissionError` reported as a blocked host (403) | `tests_fetch_classification.py` |
| A malformed URL consuming retries, or reported 403 instead of 400 | `tests_fetch_classification.py` |
| Retry layers multiplying past the browser's 300s abort | `tests_fetch_classification.py` |
| The web UI showing only an HTTP status instead of the server's message | `tests_webpage_error_display.js` |
| Remote HTML reaching the DOM or the browser console | `tests_webpage_error_display.js` |
| A public host redirecting to a private or metadata address | `tests_guarded_fetch.py` |
| DNS rebinding between validation and connection | `tests_guarded_fetch.py` |
| A host allowlist creeping back in (removed: not used in production, and bypassable via the fallback) | `tests_guarded_fetch.py`, `tests_fetch_classification.py` |
| The two downloaders using different redirect validators | `tests_fetch_classification.py` |
| A settled failure (400/403/504) being retried, or falling through to the fallback downloader | `tests_route_fetch_behavior.py` |
| A rejected redirect collapsing 400/504 into 403 | `tests_route_fetch_behavior.py` |
| A public host redirecting to a private or metadata address | `tests_route_fetch_behavior.py` |
| An HTTP client or session left unclosed | `tests_fetch_classification.py` |
| A response body buffered whole instead of streamed to a spool | `tests_fetch_classification.py` |
| Portal cookies dropped between redirect hops | `tests_route_fetch_behavior.py` |
| `httpx.Timeout` regressing to the keyword-only form that raises | `tests_fetch_classification.py` |
| The anti-bot downloader following redirects unvalidated | `tests_fetch_classification.py` |
| `PORTAL_COOKIE` being sent to caller-supplied hosts | `tests_fetch_classification.py` |
| A lifetime quota answering 503 (retryable) instead of 403 | `tests_error_sites.py`, `tests_pdf_quota.py` |
| An unsupported media type answering 400 instead of 415 | `tests_error_sites.py` |
| `jsonify` alphabetizing error bodies again | `tests_error_sites.py` |
| A NameError or dead code path in the real smart fetcher | `tests_smart_fetch_e2e.py` |
| `PORTAL_COOKIE` silently dropped by address pinning | `tests_smart_fetch_e2e.py` |
| An RGBA image failing to save as JPEG, or losing quality=95 | `tests_smart_fetch_e2e.py` |
| `Retry-After` documented but not honoured | `tests_smart_fetch_e2e.py` |
| A terminal failure falling through to the fallback fetcher | `tests_smart_fetch_e2e.py` |
| Only the first resolved address being attempted | `tests_guarded_fetch.py` |
| An unbounded DNS lookup in front of a bounded fetch | `tests_guarded_fetch.py` |
| A blocked destination classified as 500/502 instead of 403 | `tests_fetch_classification.py` |
| Conflicting smart/fallback verdicts resolved by chain order | `tests_fetch_classification.py` |
| Raw provider text returned to a caller | `tests_error_sites.py` (baseline) |
| A helper returning a Flask response and breaking its `(dict, status)` contract | `tests_error_sites.py` |
| A call site inventing an `error_code` outside the closed taxonomy | `tests_error_sites.py` |
| An HTTP status changing during a body-only conversion | `tests_error_sites.py` |
| The rate-limit response dropping `gemini_pro_usage_*` and other legacy fields | `tests_error_sites.py` |
| Any result envelope naming a payer when no provider call began | `tests_error_sites.py`, `tests_error_envelope.py` |
| A PDF page inheriting the previous page's payer | `tests_error_envelope.py` |
| A nested PDF page failure regressing to a bare `{filename, error, status_code}` | `tests_error_sites.py` |
| Error prose silently reworded during a body-only conversion | `tests_error_sites.py` (baseline) |
| A CORS preflight response receiving no `X-Request-ID` (hook ordering) | `tests_cors_policy.py` |
| `X-Request-ID` missing from a response or from `expose_headers` | `tests_cors_policy.py` |
| A hand-written `Access-Control-*` header silently disabling the real CORS policy | `tests_cors_policy.py` |
| Preflight rejecting `X-Gemini-API-Key` / `X-Vertex-Project` / `X-Vertex-Region` | `tests_cors_policy.py` |
| A wildcard origin returned alongside `Access-Control-Allow-Credentials: true` | `tests_cors_policy.py` |
| Duplicate `Access-Control-*` headers from competing writers | `tests_cors_policy.py` |
| `X-VV-Billing-Mode` / `X-Request-ID` not exposed to browser callers | `tests_cors_policy.py` |

## Open corrections

`OPEN_CORRECTIONS.md` in this directory tracks review findings that are not yet
closed — no blockers are currently open. Its "Closed" section records the
maintainer-authorized `payment_inference` enum, including the `not_processed`
member.

The prose baseline is **complete**: every `error` value in the public
processing routes and helpers — 20 literal strings, 8 f-string templates and 8
bare expressions (including every `str(e)`) — collected from both the envelope
builders and any surviving dict literal, so the errors nested in the
`/process-url` success-shaped 200 are covered too. Only in-scope call sites
count; the builders' internal calls to each other are excluded.

`message` is baselined **separately** from `error` and the two are never
compared against each other, so moving text out of `error` into `message`
fails the check rather than satisfying it. One baseline entry is recorded as an
intentional removal, with its reason, in the test itself.

## Limitations

The four dependency-free `tests_*.py` suites are stubbed unit tests. They exercise real control
flow in the real functions, but not Flask routing, real HTTP status codes, or
Firestore transactions. Route-level tests need a runnable environment, which is
currently blocked by unpinned dependencies in `requirements.txt`.

`tests_cors_policy.py` issues real requests, but against a lightweight Flask
harness built from `app.py`'s extracted configuration — it is a unit test of
the CORS policy, **not** a full import or integration test of the deployed
application. It also pins nothing: it was written against Flask 3.1.3 and
Flask-CORS 6.0.5, and both are unpinned in `requirements.txt`, so a future
release of either could change the behavior it asserts. Pinning is tracked as
separate dependency work.

Firestore composite indexes are deployment configuration, not test fixtures.
The tracked source of truth remains the root-level `firestore.indexes.json`.
