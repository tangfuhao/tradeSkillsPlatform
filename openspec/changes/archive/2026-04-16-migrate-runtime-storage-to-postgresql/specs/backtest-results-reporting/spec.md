## MODIFIED Requirements

### Requirement: Result views expose trace samples and decision history
The platform SHALL retain and expose the Agent's structured decisions, reasoning summaries, tool-call summaries, and per-step portfolio execution details for completed backtests through PostgreSQL-backed paginated and filterable queries.

#### Scenario: User inspects a trace sample
- **WHEN** a user opens a completed backtest run
- **THEN** the platform returns per-trigger trace entries including timestamp, final decision, reasoning summary, tool calls, and portfolio before/after snapshots in a deterministic order with pagination metadata when the trace volume exceeds a single response window

## ADDED Requirements

### Requirement: Result history queries are index-backed and bounded
The platform SHALL expose backtest result history through bounded query patterns that can filter by strategy, status, and time range without requiring full-table scans in application code.

#### Scenario: User filters recent backtests for a strategy
- **WHEN** a user requests recent backtest runs for one strategy and a bounded time range
- **THEN** the platform answers from PostgreSQL-backed indexed filters and returns the matching runs in reverse chronological order with continuation metadata when needed
