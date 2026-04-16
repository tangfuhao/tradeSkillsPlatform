## MODIFIED Requirements

### Requirement: Users can create replay-based backtest runs from a validated Skill
The platform SHALL allow a user to create a backtest run by selecting a validated Skill, a historical date range, and an initial capital amount, SHALL persist a PostgreSQL-backed run record before replay execution starts, and SHALL enqueue the run for worker claim without relying on process-local execution state.

#### Scenario: Valid backtest request creates a queued run
- **WHEN** a user submits a backtest request for an existing Skill and the requested window fits local historical coverage
- **THEN** the platform creates a `queued` backtest run, initializes execution-scoped portfolio and state storage, and makes the run claimable by a worker through durable database-backed coordination

#### Scenario: Backtest request outside local coverage is rejected
- **WHEN** the requested historical window falls outside the locally available market-data coverage or does not span at least one full cadence interval
- **THEN** the platform rejects the request with a validation error

## ADDED Requirements

### Requirement: Backtest workers claim and resume runs safely across a worker fleet
The platform SHALL coordinate queued or resumable backtest work through PostgreSQL row-level claims, checkpoints, and idempotent step commits so multiple workers can execute many user backtests concurrently without double-running the same work.

#### Scenario: Two workers race to start the same queued backtest
- **WHEN** two workers attempt to claim the same queued backtest run concurrently
- **THEN** only one worker acquires the run claim and the other worker observes that the run is no longer claimable

#### Scenario: Interrupted backtest resumes from the last durable checkpoint
- **WHEN** a running backtest worker crashes or loses its lease after committing some replay steps
- **THEN** another worker can reclaim the run and continue from the last durable checkpoint instead of replaying already committed steps
