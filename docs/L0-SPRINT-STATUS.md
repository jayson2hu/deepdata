# L0 Sprint Status

## Current Status

Implemented a runnable L0 baseline through the S1-S4 core path plus E8 media reference handling.
Local SQLite/file-store verification is green. Final DoD remains open only for environment-backed
PostgreSQL/Redis/MinIO verification and the required >=24h unattended run.

2026-06-04 update: implemented the multi-source collection expansion described by
`docs/L0-多源采集-方案设计.md`, `docs/L0-多源采集-开发计划.md`, and
`docs/L0-前端优化-开发文档.md`. P1-P4 are implemented and locally verified. GitHub delivery
is still blocked because `D:\vscodefile\deepdata` is not currently a Git worktree.

## Implemented Features

- F0.1 repository scaffold, Python package, lint/type/test config, CI workflow.
- F0.2 SQLAlchemy models and Alembic initial migration for L0-owned tables plus outbox.
- F0.3 file object store and S3-compatible object store adapter.
- F0.4 Arq worker skeleton with Redis settings.
- F0.5 basic smoke/health evidence through DB/object-store operations.
- F1.1 source creation with duplicate feed URL rejection.
- F1.2 idempotent OPML import.
- F2.1 due-source scheduler by crawl interval.
- F2.2 crawl_jobs stats and status recording.
- F3.1 RSS parsing for file/http feeds, malformed feed failure handling.
- F3.2 raw RSS entry preservation in raw_documents.
- F4.1 static fetcher and Playwright-rendered fetch path.
- F4.2 raw HTML object storage with sha256 pointer.
- F4.3 basic HTML text extraction and confidence.
- F4.4 failure trace preservation in raw_documents.
- F5.1 url_hash/content_hash/simhash.
- F5.2 duplicate/variant classification preserving raw traces.
- F5.3 content_items creation with WAIT_FILTER status.
- F6.1 RawStore append-only repository without update/delete.
- F6.2 content version creation on same-URL content changes.
- F6.3 lineage and rebuild_canonical from raw HTML.
- F7.1 transactional outbox with idempotency key.
- F7.1 relay restart can skip events already accepted by an idempotent publisher after a crash before `published_at` is marked.
- F7.1 Redis-backed idempotent publisher uses SETNX-style accept keys and RPUSH event envelopes.
- F7.2 list_contents/get_content L1 contract.
- F8.1/F8.2 media asset storage helpers for image/audio references.
- Soak verifier: `core_data.scripts.soak` can run scheduled crawl/relay loops, seed a fixture source, and fail unless new raw/content rows are produced.
- External DoD verifier: `core_data.scripts.external_dod` enforces PostgreSQL + Redis + S3 mode, runs external smoke, verifies Redis relay idempotency, and can run the required 24h soak.
- External smoke is safe to rerun against a persistent database because relay assertions count only unpublished outbox events.
- Docker Compose includes MinIO bucket initialization for `codepick-raw`.
- P1 multi-source adapters: added `core_data.ingest.adapters` registry, `rss`, `html_list`,
  `github_trending`, and the adapter-driven `crawl_source` path. Article sources still use
  page fetch + extract; ranking sources use lightweight `TREND` content creation through
  `build_content_item_from_entry`.
- P2 scheduler: added `core_data.scripts.scheduler_run` with `--once`, `--tick-sec`, optional
  `--relay`, and `.runtime/scheduler-heartbeat.json` heartbeat output.
- P3 dashboard/API: added `GET /api/source-types`; extended `POST /api/sources` with `type`
  and `crawl_config`; status payload now exposes source `type`, `interval_min`, `next_run`,
  scheduler status, and content `meta`; `dashboard.html` supports type/config entry and
  `TREND` metadata display.
- P4 platform adapters: added JSON hot-list adapters for `baidu_hot`, `zhihu_hot`, and
  `weibo_hot`; added explicit extension placeholders for `douyin_hot` and `xiaohongshu`.

## Verification

