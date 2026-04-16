## ADDED Requirements

### Requirement: PostgreSQL is the required runtime system of record
The platform SHALL require PostgreSQL for all persistent runtime state and SHALL reject unsupported database engines or incompatible schema revisions before API or worker traffic is accepted.

#### Scenario: Service boots against a compatible PostgreSQL runtime
- **WHEN** a service starts with a PostgreSQL connection and the database schema revision matches the version required by that release
- **THEN** the service completes startup and exposes PostgreSQL engine and schema-revision metadata in health output

#### Scenario: Unsupported engine or stale schema blocks startup
- **WHEN** a service starts with SQLite or with a PostgreSQL schema revision that is older or newer than the compatible window for that release
- **THEN** the service fails fast before accepting requests or dispatching work

### Requirement: Schema lifecycle is migration-driven and operator-visible
The platform SHALL evolve runtime storage through versioned PostgreSQL migrations and SHALL expose the active and required schema revision state to operators.

#### Scenario: Operator inspects migration state
- **WHEN** an operator requests health or status information for the runtime
- **THEN** the platform returns the PostgreSQL server version, current schema revision, required schema revision, and whether the service is in a writable compatible state

#### Scenario: Rolling deploy crosses one schema revision boundary
- **WHEN** the old and new application releases overlap during deployment and the schema is within the declared compatibility window
- **THEN** both releases continue to operate without corrupting runtime state until the rollout completes

### Requirement: Runtime coordination uses transactional claims and idempotency
The platform SHALL coordinate durable work claims, leases, and duplicate-write prevention through PostgreSQL transactions, unique constraints, and row-level locking so concurrent services cannot commit the same execution slot twice.

#### Scenario: Two workers race to claim the same work item
- **WHEN** two workers attempt to claim the same queued live slot or backtest job concurrently
- **THEN** PostgreSQL allows only one transaction to acquire the claim and the losing worker observes no claimable work or a conflict outcome

#### Scenario: Duplicate completion is prevented after a retry
- **WHEN** a worker retries a previously claimed execution after a timeout or transient failure
- **THEN** the platform records at most one committed terminal result for the same logical work item and reports the retry as reclaimed or already-completed

### Requirement: Large historical imports run outside API startup
The platform SHALL execute seed imports and deep backfills as explicit PostgreSQL-backed ingest jobs instead of blocking API startup on inline row-wise CSV import.

#### Scenario: API boots while ingest backlog exists
- **WHEN** pending seed files or backfill jobs exist for historical market data
- **THEN** API startup completes after validating database readiness and reports the ingest backlog without importing rows inline

#### Scenario: Operator submits a CSV ingest job
- **WHEN** an operator starts a historical CSV import
- **THEN** the platform bulk loads the file into PostgreSQL staging storage, merges deduplicated rows into canonical tables, and records per-job throughput, coverage, and failure metadata

### Requirement: Operator storage health signals are surfaced by the application
The platform SHALL expose application-level storage health signals that let operators understand whether PostgreSQL is becoming a bottleneck for ingest, reads, or execution coordination.

#### Scenario: Operator inspects storage health
- **WHEN** an operator requests storage or health status
- **THEN** the platform returns connection-pool saturation, ingest throughput, claim backlog, slow-query or lock-wait indicators, and partition or retention maintenance state relevant to the current runtime
