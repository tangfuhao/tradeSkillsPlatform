## ADDED Requirements

### Requirement: Execution scopes SHALL expose consistent lifecycle metadata
The platform SHALL expose lifecycle metadata for backtests and live runtimes in a consistent shape that includes current status, linked strategy ownership, last activity, available actions, and progress metadata when applicable.

#### Scenario: Product UI reads an execution summary
- **WHEN** a product surface requests a backtest or live-runtime summary
- **THEN** the platform returns lifecycle metadata in a consistent structure that the UI can use to render status, progress, and action affordances

### Requirement: Execution control commands SHALL be availability-aware
The platform SHALL accept lifecycle control commands only when the requested action is valid for the current execution state and SHALL reject invalid transitions with explicit errors.

#### Scenario: Unsupported control action is requested
- **WHEN** a user or client issues a lifecycle control command that is not available for the target execution state
- **THEN** the platform rejects the command with a validation error instead of silently ignoring it

### Requirement: Execution deletion SHALL remove scope-owned execution artifacts
Deleting an execution scope SHALL remove the artifacts owned by that scope, including scheduler registrations, traces or signals, and execution-scoped portfolio or state records.

#### Scenario: Execution scope is deleted
- **WHEN** a user deletes a backtest or live runtime
- **THEN** the platform removes the owned execution artifacts for that scope so no orphaned execution state remains
