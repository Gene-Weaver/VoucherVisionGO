# Required corrections before public-body conversion is complete

Recorded from review. Public-body conversion is **not** complete until these
are closed. Do not deploy the error-contract work with item 1 open.

## Open

Error Contract Normalization is complete. One item remains, decoupled from it:

### Dependency pinning (separate task)

`requirements.txt` is UTF-16 and **78 of 91 packages are unpinned**, including
flask / werkzeug / flask-cors as a set. `httpx[http2]` is pinned. There is no
lock file and the Dockerfile does not pin, so the working versions must be
captured with `pip freeze` against the deployed image digest before anything
else is pinned. That cannot be done from this repo alone.

## Closed

- **The primary downloader no longer swallows terminal verdicts.** Its broad
  `except Exception` caught the `TerminalFetchError` raised by
  `destination_check`, retried it, wrapped it in `RuntimeError`, and let the
  route fall through to the fallback — so a blocked or invalid redirect could
  still be retried and then downloaded by the second path. It now takes a
  `terminal_exceptions` tuple (passed in by the route, so it need not import
  `app.py`) and re-raises those immediately, ahead of every other handler.
- **One retry-owning layer.** The primary owns transient retries
  (`max_retries=3`); the route makes a single pass over primary-then-fallback,
  so the two cannot multiply.
- **The host allowlist is removed entirely.** `ALLOWED_IMAGE_DOMAINS` is not
  used in production, and it was also bypassable: the primary rejected a
  disallowed public host with `PermissionError`, which the fallback then
  fetched because it checked public routing but not the allowlist. The
  public-address rule is now the single boundary.
- **One shared redirect validator.** `validate_redirect_target()` is called by
  the primary (as `destination_check`) and by the fallback directly, so a
  destination refused by one path cannot be fetched by the other.
- **Both clients are closed reliably** — `with httpx.Client(...)` in the
  primary and `with requests.Session()` in the fallback, plus explicit closing
  of streamed responses and the spooled temp file on every path.
- **Bodies are streamed** into a `SpooledTemporaryFile` in both downloaders:
  small images stay in memory, larger ones spill to disk. This is a memory
  measure only — there is no maximum response size and no route-wide fetch
  budget. Ordinary connect/read inactivity timeouts are kept, and every
  response, client, session and spooled temp file is closed on all paths.
- **`httpx.Timeout` and `h2`.** The keyword-only construction raised
  `ValueError` before the retry loop, so the primary never ran and every
  request silently used the fallback. Fixing it exposed a second latent
  failure one line down: `httpx.Client(http2=True)` raises `ImportError`
  without the `h2` package, which was never declared. `requirements.txt` pins
  `httpx[http2]==0.28.1`.

- **The anti-bot downloader actually runs now.** Its
  `httpx.Timeout(connect=..., read=...)` raised `ValueError` before the retry
  loop, so `smart_fetch_image_as_filestorage()` never completed and every
  download silently used the `requests` fallback. Fixing that exposed a second
  latent failure one line down: `httpx.Client(http2=True)` raises `ImportError`
  without the `h2` package, which was never a declared dependency —
  `requirements.txt` now pins `httpx[http2]==0.28.1`. Verified end to end by
  decoding a real image through the function.
- **Guards added because it is now live.** `follow_redirects=False` plus a
  manual, validated redirect walk, and the route no longer passes
  `PORTAL_COOKIE` — it would have been sent to whatever caller-supplied host
  the URL names, and to every cross-domain redirect target.
- **Terminal failures are attempted once.** The route's three-attempt loop and
  its fallback both re-ran settled failures: a blocked or malformed
  destination could be tried three times and then handed to the second
  downloader. Both catch sites now use one shared
  `TERMINAL_FETCH_FAILURES` tuple and return immediately.
- **Redirect cookies survive.** The hardened fallback issued an independent
  `requests.get()` per hop, dropping any cookie a portal set on an earlier
  redirect — something the old automatic handling did for free. It uses a
  `requests.Session()` while still validating each hop manually.
- **A rejected redirect keeps its own verdict.** Every rejection was being
  converted into `BlockedDestination`, turning an invalid redirect target into
  403 instead of 400 and a redirect DNS timeout into 403 instead of 504. The
  `TerminalFetchError` from `check_url_destination` is now raised as-is.

- **Status Code Correction is complete.** Lifetime quota 503 -> **403** (a
  lifetime cap will not reset with time) at all four sites, including PDF page
  entries. Unsupported media type 400 -> **415**. Upstream provider failures
  split by blame through `classify_provider_failure()`: caller-supplied
  credentials give 401/403/429, the same failure on server keys gives 502/503.
  `/process-url` fetch failure is a classified error rather than a
  success-shaped 200. No client branches on any changed code; all surface
  through `describeApiError()` in the web UI.
