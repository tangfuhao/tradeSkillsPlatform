## Context

TradeSkills currently uses a single SQLite runtime database for market candles, execution state, backtest records, signals, and operator metadata. That design matches the project's original single-machine demo shape, but it now conflicts with the next stage of the product: much larger historical coverage, multi-process sync and execution workers, and eventual multi-user traffic against the same runtime.

The sharpest current pain point is startup-time CSV ingestion. Historical data is still discovered during startup, parsed row by row in Python, and inserted through SQLite-oriented chunking logic, which turns large seed loads into a blocking boot path. The same architecture also keeps important aggregation work in application code, makes concurrency control depend on process-local behavior, and leaves the project without a real schema-migration discipline.

This change makes PostgreSQL the required system of record and uses PostgreSQL-native capabilities as part of the design contract, not merely as a drop-in connection-string replacement. The goal is to build one storage plane that can safely support API servers, sync workers, backtest workers, and product surfaces at materially larger scale.

## Goals / Non-Goals

**Goals:**
- Replace SQLite with PostgreSQL as the only supported runtime database for persistent platform state.
- Eliminate startup-blocking historical imports and replace them with explicit PostgreSQL-backed ingest workflows.
- Scale historical candles, traces, fills, and signals to much larger volumes using PostgreSQL-native storage and query patterns.
- Move hot aggregation and analytical filtering from Python into SQL so large-window and multi-symbol reads do not depend on loading raw rows into application memory.
- Make live dispatch, backtest orchestration, and lifecycle control safe under multiple API and worker processes.
- Introduce a first-class migration, observability, and operational model suitable for a production deployment.

**Non-Goals:**
- Introduce a separate OLAP warehouse, lakehouse, or columnar analytics engine in this change.
- Redesign trading semantics, portfolio accounting rules, or Agent prompts.
- Add end-user tenancy, authentication, or billing in this change.
- Guarantee zero-downtime cutover from SQLite; this change targets a controlled migration from demo data to the PostgreSQL runtime.
- Require TimescaleDB or another PostgreSQL extension on day one, although the design keeps that option open for a later phase.

## Decisions

### 1. PostgreSQL becomes the sole runtime database
- Decision: remove SQLite as a supported runtime engine and standardize runtime persistence on PostgreSQL.
- Why: dual-engine support would preserve the very branch complexity we are trying to remove, especially in bulk ingest, locking semantics, migrations, and query planning.
- Alternatives considered:
  - Keep SQLite for local dev and PostgreSQL for production: rejected because it would let concurrency bugs, migration drift, and query regressions escape local testing.
  - Abstract the database behind a storage interface first: rejected as unnecessary indirection for a codebase that already relies heavily on SQLAlchemy models and query behavior.
- Consequences: local development now requires PostgreSQL, and every service must validate engine type and migration revision at boot.

### 2. Adopt versioned schema management and compatibility checks
- Decision: manage schema evolution through forward-only PostgreSQL migrations, expose the active revision in health/status endpoints, and fail service startup when the schema revision is incompatible.
- Why: the current `create_all()` approach is not safe once multiple services, rolling deploys, and partitioned tables are involved.
- Alternatives considered:
  - Keep auto-create for local environments: rejected because it hides migration requirements and produces non-reproducible schema drift.
  - Run destructive rebuilds for every release: rejected because retained historical data and execution records are too valuable.
- Consequences: introduce migration tooling, release-time migration steps, and compatibility tests between code revision and schema revision.

### 3. Use PostgreSQL-native bulk ingest with staging and merge
- Decision: route CSV seed imports and large historical backfills through PostgreSQL staging tables and bulk-load commands, then merge into canonical tables with database-enforced deduplication.
- Why: the current row-wise parse-and-insert path is dominated by ORM overhead, SQLite variable limits, and startup blocking.
- Alternatives considered:
  - Keep batched ORM inserts against PostgreSQL: rejected because it leaves most ingest performance on the table and still couples import cost tightly to Python.
  - Load directly into canonical tables without staging: rejected because malformed files, duplicate handling, and partial-file diagnostics become harder to manage.
- Consequences: historical ingest becomes an explicit job flow, API startup only validates readiness, and operators gain visible ingest progress/failure metadata.

### 4. Store large append-heavy datasets in partition-friendly PostgreSQL tables
- Decision: redesign candle and other large append-heavy tables around PostgreSQL declarative partitioning, targeted indexes, and retention-aware maintenance.
- Why: market candles, traces, signals, and fills will grow far beyond demo scale, and global btree indexes become an avoidable bottleneck.
- Alternatives considered:
  - Single large heap tables with many composite indexes: rejected because write amplification and vacuum/index maintenance will worsen as data grows.
  - External time-series database: rejected for now because PostgreSQL is sufficient for the next scale step and keeps operational complexity lower.
- Consequences: canonical candle storage remains append-oriented, partition management becomes part of operations, and retention/archive policy can evolve without rewriting the data plane.

