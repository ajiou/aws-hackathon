# Smart Watchdog FastAPI backend

Implements the nine endpoints in [`docs/SPEC.md` §8](../docs/SPEC.md). All backend code, dependencies, tests, and setup configuration live in this **`backend/` directory**. Root-level and `infra/` files are owned by other team members and are not changed by this implementation.

Run the commands below from `aws-hackathon/backend`.

## Run locally

Python 3.12+ and uv:

```bash
uv sync --locked
uv run uvicorn main:app --reload --port 8000
```

Open **http://127.0.0.1:8000/docs** for Swagger UI. Use `main:app` with the backend directory as PyCharm's working directory. Alternatively, `uv run python local_server.py` honors `HOST` and `PORT`. The original `python backend/local_server.py` command also works from the shared root after installing the backend dependencies.

Without environment settings, the server uses `./out/serving` if present, otherwise the repository's `./frontend/mock`. Missing data produces `503 DATA_NOT_READY`; the server can start without AWS credentials. Both defaults resolve relative to the shared repository, independent of the working directory.

`uv sync` installs the backend and its test tools into `backend/.venv`. The team's root dependency file is independent. For a backend runtime installation with pip, run `pip install -r requirements.txt` from this directory.

Choose a dataset explicitly:

```bash
SERVING_DIR=../frontend/mock uv run uvicorn main:app --reload
SERVING_DIR=../out/serving uv run uvicorn main:app --reload
```

Frontend setting: `VITE_API_BASE=http://localhost:8000/api/v1`.

`.env.example` documents the environment variables. It is not loaded automatically. `CORS_ORIGINS` is a comma-separated list of exact origins; local defaults allow `localhost:5173` and `127.0.0.1:5173`. S3 mode defaults to same-origin access unless configured.

## API

All data routes use `/api/v1` and GET.

| Route | Behavior |
| --- | --- |
| `/meta` | Dataset version, weights, coverage and model metadata |
| `/parks` | Active parks; name search, repeated or comma-separated `town`, `type`, `tier`, finance-flag filter and pagination |
| `/parks/{park_id}` | Full record, including inactive parks; joins fees, finance and evaluations |
| `/parks/{park_id}/brief` | Offline brief; deterministic evidence-based template when missing or invalid |
| `/risk/top?k=50` | Active parks in ascending rank order, with reasons and finance flags |
| `/districts` | Precomputed district statistics |
| `/map` | GeoJSON points; town joins against park records when map properties omit it |
| `/curve` | Precomputed backtest data, preserved as supplied |
| `/worklist?week=2026-W37&k=50` | Saved weekly sheet or a current-week template built from ranked parks |

`page` defaults to 1, `size` to 50, and `k` to 50. `size` and `k` must be 1–200. Invalid values return 400. List sorting supports `risk` (rank ascending), `name` (ascending), and `pun_count` (descending); optional `dir=asc|desc` overrides the direction. `has_finance_flag=false` leaves the list unfiltered. Unknown towns return empty results.

The spec examples use `type`, while the reference mock and original handler use `institution_type`. Both are returned with the same value. Known legacy inconsistencies are normalized: non-applicable dimensions have null weights, and financial flags have `validated=false`. Null scores stay null. Empty risk reason arrays are preserved under §3.3's “at most 3” rule; templates explain missing reasons without inventing a reason code.

Every response carries a fresh `x-request-id`, logged with route, status, elapsed time and Lambda request id when available. Successful data responses include `x-data-version` and `Cache-Control: public, max-age=60`. Errors and details containing signed PDF URLs use `no-store`. The data-version header is empty if metadata could not be loaded. Errors have the frozen envelope:

```json
{"error":{"code":"PARK_NOT_FOUND","message":"查無此園所或資源","request_id":"..."}}
```

Invalid input is 400, absent resources 404, unsupported methods 405, unavailable data 503, and corrupt data/unexpected failures 500. Error bodies and application logs omit raw validation inputs, exception messages, bucket names, and stack traces.

## Serving data handoff

The backend reads only prepared serving artifacts. It never reads raw personal-data files, connects to a database, calculates model scores, or calls an LLM.

Required for the full API: `meta.json`, `scores.json`, `districts.json`, `map.json`, `curve.json`. `scores.json` must contain **all parks**, not the 50-record `risk-top.json` preview. Record collections accept an array, an `{"items": [...]}` envelope, or a park-id keyed mapping. `scores.json` may embed basic fields, or join against optional `parks.json` within the serving directory.