- 2026-06-01 `python -m pytest -q D:\vscodefile\deepdata\tests --cov=core_data --cov-config=D:\vscodefile\deepdata\.coveragerc --cov-report=term-missing --cov-fail-under=80`: 26 passed, coverage 88.83%.
- Coverage is scoped to `D:\vscodefile\deepdata\src\core_data` via `.coveragerc`.
- 2026-06-01 `python -m core_data.scripts.smoke`: `L0 PIPELINE: PASS sources=1 entries=1 raw=2 content=1 events=1 failed=0`.
- `python -m core_data.scripts.smoke` repeated twice in one process: passed both runs.
- `python -m compileall -q ...`: passed.
- 2026-06-01 `python -m ruff check D:\vscodefile\deepdata`: passed.
- 2026-06-01 `python -m mypy --config-file D:\vscodefile\deepdata\pyproject.toml D:\vscodefile\deepdata\src`: passed, 36 source files.
- 2026-06-01 `python -m core_data.scripts.audit_dod`: passed all local static DoD checks, including append-only RawStore, L0-owned tables, stable L1 fields, transactional outbox signature, no upper-layer imports, and delivery artifacts present.
- 2026-06-01 `python -m core_data.scripts.audit_dod`: now also verifies that the external DoD verifier is documented and wired through README/Makefile/script entrypoint.
- Forbidden import AST check: `FORBIDDEN_IMPORTS []`.
- 2026-06-01 from project root, `python -m alembic -c alembic.ini upgrade head`: passed against SQLite.
- 2026-06-01 from project root, `python -m alembic -c alembic.ini downgrade base`: passed against SQLite.
- 2026-06-01 `python -m core_data.scripts.soak --hours 0 --interval-sec 0 --seed-fixture --report D:\tmp\l0-soak-proof-current2.json`: passed with `new_raw_documents=2`, `new_content_items=1`, `events_relayed=1`, `errors=[]`, `pass=true`.
- `python -m pytest -q D:\vscodefile\deepdata\tests\integration\test_playwright_fetcher.py --no-cov`: passed.
- 2026-06-01 `python -m core_data.scripts.integration_smoke`: passed in local file-store/SQLite mode.
- `integration-smoke --require-external` now checks PostgreSQL, Redis, and object-store round trips before running the pipeline.
- 2026-06-01 `python -m core_data.scripts.external_dod --skip-soak`: rejected default local SQLite mode with `DATABASE_URL must point at PostgreSQL for external DoD`, proving the final DoD verifier will not accidentally certify local mode.
- 2026-06-01 CI workflow includes `python -m core_data.scripts.audit_dod` after smoke.
- Docker CLI available: `Docker version 28.0.4`; Docker Compose available: `v2.34.0-desktop.1`.
- Playwright Chromium launch check: passed.
- 2026-06-01 `docker info`: Docker client available, server unavailable because `dockerDesktopLinuxEngine` pipe is missing.
- 2026-06-01 `docker compose -f D:\vscodefile\deepdata\deploy\docker-compose.yml up -d`: failed before service startup with missing `dockerDesktopLinuxEngine` pipe while checking `minio/minio`.
- 2026-06-01 repeated `docker compose -f D:\vscodefile\deepdata\deploy\docker-compose.yml up -d`: failed before service startup with missing `dockerDesktopLinuxEngine` pipe while checking `redis:7`.
- 2026-06-01 after Docker Desktop/Linux engine startup, `docker compose -f D:\vscodefile\deepdata\deploy\docker-compose.yml up -d`: passed; PostgreSQL+pgvector, Redis, and MinIO are running.
- 2026-06-01 PostgreSQL Alembic `downgrade base` and `upgrade head`: passed against `postgresql+psycopg://codepick:dev@localhost:5432/codepick`.
- 2026-06-01 `python -m core_data.scripts.integration_smoke --require-external`: passed against real PostgreSQL, Redis, and MinIO/S3.
- 2026-06-01 `python -m core_data.scripts.external_dod --skip-soak`: passed; Redis relay idempotency evidence showed `first_relay_count=1`, `second_relay_count=0`, duplicate publish did not increase queue length.
- 2026-06-01 `python -m core_data.scripts.external_dod --soak-hours 0 --interval-sec 0 --report D:\tmp\external-dod-soak-quick.json`: passed against real external services with `new_raw_documents=2`, `new_content_items=1`, `errors=[]`, `pass=true`.
- 2026-06-01 user-requested 2-minute external soak, `python -m core_data.scripts.external_dod --soak-hours 0.0334 --interval-sec 30 --report D:\tmp\external-dod-soak-2min.json`: passed with `iterations=5`, `new_raw_documents=2`, `new_content_items=1`, `events_relayed=1`, `errors=[]`, `pass=true`.
- 2026-06-04 `python -m ruff check .`: passed.
- 2026-06-04 `python -m mypy --config-file pyproject.toml src`: passed, 44 source files.
- 2026-06-04 `python -m core_data.scripts.audit_dod`: passed all static L0 contract checks.
- 2026-06-04 `python -m core_data.scripts.smoke`: `L0 PIPELINE: PASS sources=1 entries=1 raw=2 content=1 events=1 failed=0`.
- 2026-06-04 `python -m core_data.scripts.scheduler_run --once`: passed, wrote scheduler heartbeat with `due=1`, `crawled=1`, `failed=0`.
- 2026-06-04 `python -m pytest -q D:/vscodefile/deepdata/tests --cov=core_data --cov-config=D:/vscodefile/deepdata/.coveragerc --cov-report=term-missing --cov-fail-under=80`: 37 passed, coverage 86.60%.
- 2026-06-04 dashboard HTTP smoke on `127.0.0.1:8091`: `GET /` returned 200,
  `GET /api/source-types` returned 8 source types, and `GET /api/status` returned live status
  including scheduler/source metadata.

## Local Tool Gaps

- Docker Desktop/Linux engine is now running and external PostgreSQL/Redis/MinIO verification has passed.
- The strict original >=24h unattended run remains intentionally unexecuted because the user requested a 2-minute run instead.
- README and Makefile now expose `make external-dod` for the final external verification path after Docker engine is available.
- Alembic's `script_location = db/alembic` is relative to the current working directory; run migration commands from `D:\vscodefile\deepdata` or use `Set-Location` first.
- `python -m pytest -q` from this shell can collect sibling workspace projects because the
  current directory handling is inconsistent. Use the explicit Makefile-equivalent test command
  above for authoritative L0 verification.
- `D:\vscodefile\deepdata` has no `.git` directory and `git -C D:\vscodefile\deepdata
  rev-parse --show-toplevel` returns `fatal: not a git repository`; per-feature commits and
  GitHub push cannot be completed until the real Git worktree/remote is provided or initialized.

## Remaining DoD Work

- Strict DoD only: execute and record the original >=24h unattended scheduler/worker run with `make external-dod`; the report must show `pass=true`, `new_raw_documents>=1`, `new_content_items>=1`, and `errors=[]`.
- Delivery only: commit P1/P2/P3/P4 as separate commits and push to GitHub after restoring or
  initializing Git metadata for `D:\vscodefile\deepdata`.