### 5. Push time-series aggregation and analytical filtering into SQL
- Decision: preserve canonical `1m` candles, but execute larger timeframe aggregation, market scans, reporting filters, and pagination in PostgreSQL. For hot intervals, allow database-managed rollups or materialized views while keeping `1m` as the source of truth.
- Why: Python-side aggregation does not scale for broad windows or many symbols and prevents the query planner from doing the heavy lifting.
- Alternatives considered:
  - Keep dynamic aggregation in Python only: rejected because it grows linearly in application memory and CPU with every wider query.
  - Precompute every timeframe eagerly: rejected because it adds write amplification and unnecessary storage for infrequently queried intervals.
- Consequences: query correctness needs parity tests against current behavior, and read APIs must adopt explicit pagination/bounds.

### 6. Coordinate live and backtest execution with transactional claims
- Decision: move run coordination onto PostgreSQL using row-level locks, `FOR UPDATE SKIP LOCKED`-style work claims, unique slot constraints, idempotency keys, heartbeat/lease columns, and optimistic concurrency for lifecycle actions.
- Why: once multiple workers or API instances exist, process-local coordination is not enough to prevent duplicate live slots, double-started backtests, or conflicting lifecycle commands.
- Alternatives considered:
  - Rely only on Redis queue semantics: rejected because durable system-of-record state still needs transactional coordination at commit time.
  - Use fully serializable transactions everywhere: rejected because targeted row locks and unique constraints are simpler and cheaper for this workload.
- Consequences: execution tables need claim metadata and revision fields, and command handlers must distinguish conflict, retryable lease expiry, and idempotent replay.

### 7. Keep one explicit cutover instead of long-lived dual-write
- Decision: migrate demo data into PostgreSQL during a controlled rollout, validate parity, switch all services to PostgreSQL, and then remove SQLite code paths rather than maintaining long-term dual-write support.
- Why: dual-write would multiply failure modes while the current dataset is still small enough to migrate directly.
- Alternatives considered:
  - Permanent dual-write and gradual read cutover: rejected because it adds large ongoing complexity for a temporary transition.
  - Drop old data and start fresh: rejected because even demo execution history and candle coverage are useful for verification and local continuity.
- Consequences: the rollout needs a one-time migration tool, pre-cutover verification, and rollback checkpoints such as PostgreSQL snapshots or exported seed files.

### 8. Expose operator-visible storage metrics as a product requirement
- Decision: health/status responses must expose PostgreSQL engine status, migration revision, connection-pool pressure, ingest throughput, claim backlog, and partition/retention health signals.
- Why: moving to PostgreSQL improves scale only if operators can see when storage behavior is degrading.
- Alternatives considered:
  - Rely on database-internal dashboards only: rejected because product operators need application-context signals, not only generic database charts.
- Consequences: health schemas and operator docs must expand, and tests should validate the presence of these signals.

## Risks / Trade-offs

- [Operational complexity rises relative to SQLite] -> Provide Docker/dev defaults, seed scripts, migration commands, and clear local runbooks so the project remains easy to start.
- [Partitioning strategy may be wrong for future volume or query shape] -> Start with conservative partitions for the largest append-heavy tables, monitor pruning/selectivity, and keep partition boundaries configurable.
- [Bulk merge workflows can create lock pressure or long transactions] -> Use staging tables, bounded merge batches, and observability for merge duration and deadlock/lock-wait failures.
- [SQL aggregation may drift from current Python behavior] -> Build parity tests for timeframe aggregation, coverage calculations, and scan outputs before removing the old code path.
- [Concurrency-safe execution control increases implementation scope] -> Phase the work so schema/migration and ingest changes land before worker claim refactors, while preserving clear invariants in the specs.
- [Local developer friction could slow iteration] -> Ship compose-managed PostgreSQL, fast seed fixtures, and representative test containers so local behavior matches production.

## Migration Plan

1. Add PostgreSQL runtime dependencies, configuration, migration tooling, and container/dev wiring.
2. Create the PostgreSQL schema, partitioned large tables, indexes, constraints, and migration compatibility checks.
3. Implement explicit ingest commands/jobs that bulk load CSV or historical backfill data into staging tables and merge into canonical storage.
4. Port read paths to PostgreSQL-native aggregation, pagination, and analytical filtering while keeping result-parity tests against existing behavior.
5. Port live dispatch, backtest orchestration, and lifecycle commands to PostgreSQL-backed claims, leases, and revision checks.
6. Migrate existing SQLite demo data into PostgreSQL, verify counts and sample-query parity, and cut all service environments over to PostgreSQL.
7. Remove SQLite-specific code, tests, env defaults, and documentation after the cutover succeeds.

Rollback approach:
- Before cutover, rollback means reverting configuration to the prior SQLite release and discarding the new PostgreSQL environment.
- After cutover, rollback means restoring PostgreSQL from a snapshot or re-running the data migration into a known-good schema revision together with the prior application release; SQLite is not kept as a permanent fallback runtime.

## Open Questions

- Should common rollups such as `5m`, `15m`, `1h`, and `4h` be materialized immediately, or should we launch with dynamic SQL aggregation first and materialize only after profiling?
- Which large append-heavy tables besides `market_candles` should be partitioned in v1 of the migration: `run_traces`, `live_signals`, `portfolio_fills`, or all of them?
- Do we want PgBouncer in the first production deployment, or is native SQLAlchemy pooling sufficient until multi-user traffic arrives?
- How much trace/result retention should remain hot in PostgreSQL before archival/export becomes necessary?