Optional artifacts:

- `briefs.json`: map keyed by park id or a record collection. Valid `source=llm|template` briefs are returned as supplied; invalid individual briefs or unsupported actions fall back to templates. A malformed file or PII violation fails closed.
- `fees.json`, `finance.json`, `evaluations.json`: de-identified record collections joined by `park_id`. Detail responses expose arrays; an absent source is `[]`. Evaluation counts are `null` when no evaluation records are available.
- `finance[].source_pdf`: an S3 key under `raw/pdf/`. With `DATA_BUCKET` configured, detail requests add a freshly generated `pdf_url` valid for 900 seconds. Local-only mode returns a null URL. Finance records must explicitly carry `validated=false`.
- `worklist.json`: a saved sheet with its actual ISO week. Current-week sheets can be expanded to `k` using ranked parks. Template rows have exactly three factual reasons and at most three actions grounded in recorded laws or approved capacity; no evaluation count is invented. Legacy short reason arrays and unsupported mock actions are repaired from the park's evidence.
- `worklist-2026-w37.json`: optional archived sheets, with lowercase filenames. An explicitly requested non-current week must match a saved sheet; otherwise the API returns 503. Latest data is never relabeled as historical data.

Omitted `week` uses the current ISO week in Asia/Taipei. A template's `generated_at` retains the source snapshot timestamp, so stale input remains visible.

Objects and validated park indexes are loaded lazily once per process, under a lock, and reused across requests and Lambda invocations. Missing required files are retried on the next request; optional-file absence is cached. Publish a coherent snapshot, then restart Uvicorn or change Lambda's `DATA_REVISION` environment value to refresh all caches. Do not mix files from different model runs.

The ETL must remove natural-person names before producing or uploading serving files, using the reference `etl/pii.py` for owner hashes. The backend rejects known person fields, invalid owner hashes, and explicit person labels, and projects worklist rows through an allowlist. This guard does **not** recognize every person name in unrestricted prose; upstream de-identification remains required. Report PDFs must also be suitable for publication to API users before upload.

Validate a snapshot before publishing:

```bash
SERVING_DIR=../out/serving uv run python validate.py
```

This checks response schemas, population/rank consistency, map references and decision templates. It does not validate the model's scientific accuracy. The provided mock curve and metrics are fixtures, not newly measured model results.

## Tests

```bash
uv run pytest -q
uv run ruff check .
```

The core suite uses synthetic fixtures and mocked S3, with no credentials or network access. An additional integration test exercises the complete reference mock when present. Coverage includes every route, filtering, pagination, schema failures, 400/404/503 paths, worklist weeks, privacy guards, concurrent cache reads, PDF signing and API Gateway v2 events. The installed Starlette test client currently emits upstream deprecation warnings; they do not affect test results.

## AWS handoff

[`template.yaml`](template.yaml) and [`Makefile`](Makefile) define a standalone backend package and optional API stack, with Python 3.12, 512 MB, a 10-second timeout, concurrency 10, read-only S3 access and a seven-day log group. Mangum exposes the same FastAPI app through `backend.app.handler`.

With AWS SAM CLI, Docker and competition credentials configured:

```bash
sam build --template-file template.yaml --use-container
```

This produces a Lambda artifact in `backend/.aws-sam/build/ApiFunction`. The custom build copies only backend Python modules and installs the locked runtime dependencies; it does not package data, tests, or local credentials.

The shared `infra/` files remain unchanged. Their original source-only packaging command does not install FastAPI/Pydantic/Mangum, and their handler setting is `app.handler`. The infra owner must integrate the built artifact and `backend.app.handler` before deploying this backend through the existing stack. See [DEPLOYMENT.md](DEPLOYMENT.md) for the concrete handoff. The optional standalone template takes `DataBucketName` and `FrontendOrigin`; building it does not deploy resources or switch the existing frontend.

The deployment template is provided for handoff; no AWS resources have been deployed from this workspace. SAM build and live cold-start/p99 acceptance need verification in the target environment. Local tests run in the project's configured Python 3.14 environment; the declared runtime compatibility is Python 3.12+.

Runtime requirements are exported from `uv.lock`. Refresh after dependency changes:

```bash
uv export --frozen --no-dev --no-hashes --no-emit-project --output-file requirements.txt
```

Framework references: [FastAPI error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/) and [Mangum adapter](https://mangum.fastapiexpert.com/adapter/).
