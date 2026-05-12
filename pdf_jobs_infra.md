# Async PDF Jobs Infra Notes

This feature expects the following infrastructure/config in deployment:

## Required env vars

- `PDF_JOBS_GCS_BUCKET`
  Use a bucket dedicated to async PDF job artifacts.
- `PDF_JOBS_QUEUE_LOCATION`
  Defaults to `us-central1`.
- `PDF_JOBS_CONTROL_QUEUE`
  Defaults to `pdf-control`.
- `PDF_JOBS_PAGE_QUEUE`
  Defaults to `pdf-pages`.
- `PDF_JOBS_PUBLIC_BASE_URL`
  Public app base URL used in email download links.
- `PDF_JOBS_TASK_TARGET_BASE_URL`
  Base URL Cloud Tasks should call for internal worker routes.
- `PDF_JOBS_TASK_SERVICE_ACCOUNT_EMAIL`
  Service account email used for Cloud Tasks OIDC tokens.
- `PDF_JOBS_INTERNAL_SECRET`
  Shared secret added as `X-Pdf-Task-Secret` on internal worker calls.

## Cloud Tasks queues

Create two HTTP queues:

- `pdf-control`
  Use for split/finalize/email tasks.
- `pdf-pages`
  Use for per-page processing fan-out.

Recommended starting settings:

- `pdf-control`
  Lower concurrency, e.g. `maxConcurrentDispatches=2`
- `pdf-pages`
  Higher concurrency, e.g. `maxConcurrentDispatches=16`

Tune based on Cloud Run capacity and model throughput.

## Firestore TTL

Enable Firestore TTL on:

- collection: `pdf_jobs`
- subcollection: `pdf_jobs/*/pages`
- field: `expires_at`

The app writes `expires_at = created_at + 7 days`.

## GCS lifecycle

Apply a lifecycle rule to the async PDF jobs bucket or prefix:

- delete objects older than `7` days

The app stores artifacts under:

- `pdf-jobs/<job_id>/original/...`
- `pdf-jobs/<job_id>/pages/...`
- `pdf-jobs/<job_id>/results/...`
- `pdf-jobs/<job_id>/bundle/...`

## Internal worker routes

These routes are intended for Cloud Tasks only:

- `POST /internal/pdf-jobs/<job_id>/split`
- `POST /internal/pdf-jobs/<job_id>/pages/<page_index>/process`
- `POST /internal/pdf-jobs/<job_id>/finalize`
- `POST /internal/pdf-jobs/<job_id>/send-email`

They validate:

- `X-CloudTasks-TaskName`
- `X-Pdf-Task-Secret` when configured
- OIDC bearer token when `PDF_JOBS_TASK_SERVICE_ACCOUNT_EMAIL` is configured
