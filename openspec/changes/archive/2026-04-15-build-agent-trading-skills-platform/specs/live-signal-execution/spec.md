## ADDED Requirements

### Requirement: Users can activate periodic live signal tasks from a validated Skill
The platform SHALL allow a user to activate a validated Skill as a live signal task and SHALL persist the task cadence and lifecycle state.

#### Scenario: Live task is activated
- **WHEN** a user enables live mode for a Skill
- **THEN** the platform creates an `active` live task, initializes execution-scoped portfolio and state storage, and schedules periodic triggers using the cadence extracted from the Skill Envelope

### Requirement: Live tasks can be triggered by the scheduler or the manual trigger API
The platform SHALL invoke a short-lived Agent execution for each live trigger rather than relying on long-lived in-Agent cron state.

#### Scenario: Scheduler triggers a live run
- **WHEN** the live scheduler reaches the next scheduled fire time for a task
- **THEN** the platform creates a live run context, invokes the Agent, stores the resulting signal record, and exits the run

#### Scenario: User manually triggers a live task
- **WHEN** a user calls the live-task trigger endpoint for an active task
- **THEN** the platform executes one short-lived live run immediately and returns the stored signal record

### Requirement: Live runs store structured signal records
The platform SHALL require each live Agent run to produce a structured stored signal record for later inspection, rather than treating outbound notification delivery as a required runtime feature.

#### Scenario: Agent produces a stored signal record
- **WHEN** a live Agent run completes successfully
- **THEN** the platform stores a structured signal payload containing the final decision, reasoning summary, execution context, and a `delivery_status` of `stored`

#### Scenario: Live run failure is captured
- **WHEN** a live Agent run fails before producing a normal decision payload
- **THEN** the platform stores a failed signal record with `delivery_status` set to `failed` and includes the error context for inspection

### Requirement: Users can inspect recent signals and live-task portfolio state
The platform SHALL provide APIs to list recent signals and inspect the live-task portfolio state.

#### Scenario: User checks recent live outputs
- **WHEN** a user requests recent signals for all tasks or for a specific live task
- **THEN** the platform returns the latest stored structured signals in reverse chronological order

#### Scenario: User opens the live-task portfolio view
- **WHEN** a user requests the portfolio for an existing live task
- **THEN** the platform returns the task-scoped account snapshot, current positions, and recent fills
