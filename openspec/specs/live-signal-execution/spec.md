# live-signal-execution Specification

## Purpose
TBD - created by archiving change build-agent-trading-skills-platform. Update Purpose after archive.
## Requirements
### Requirement: Users can activate periodic live signal tasks from a validated Skill
The platform SHALL allow a validated Skill to own one active or paused live runtime, SHALL persist that runtime's cadence and lifecycle state, and SHALL prevent duplicate concurrent runtimes for the same strategy.

#### Scenario: Live task is activated
- **WHEN** a user enables live mode for a Skill that does not already own an active or paused runtime
- **THEN** the platform creates an `active` live runtime, initializes execution-scoped portfolio and state storage, and waits for the next qualified market-sync hook to execute the latest cadence-aligned slot

#### Scenario: Duplicate live activation is rejected
- **WHEN** a user enables live mode for a Skill that already owns an active or paused runtime
- **THEN** the platform does not create a second concurrent runtime for that Skill and returns the existing ownership state or a validation error

### Requirement: Live tasks can be triggered by the sync loop or the manual trigger API
The platform SHALL invoke a short-lived Agent execution for each live trigger, SHALL gate execution on healthy synced market data, and SHALL not rely on in-process wall-clock scheduler jobs for automatic live dispatch.

#### Scenario: Sync loop triggers a live run
- **WHEN** a market-data sync sweep completes successfully, advances local `coverage_end_ms`, and a live task has a newer cadence-aligned executable slot than its checkpoint
- **THEN** the platform creates a live run context for that slot, invokes the Agent, stores the resulting signal record, and exits the run

#### Scenario: User manually triggers a live task
- **WHEN** a user calls the live-task trigger endpoint for an active task while sync state is healthy, fresh, and exposes a pending executable slot
- **THEN** the platform executes one short-lived live run for that same gated slot and returns the stored signal record

#### Scenario: Manual trigger is rejected on stale or unhealthy sync
- **WHEN** a user calls the live-task trigger endpoint but the latest sync state is stale, unhealthy, or has no pending slot
- **THEN** the platform rejects the request with an explicit conflict-style error instead of running on an older snapshot

### Requirement: Live runs store structured signal records
The platform SHALL require each live Agent run to produce a structured stored signal record for later inspection, rather than treating outbound notification delivery as a required runtime feature.

#### Scenario: Agent produces a stored signal record
- **WHEN** a live Agent run completes successfully
- **THEN** the platform stores a structured signal payload containing the final decision, reasoning summary, execution context, the slot `execution_time_ms`, the `trigger_origin`, and a `delivery_status` of `stored`

#### Scenario: Live run failure is captured
- **WHEN** a live Agent run fails before producing a normal decision payload
- **THEN** the platform stores a failed signal record with `delivery_status` set to `failed` and includes the error context for inspection

### Requirement: Users can inspect recent signals and live-task portfolio state
The platform SHALL provide APIs to list recent signals, inspect live-task portfolio state, and expose runtime lifecycle metadata needed by product monitoring surfaces.

#### Scenario: User checks recent live outputs
- **WHEN** a user requests recent signals for all tasks or for a specific live task
- **THEN** the platform returns the latest stored structured signals in reverse chronological order together with enough runtime context to identify their owning strategy and lifecycle state

#### Scenario: User opens the live-task portfolio view
- **WHEN** a user requests the portfolio for an existing live task
- **THEN** the platform returns the task-scoped account snapshot, current positions, recent fills, and the runtime state needed for product monitoring

### Requirement: Live runtimes SHALL support lifecycle control actions
The platform SHALL allow pause, resume, stop, and delete actions for live runtimes by updating persisted runtime state and sync-driven eligibility, without relying on scheduler job registration side effects.

#### Scenario: User pauses a live runtime
- **WHEN** a user issues a pause action for an active live runtime
- **THEN** the platform preserves runtime state and portfolio context, marks the runtime paused, and prevents future sync-driven dispatch until resume

#### Scenario: User resumes a paused live runtime
- **WHEN** a user issues a resume action for a paused live runtime
- **THEN** the platform marks the runtime active again and makes it eligible for the next qualified market-sync hook

#### Scenario: User deletes a live runtime
- **WHEN** a user deletes a live runtime whose state permits deletion
- **THEN** the platform removes the runtime and its owned signal and execution state records and ensures it is no longer eligible for sync-driven dispatch
