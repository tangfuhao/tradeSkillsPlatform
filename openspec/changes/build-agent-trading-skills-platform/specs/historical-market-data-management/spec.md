## ADDED Requirements

### Requirement: Operators can manage local historical market data snapshots for replay
The platform SHALL support operator-managed historical market data snapshots suitable for replay-safe backtests, including venue, symbol scope, timeframe, and coverage metadata.

#### Scenario: Historical snapshot is registered
- **WHEN** an operator publishes a local historical dataset snapshot
- **THEN** the platform stores the snapshot metadata and makes it selectable for replay-capable backtests

### Requirement: Historical reads are constrained by replay time
The platform SHALL expose historical market data to backtest tools through time-bounded queries that prevent future-data leakage.

#### Scenario: Candle query respects replay timestamp
- **WHEN** the replay driver invokes a market-data tool with an `as_of` or `end_time` boundary
- **THEN** the tool returns only rows available up to that timestamp

### Requirement: Data coverage issues are visible to the runtime and the user
The platform SHALL surface missing coverage, degraded data quality, or unavailable symbols so that runs can fail clearly or carry an explicit warning.

#### Scenario: Backtest references incomplete data coverage
- **WHEN** the requested date range or symbol set is not fully covered by the available historical data
- **THEN** the platform rejects the run or marks it with a data-coverage warning that is visible in the result context
