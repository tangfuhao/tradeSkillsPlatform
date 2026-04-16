## MODIFIED Requirements

### Requirement: Execution control commands SHALL be availability-aware
The platform SHALL accept lifecycle control commands only when the requested action is valid for the current execution state, SHALL execute those transitions through concurrency-safe PostgreSQL-backed updates, and SHALL reject invalid or stale transitions with explicit errors.

#### Scenario: Unsupported control action is requested
- **WHEN** a user or client issues a lifecycle control command that is not available for the target execution state
- **THEN** the platform rejects the command with a validation error instead of silently ignoring it

#### Scenario: Concurrent lifecycle commands target the same execution scope
- **WHEN** two clients or workers issue conflicting lifecycle control commands against the same backtest or live runtime concurrently
- **THEN** the platform commits at most one state transition for the contested revision and returns a deterministic conflict or idempotent success outcome for the losing command

## ADDED Requirements

### Requirement: Execution summaries expose revision metadata for safe control
The platform SHALL expose revision or last-updated metadata on execution summaries so product surfaces and operators can issue control actions against a known execution state.

#### Scenario: Product UI reads an execution summary before sending a control action
- **WHEN** a product surface requests a backtest or live-runtime summary
- **THEN** the platform returns lifecycle metadata together with the current revision or last-updated token needed to reason about concurrent control changes
