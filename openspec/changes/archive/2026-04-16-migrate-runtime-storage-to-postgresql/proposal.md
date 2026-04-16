## Why

The current SQLite-based runtime is sufficient for a single-machine demo, but it becomes a bottleneck once historical candle volume, concurrent workers, and user-facing execution traffic grow together. We need a PostgreSQL-first storage architecture now so market-data ingestion, multi-user execution, and analytical reads can scale without startup-time bulk imports, write contention, or fragile process-local coordination.

## What Changes

- **BREAKING** Replace SQLite as the supported runtime database with PostgreSQL for all persistent platform state.
- Move historical candle ingestion from startup-bound row batching to PostgreSQL-native bulk-load and merge workflows that can run out of band from API boot.
- Introduce PostgreSQL-first schema management, online migration, connection-pool, and operational requirements so API, sync workers, and future multi-user runtimes share one durable concurrency-safe data plane.
- Redesign historical market-data storage around PostgreSQL capabilities such as partitioning, covering indexes, set-based aggregation, and database-enforced idempotent upserts.
- Redesign live and backtest execution persistence around database-backed leasing, idempotency, and checkpoint semantics so multiple API or worker processes can operate safely without duplicate runs.
- Push time-series aggregation and analytical queries down into PostgreSQL where practical, replacing Python-side scan-and-aggregate paths that do not scale with larger coverage windows.
- Add explicit operator-facing requirements for ingestion throughput, backlog visibility, query pagination, retention, and failure recovery under a multi-user deployment model.

## Capabilities

### New Capabilities
- `postgresql-runtime-storage`: Defines PostgreSQL as the required system of record for platform persistence, including schema lifecycle, concurrency control, migration safety, bulk ingestion, and operator visibility for a multi-process deployment.

### Modified Capabilities
- `historical-market-data-management`: Historical candles, sync state, and coverage reads now rely on PostgreSQL-native bulk ingestion, partitioned storage, and SQL-side aggregation rather than SQLite-oriented startup import behavior.
- `live-signal-execution`: Live dispatch must support PostgreSQL-backed idempotency, slot leasing, and duplicate-run prevention across multiple API or worker processes.
- `backtest-simulation`: Backtest orchestration must support PostgreSQL-backed checkpointing, queue coordination, and concurrent multi-user execution without relying on SQLite-friendly single-process assumptions.
- `backtest-results-reporting`: Result and trace reads must support paginated, index-backed PostgreSQL query patterns suitable for larger retained histories and multi-user inspection.
- `execution-control-lifecycle`: Lifecycle commands must become concurrency-safe and idempotent when multiple clients or workers issue control actions against the same execution scope.

## Impact

- Affected backend code: `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/core/*`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/models.py`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/services/*`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/runtime/*`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/api/routes/*`, and supporting tests.
- Affected infrastructure: `/Users/fuhao/Documents/hackson/tradeSkills/infra/docker/compose/docker-compose.yml`, `/Users/fuhao/Documents/hackson/tradeSkills/infra/env/*`, local dev scripts, deployment manifests, and secrets management for PostgreSQL.
- Affected dependencies: PostgreSQL driver/runtime, migration tooling, connection pooling, and optional bulk-ingest helpers.
- Affected data/operations: one-time SQLite-to-PostgreSQL migration for demo data, new bootstrap/backfill procedures, operator runbooks, and health/status reporting for the database layer.
