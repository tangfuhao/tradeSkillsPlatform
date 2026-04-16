## 1. PostgreSQL foundation

- [x] 1.1 Add PostgreSQL runtime dependencies, environment settings, and container/dev wiring for local and deployed environments.
- [x] 1.2 Introduce versioned schema migrations and startup compatibility checks that fail fast on unsupported engines or stale revisions.
- [x] 1.3 Expand health/status contracts to report PostgreSQL engine, migration, pool, and storage-health metadata.

## 2. Storage schema redesign

- [x] 2.1 Refactor runtime models for PostgreSQL-specific constraints, revision fields, and execution-claim metadata.
- [x] 2.2 Create partitioned schemas and indexes for `market_candles` and other large append-heavy runtime tables.
- [x] 2.3 Add partition/retention maintenance helpers and migration coverage for new table layouts.

## 3. Historical market-data ingestion and reads

- [x] 3.1 Replace startup-bound CSV import with explicit ingest job records, APIs or commands, and backlog reporting.
- [x] 3.2 Implement PostgreSQL staging plus bulk-load/merge flows for CSV seeds and large historical backfills.
- [x] 3.3 Move candle aggregation, market-overview, and coverage queries into PostgreSQL with bounded pagination and parity tests.

## 4. Execution coordination and concurrency control

- [x] 4.1 Implement PostgreSQL-backed live slot claims, leases, and idempotent terminal writes across multiple workers.
- [x] 4.2 Implement PostgreSQL-backed backtest queue claims, checkpoints, and resume behavior across a worker fleet.
- [x] 4.3 Make lifecycle control commands concurrency-safe and expose revision metadata needed by product surfaces.

## 5. Data migration and validation

- [x] 5.1 Build a one-time SQLite-to-PostgreSQL migration tool for demo data and seed-state verification.
- [x] 5.2 Add PostgreSQL integration tests for ingest throughput, SQL aggregation correctness, execution claims, and lifecycle conflicts.
- [x] 5.3 Run count/sample-query parity checks, cut service environments over to PostgreSQL, and remove SQLite-specific runtime code paths.

## 6. Operations and documentation

- [x] 6.1 Update deployment manifests, local run scripts, and environment examples to require PostgreSQL instead of SQLite.
- [x] 6.2 Document operator runbooks for ingest jobs, partition maintenance, storage-health debugging, and rollback/cutover steps.
- [x] 6.3 Refresh architecture and product-operations docs so the running system is documented as PostgreSQL-first.