- **Redirects are validated hop by hop** on that path: `allow_redirects=False`
  plus `check_url_destination()` on every target, closing the SSRF gap where a
  public host could redirect to a private or metadata address after the
  pre-flight check had passed.
- **Response encoder cleanup.** `app.json_encoder` (a no-op since Flask 2.3,
  proven by `/health` returning alphabetized keys) removed, and
  `app.json.sort_keys = False` set so error bodies stop being alphabetized
  while success envelopes are not. Verified against Flask 3.1.3.

- **Raw exception text is no longer returned to callers.** All five remaining
  `str(e)` sites are sanitized: PDF conversion, PDF page resize, the two
  generic provider paths (now via `classify_provider_failure()`), and image
  preparation. Each returns a fixed, actionable message and logs the exception
  under the request ID. `classify_provider_failure()` also splits blame — a
  credential the caller supplied yields 401/403/429, the same failure on server
  keys yields 502/503.
- **Typed aggregate failure.** `AggregateFetchError` keeps every attempt's
  outcome instead of `raise ... from`, and classification takes the most
  specific verdict by rank rather than by class-name precedence through a
  chain. A smart-fetch timeout plus a fallback unreadable image now reports 415.
- **A blocked redirect returns 403 immediately**, with no retry and no
  fallback. `BlockedDestination` / `InvalidFetchUrl` are their own types, not
  `PermissionError`, and typed guards are checked before any chain heuristic.
- **DNS rebinding.** Resolving before the request left a check-to-connect race
  because the client resolved again. Requests now connect to the validated
  address, carrying the original `Host` header and TLS SNI so certificate
  verification still happens against the real hostname (verified against
  example.com and swbiodiversity.org). A host resolving to both public and
  private addresses is rejected outright.
- **The httpx client is context-managed** in both fetchers, not closed on
  selected paths.
- **The browser no longer logs raw remote bodies**, and error text is rendered
  with `.text()`.

- **`/process-url` fetch failure is no longer a success-shaped HTTP 200.**
  The unreachable-URL path now classifies the failure once — after every retry
  and both permitted fetch methods have failed — and returns a top-level error
  with the right status: 400 `URL_INVALID`, 403 `URL_BLOCKED`, 415
  `INVALID_INPUT`, 502 `FETCH_FAILED`, 504 `UPSTREAM_TIMEOUT`, 500
  `INTERNAL_ERROR`. `URL_BLOCKED` is terminal: a refused destination never
  falls through to the fallback or another retry. The most specific cause wins, so a timeout nested
  under `smart_fetch`'s `RuntimeError` still reports 504 — which required
  chaining the cause in `anti_bot_fetch.py` (`raise ... from last_exc`).
  Messages are fixed sentences; raw exceptions go to the log under the request
  ID. Covered by `tests_fetch_classification.py`.

  **Caller-visible change:** a dead image URL previously returned HTTP 200 with
  an empty result, so `client.py` wrote a hollow JSON file and the web UI
  rendered an empty success. Both now surface a real error.

- **`payment_inference: "not_processed"` — authorized by the maintainer** in
  response to a direct request for authorization (after Claude twice recorded a
  premise-correction and a recommendation as approval; neither was). The field
  is a live, string-valued key in every result envelope, so the sentinel
  preserves both its presence and its type while removing the false-payer
  report. No code change was required. The four-value enum is documented in the
  root `README.md`; consumers switching exhaustively on it need a
  `not_processed` branch. Error bodies continue to omit the field, since their
  key set already varies by error type.

- `payment_inference` reported when no inference began — fixed. Every public
  response shape now goes through `current_payment_inference()`, which returns
  `not_processed` unless `mark_inference_started()` ran immediately before a
  provider call. PDF pages reset the marker per page so a failed page cannot
  inherit the previous page's payer, while request-scope reporting keeps the
  real payer's label. Covered by `tests_error_envelope.py` and
  `tests_error_sites.py`.
- Nested PDF page failures lacked the envelope — fixed via `_pdf_page_error`;
  failures from `process_image_request` now carry their inner envelope through
  instead of being flattened to a bare message.
- `expected <= got or not got` passed when a status vanished — fixed to require
  presence, and mutation-tested.
- "Prose unchanged" was asserted without a baseline — now checked against
  `tests/error_prose_baseline.json`, captured from the commit preceding the
  conversion, comparing **occurrence counts** so rewording one of two identical
  strings is caught.
