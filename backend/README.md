# aicafe backend

FastAPI + hexagonal layout (`domain` → `application` → `adapters`). See `.claude/rules/backend-fastapi-hexagonal.md`.

## Local development

```bash
docker compose -f ../docker-compose.dev.yml up -d      # pgvector Postgres on localhost:55432
psql postgresql://aicafe:aicafe@localhost:55432/aicafe -c 'CREATE DATABASE aicafe_test'   # integration tests
uv sync
uv run alembic upgrade head                             # AICAFE_DATABASE_URL overrides the default
uv run pytest                                           # unit + integration tests
uv run ruff check . && uv run mypy && uv run lint-imports
```

## Collecting cafe data (Yeoksam, 2 km)

```bash
./scripts/crawl_yeoksam.sh            # discover (grid x keywords) then details (menus, reviews, status)
uv run python -m app.adapters.inbound.cli discover --radius-m 600 --max-requests 50   # small trial
uv run python -m app.adapters.inbound.cli details --limit 20
```

- Slow on purpose: a search every ~2 s and a detail page every ~3 s (plus jitter). At 1 request/second Naver
  started answering 400/429 after a few hundred requests. A 403/429, or 5 consecutive failures, stops the run
  (exit code 2) and keeps progress; wait a few hours before resuming.
- Re-running is safe: `cafe.place_id` is the primary key, unchanged rows are not rewritten
  (`content_hash`), changed rows are updated, vanished places are marked `is_active = false`.
- Review text policy: only the 10 reviews on the first page are read; noise/chatbot text is dropped;
  `raw_body` is temporary and is purged after taste tagging, leaving tags + a 200-character snippet.
- Naver session cookies are not used and must never be added to the repository.

## Collection requests (areas visitors ask for)

When a visitor opens a place with no data, the web UI offers "이 지역 수집 요청하기". Requests are queued
(`collection_request` table, one row per ~1.1 km cell, `request_count` goes up when others ask for the same
area) and collected in quiet hours by the `aicafe-collector` CronJob (03:30 KST, `deploy/k8s/base/collector.yaml`).

```bash
uv run python -m app.adapters.inbound.cli requests                          # the queue, most requested first
uv run python -m app.adapters.inbound.cli collect-requests --budget-minutes 8 --max-requests 1   # run by hand
```

- Per request: discover within 1.5 km, fetch details only for places without them, compute tastes for the new
  cafes only (`ComputeCafeTastes.run(only_new=True)`), then purge raw review text.
- Stops when the time budget (default 150 min) is used up and puts the unfinished request back in the queue;
  stops the whole run at once on a Naver 403/429 (exit code 2). Any other error marks that one request `failed`.
- API: `POST /api/v1/collection-requests` (`{lat, lng}`) and `GET /api/v1/collection-requests?lat&lng`.
  Limits: 5 requests per visitor per hour, 100 waiting areas, 30 new areas per day; areas that already have
  10+ cafes within 1 km answer `covered`.

## Admin page (`/admin`)

Signs in with the Secret keys `AICAFE_ADMIN_USER`, `AICAFE_ADMIN_PASSWORD` (12+ characters) and
`AICAFE_ADMIN_SESSION_KEY` (24+ characters); without them every `/api/v1/admin/*` route answers 404.
`deploy.sh secrets` adds them to `aicafe-backend` once. Locally:

```bash
AICAFE_ADMIN_USER=admin AICAFE_ADMIN_PASSWORD=<12+ chars> AICAFE_ADMIN_SESSION_KEY=<24+ chars> \
  uv run uvicorn app.main:app --port 8010          # then open http://localhost:5173/admin
```

- Session = HMAC-signed cookie (8 h, `HttpOnly`, `SameSite=Strict`), nothing stored on the server. Every admin
  call needs the header `X-Admin-Request: 1`. Login attempts: 10 per 10 minutes per visitor.
- "Run now" creates a Kubernetes Job from the nightly CronJob (`adapters/outbound/clients/k8s_collector.py`) with
  `--request-id <id> --budget-minutes 60`; it refuses while another collector is working. Outside a cluster it
  answers 503. Run one request from a shell with
  `uv run python -m app.adapters.inbound.cli collect-requests --request-id <id>`.
- A request left `running` for 4+ hours (its pod died) goes back to the queue when the next collection starts.

## Running the API

```bash
uv run alembic upgrade head
uv run python -m app.adapters.inbound.cli seed-archetypes     # once
uv run python -m app.adapters.inbound.cli taste               # after each crawl
AICAFE_KMA_AUTH_KEY=... uv run uvicorn app.main:app --port 8010
```

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/recommendations?lat&lng&radius_m=1000` | weather -> wanted taste -> TOP 3 cafes (`items`) plus 10 more (`more_items`, ranks 4-13), each with menu, message, open state |
| `GET /api/v1/weather?lat&lng` | the weather and the taste it calls for |
| `GET /healthz` | liveness |

- Weather: one KMA call serves every request of that hour (snapshot kept in memory and in
  `weather_snapshot`); an hour that is not published yet falls back to the previous one. Locations
  farther than 40 km from a covered station get a 503 (`data/kma_stations.csv`, capital area only,
  coordinates approximate until the official station table is available).
- Open/closed is shown, never filtered; at least two of the three picks are open whenever enough
  cafes are open (the radius grows 1 -> 2 -> 3 -> 5 km if needed).
- Recommendations are cached for 10 minutes per ~200 m cell. The KMA key is read from the
  environment only and is kept out of logs.

## Moving data to the cluster

```bash
./scripts/export_data.sh /tmp/aicafe-data.sql.gz     # taste vectors, scenarios, purge raw review text, dump
../.claude/skills/deploy-k3s/scripts/deploy.sh load-data /tmp/aicafe-data.sql.gz   # into an empty cluster DB
```

The dump contains tags and 200-character snippets only. Weather snapshots are not copied (the API refetches
the current hour). To refresh later, crawl locally (or run the crawl as a Job from `deploy/k8s/jobs/job.yaml`),
rerun `taste`, and reload.

## Evaluating the taste lexicon

```bash
uv run python -m scripts.eval_taste     # precision / recall / F1 against 120 made-up, hand-labelled snippets
```

`tests/test_taste_eval.py` keeps those scores from regressing. The snippets are invented (no real reviews or shops are stored in
the repository), so the scores guard against regressions; they do not measure accuracy on real reviews. See `docs/taste-model.md`.

## Measuring recommendation quality

```bash
uv run python -m scripts.eval_reco      # drink rate, podium variety, reason types over 78 weather x location podiums
```
