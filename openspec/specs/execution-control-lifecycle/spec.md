# execution-control-lifecycle Specification

## Purpose
Define the shared lifecycle metadata and control semantics for execution scopes such as backtests and live runtimes so product surfaces can manage them consistently and safely.
## Requirements
### Requirement: Execution scopes SHALL expose consistent lifecycle metadata
The platform SHALL expose lifecycle metadata for backtests and live runtimes in a consistent shape that includes current status, linked strategy ownership, last activity, available actions, and progress metadata when applicable.

#### Scenario: Product UI reads an execution summary
- **WHEN** a product surface requests a backtest or live-runtime summary
- **THEN** the platform returns lifecycle metadata in a consistent structure that the UI can use to render status, progress, and action affordances

### Requirement: Execution control commands SHALL be availability-aware
The platform SHALL accept lifecycle control commands only when the requested action is valid for the current execution state, SHALL execute those transitions through concurrency-safe PostgreSQL-backed updates, and SHALL reject invalid or stale transitions with explicit errors.

#### Scenario: Unsupported control action is requested
- **WHEN** a user or client issues a lifecycle control command that is not available for the target execution state
- **THEN** the platform rejects the command with a validation error instead of silently ignoring it

#### Scenario: Concurrent lifecycle commands target the same execution scope
- **WHEN** two clients or workers issue conflicting lifecycle control commands against the same backtest or live runtime concurrently
- **THEN** the platform commits at most one state transition for the contested revision and returns a deterministic conflict or idempotent success outcome for the losing command

### Requirement: Execution deletion SHALL remove scope-owned execution artifacts
Deleting an execution scope SHALL remove the artifacts owned by that scope, including traces or signals and execution-scoped portfolio or state records, so no sync-driven runtime state remains dispatchable afterward.

#### Scenario: Execution scope is deleted
- **WHEN** a user deletes a backtest or live runtime
- **THEN** the platform removes the owned execution artifacts for that scope so no orphaned execution state remains

### Requirement: Execution summaries expose revision metadata for safe control
The platform SHALL expose revision or last-updated metadata on execution summaries so product surfaces and operators can issue control actions against a known execution state.

#### Scenario: Product UI reads an execution summary before sending a control action
- **WHEN** a product surface requests a backtest or live-runtime summary
- **THEN** the platform returns lifecycle metadata together with the current revision or last-updated token needed to reason about concurrent control changes

