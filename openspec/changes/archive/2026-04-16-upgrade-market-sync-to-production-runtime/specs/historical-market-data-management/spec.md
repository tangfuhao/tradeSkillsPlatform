## MODIFIED Requirements

### Requirement: Operators can seed and sync local historical market data
The platform SHALL support operator-managed local historical OKX-style candle ingestion from CSV files, SHALL persist the OKX `SWAP` instrument universe with lifecycle and priority metadata, and SHALL advance recent coverage through symbol-scoped bootstrap, incremental sync, and backfill workflows rather than a single sweep-scoped cursor.

#### Scenario: CSV seed import is recorded
- **WHEN** unseen historical CSV files are discovered during startup sync
- **THEN** the platform imports supported rows into local storage and records ingestion-job metadata and coverage information

#### Scenario: Universe refresh tracks active and delisted contracts
- **WHEN** the platform refreshes the OKX `SWAP` universe from the exchange metadata endpoints
- **THEN** it upserts active or suspended contracts into persistent instrument state, updates sync priority tiers, and marks repeatedly missing contracts as `delisted` without deleting their stored history

#### Scenario: New active symbol becomes live-eligible after recent bootstrap
- **WHEN** a newly discovered active contract has no local candles yet
- **THEN** the platform creates symbol sync state, bootstraps a recent window of `1m` candles, and marks the symbol ready for live coverage without waiting for full-history backfill

#### Scenario: Deep backlog is diverted away from the high-frequency budget
- **WHEN** a symbol's local gap exceeds the configured recent bootstrap window
- **THEN** the platform refreshes only the recent live window, records that deeper backfill is still pending, and keeps the symbol's deeper history catch-up out of the high-frequency freshness budget

#### Scenario: Partial symbol sync progress is preserved across failures
- **WHEN** a symbol sync worker inserts some candle pages and a later page fails or times out
- **THEN** the platform keeps the successfully written rows and updated sync cursor, records the failed attempt, and retries the remaining gap according to retry and backoff rules instead of rewinding the symbol

### Requirement: Data coverage issues are visible to the runtime and operator
The platform SHALL surface symbol-level sync freshness and an aggregated market coverage gate so that live runs can fail clearly, operators can inspect the current state, and automatic dispatch only advances from a qualified `dispatch_as_of_ms` snapshot.

#### Scenario: Coverage aggregation unlocks dispatch from qualified market freshness
- **WHEN** all active `tier1` symbols are fresh and the configured active-universe coverage threshold is satisfied for a common timestamp `T`
- **THEN** the platform records a coverage snapshot with `dispatch_as_of_ms = T`, coverage ratios, degraded status, and missing-symbol metadata that downstream live dispatch uses as its only automatic market gate

#### Scenario: Coverage aggregation blocks when freshness is insufficient
- **WHEN** the active universe is missing required `tier1` freshness, falls below the configured coverage ratio, or only has a stale snapshot
- **THEN** the platform marks the gate as blocked or stale with an explicit reason instead of reusing an older dispatch cutoff

#### Scenario: Operator inspects sync health and universe state
- **WHEN** an operator calls health or market-data status endpoints
- **THEN** the platform returns aggregated coverage, freshness counts, bootstrap and backfill indicators, recent sync errors, and the current active or delisted universe state for inspection
