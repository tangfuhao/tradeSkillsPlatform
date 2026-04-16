# PostgreSQL Runtime Operations

This runbook covers the PostgreSQL-first runtime used by TradeSkills today: schema migrations, CSV ingest jobs, partition maintenance, storage-health debugging, and SQLite-to-PostgreSQL cutover / rollback steps.

## 1. Preconditions

- Runtime storage is PostgreSQL only.
- The API and worker processes expect the configured database to already be reachable and migrated to Alembic head.
- Default local URL:

```bash
postgresql+psycopg://tradeskills:tradeskills@127.0.0.1:5432/tradeskills
```

## 2. Apply schema migrations

Before starting the API in any environment:

```bash
cd apps/api
../../.venv/bin/alembic upgrade head
```

To inspect runtime storage compatibility and current revision:

```bash
./.venv/bin/python scripts/runtime_storage_admin.py health
```

You should see:

- `backend: "postgresql"`
- `status: "ok"`
- `current_revision == required_revision`
- `writable: true`

## 3. Manage CSV ingest backlog

Historical CSV import is no longer tied to API startup. Operators explicitly discover and run ingest jobs.

Discover new jobs from `TRADE_SKILLS_HISTORICAL_DATA_DIR`:

```bash
./.venv/bin/python scripts/market_data_ingest.py discover
```

List recent jobs:

```bash
./.venv/bin/python scripts/market_data_ingest.py list --limit 20
```

Run pending jobs:

```bash
./.venv/bin/python scripts/market_data_ingest.py run-pending --limit 4 --runner-id ops-manual
```

Run one specific job:

```bash
./.venv/bin/python scripts/market_data_ingest.py run-job <csv_job_id> --runner-id ops-manual
```

Equivalent HTTP endpoints:

- `GET /api/v1/market-data/ingest-jobs`
- `POST /api/v1/market-data/ingest-jobs/discover`
- `POST /api/v1/market-data/ingest-jobs/run`

Operational expectations:

- PostgreSQL ingest uses `COPY` -> staging table -> merge into `market_candles`
- `rows_staged` reflects rows loaded into staging before merge
- `rows_inserted` reflects rows that survived dedupe into canonical storage
- `rows_filtered` reflects rows rejected before merge, such as non-confirmed candles

## 4. Maintain candle partitions

The `market_candles` table is PostgreSQL-partitioned by `open_time_ms`.

List partitions:

```bash
./.venv/bin/python scripts/runtime_storage_admin.py partitions-list --as-json
```

Ensure historical and near-future partitions exist:

```bash
./.venv/bin/python scripts/runtime_storage_admin.py partitions-ensure --months-back 36 --months-ahead 3
```

Detach old partitions outside the hot retention window:

```bash
./.venv/bin/python scripts/runtime_storage_admin.py partitions-prune --retention-months 36
```

Drop old partitions permanently:

```bash
./.venv/bin/python scripts/runtime_storage_admin.py partitions-prune --retention-months 36 --drop
```

Notes:

- API startup already ensures the configured partition window exists.
- Use `detach` first if you want a rollback window before permanent deletion.
- `market_candles_default` is expected to exist as a safety partition for unexpected ranges.

## 5. Storage-health debugging

Primary health endpoint:

```bash
curl -s http://127.0.0.1:8000/api/v1/health | jq '.database'
```

Focus on:

- `database.status`
- `database.current_revision`
- `database.required_revision`
- `database.pool`
- `database.market_candle_partitions`
- `ingest_backlog`

Useful triage flow:

1. Confirm PostgreSQL connectivity and Alembic head with `scripts/runtime_storage_admin.py health`.
2. Confirm pending or failed CSV jobs with `scripts/market_data_ingest.py list`.
3. Inspect API health for pool pressure or stale schema.
4. Inspect coverage and backlog via:

```bash
curl -s http://127.0.0.1:8000/api/v1/market-data/overview | jq '.ingest_backlog, .coverage_ranges'
curl -s http://127.0.0.1:8000/api/v1/market-data/sync-status | jq '.ingest_backlog, .latest_snapshot'
```

If startup fails immediately:

- verify `TRADE_SKILLS_DATABASE_URL`
- verify PostgreSQL is writable, not a read-only recovery node
- run Alembic migrations
- ensure the configured role can create temp tables for ingest staging

## 6. SQLite demo-data cutover

Use the one-time migration tool when an environment still has legacy SQLite demo data.

Run migration:

```bash
./.venv/bin/python scripts/migrate_sqlite_to_postgres.py \
  --source-sqlite-path data/runtime/trade_skills.db \
  --report-path data/runtime/migration-report.json
```

What the tool verifies:

- per-table row-count parity
- `market_candles` coverage parity
- sample-query parity for:
  - aggregated `fetch_candles(... timeframe="15m")`
  - `build_market_snapshot(...)`
  - `get_market_data_coverage_ranges()`

Safe cutover sequence:

1. Stop API / worker processes that still point at the old environment.
2. Snapshot or back up PostgreSQL.
3. Run `alembic upgrade head`.
4. Run `scripts/migrate_sqlite_to_postgres.py`.
5. Review the generated JSON report and confirm `"verified": true`.
6. Start API and worker processes against PostgreSQL only.
7. Validate `GET /api/v1/health`, `GET /api/v1/market-data/overview`, and a few representative backtest / live summaries.
8. Remove or archive the legacy SQLite file once the cutover is accepted.

## 7. Rollback guidance

TradeSkills no longer uses SQLite as a runtime fallback. Rollback means reverting within PostgreSQL:

- restore a PostgreSQL snapshot taken before cutover, or
- redeploy the previous application release against a known-good PostgreSQL snapshot / schema revision

Recommended rollback discipline:

1. Take a PostgreSQL backup before migrations or bulk data migration.
2. Keep the JSON migration report produced by `scripts/migrate_sqlite_to_postgres.py`.
3. Detach, rather than drop, old partitions when you need a reversible retention action.
4. Do not plan to switch live services back to SQLite once PostgreSQL cutover is accepted.
