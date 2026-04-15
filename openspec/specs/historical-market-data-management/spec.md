# historical-market-data-management Specification

## Purpose
TBD - created by archiving change build-agent-trading-skills-platform. Update Purpose after archive.
## Requirements
### Requirement: Operators can seed and sync local historical market data
The platform SHALL support operator-managed local historical OKX-style candle ingestion from CSV files and SHALL track import coverage and incremental sync status in local persistence.

#### Scenario: CSV seed import is recorded
- **WHEN** unseen historical CSV files are discovered during startup sync
- **THEN** the platform imports supported rows into local storage and records ingestion-job metadata and coverage information

#### Scenario: Incremental catch-up is skipped for large gaps
- **WHEN** the local coverage gap exceeds the configured incremental sync threshold
- **THEN** the platform marks the sync cursor as skipped and leaves the larger backfill to offline CSV seeding

### Requirement: Historical reads are constrained by replay time
The platform SHALL expose historical market data to backtest tools through time-bounded queries that prevent future-data leakage.

#### Scenario: Candle query respects replay timestamp
- **WHEN** the replay driver or Tool Gateway invokes a market-data query with an `as_of` boundary
- **THEN** the tool returns only rows available up to that timestamp

### Requirement: Historical candle APIs can aggregate from stored 1m bars
The platform SHALL store `1m` candles as the base timeframe and derive larger timeframes from those stored bars when requested.

#### Scenario: User requests a 15m candle series
- **WHEN** a client requests aggregated candles for a supported market symbol and timeframe such as `15m`
- **THEN** the platform builds the response from the stored `1m` history within the available coverage window

### Requirement: Data coverage issues are visible to the runtime and operator
The platform SHALL surface missing coverage, skipped syncs, or unavailable symbols so that runs can fail clearly or operators can inspect the current state.

#### Scenario: Backtest references incomplete data coverage
- **WHEN** the requested date range is not fully covered by the available historical data
- **THEN** the platform rejects the run with a coverage error instead of silently falling back to partial history

