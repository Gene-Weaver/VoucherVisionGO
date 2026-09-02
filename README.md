# This is the server code for VoucherVisionGO, the API version of VoucherVision. 
This is likely **not** the repo that you want. If you just want to use the API, then please use the VoucherVisionGO-client repo.

## Billing Gemini usage to your own account

By default, Gemini calls are billed to VoucherVisionGO's shared keys and count against
the caller's per-model quota. Callers can instead have Gemini billed to their own
account. These are ordinary request parameters, so **any HTTP client works** — there is
nothing Python-specific about it.

Each credential can be sent as a **form field**, a **JSON body field**, or a **header**.
Form and JSON values take precedence over headers.

| Purpose | Form / JSON field | Header |
| --- | --- | --- |
| Google AI Studio key | `gemini_api_key` | `X-Gemini-API-Key` |
| Google Cloud project ID (Vertex AI) | `vertex_project` | `X-Vertex-Project` |
| Vertex AI region — always `global` | `vertex_region` | `X-Vertex-Region` |

### Option A — the caller's own Google AI Studio key

```bash
curl -X POST "https://vouchervision-go-738307415303.us-central1.run.app/process" \
  -H "X-API-Key: YOUR_VVGO_KEY" \
  -F "file=@your_image.jpg" \
  -F "engines=gemini-3.1-flash-lite" \
  -F "llm_model=gemini-3.1-flash-lite" \
  -F "gemini_api_key=YOUR_GEMINI_API_KEY"
```

Header form:

```bash
curl -X POST "https://vouchervision-go-738307415303.us-central1.run.app/process" \
  -H "X-API-Key: YOUR_VVGO_KEY" \
  -H "X-Gemini-API-Key: YOUR_GEMINI_API_KEY" \
  -F "file=@your_image.jpg" \
  -F "engines=gemini-3.1-flash-lite" \
  -F "llm_model=gemini-3.1-flash-lite"
```

### Option B — the caller's own Google Cloud project (Vertex AI)

Two one-time setup steps, covered in full in
[`webpage/Vertex_Passing_Guide/enable_vertex_billing.md`](webpage/Vertex_Passing_Guide/enable_vertex_billing.md):

1. Enable the Vertex AI API on the project and grant the **Vertex AI User** role to
   `vouchervision-vertex@vouchervision-387816.iam.gserviceaccount.com`.
2. Link the project ID to the VoucherVisionGO account under **API Key Management →
   Linked Google Cloud Projects**. Unlinked project IDs are rejected with HTTP 403.

```bash
curl -X POST "https://vouchervision-go-738307415303.us-central1.run.app/process" \
  -H "X-API-Key: YOUR_VVGO_KEY" \
  -F "file=@your_image.jpg" \
  -F "engines=gemini-3.1-flash-lite" \
  -F "llm_model=gemini-3.1-flash-lite" \
  -F "vertex_project=your-gcp-project-id" \
  -F "vertex_region=global"
```

Header form:

```bash
curl -X POST "https://vouchervision-go-738307415303.us-central1.run.app/process" \
  -H "X-API-Key: YOUR_VVGO_KEY" \
  -H "X-Vertex-Project: your-gcp-project-id" \
  -H "X-Vertex-Region: global" \
  -F "file=@your_image.jpg" \
  -F "engines=gemini-3.1-flash-lite" \
  -F "llm_model=gemini-3.1-flash-lite"
```

**Always use `vertex_region=global`.** It covers the entire Gemini model catalog;
regional endpoints do not carry every model. `vertex_project` and `vertex_region` must
be sent together — a project without a region is rejected with HTTP 400.

### No silent fallback to server keys

A request that *attempts* to supply its own credentials will never quietly fall through
to VoucherVisionGO's shared keys:

- A **misspelled** parameter (`gemini_key`, `vertexProjectId`, `X-Gemini-Key`, …) or an
  **empty** value returns **HTTP 400** naming the correct parameter, instead of running
  on server keys and returning 200. See `detect_unusable_billing_intent` in `app.py`.
- A credential that is read but **invalid or over quota** surfaces Google's own error.
  It is never retried on server credentials.
- Every response carries **`X-VV-Billing-Mode`**: `user_gemini`, `user_vertex`, or
  `server`. Check this header to confirm which account a request was billed to.

VoucherVisionGO's own auth inputs (`X-API-Key`, `Authorization`, `?api_key=`) are never
mistaken for Gemini credentials.

### Endpoint support

| Endpoint | `gemini_api_key` | `vertex_project` |
| --- | --- | --- |
| `/process` | yes | yes |
| `/process-url` | yes | yes |
| `/process-pdf-async` | **no** (HTTP 400) | yes |

Async PDF jobs do not yet accept `gemini_api_key`; use Vertex AI for those.
