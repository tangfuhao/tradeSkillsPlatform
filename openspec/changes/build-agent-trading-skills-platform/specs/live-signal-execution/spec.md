## ADDED Requirements

### Requirement: Users can activate periodic live signal tasks
The platform SHALL allow a user to activate a validated Skill version as a live signal task and SHALL persist the task configuration and lifecycle state.

#### Scenario: Live task is activated
- **WHEN** a user enables live mode for a Skill version
- **THEN** the platform creates a live task record and schedules periodic triggers using the cadence extracted from the Skill Envelope

### Requirement: Live tasks trigger short-lived Agent runs
The platform SHALL invoke a short-lived Agent execution for each live trigger rather than relying on long-lived in-Agent cron state.

#### Scenario: Scheduler triggers a live run
- **WHEN** the live scheduler reaches the next scheduled fire time for a task
- **THEN** the platform creates a live run context, invokes the Agent, stores the resulting signal, and exits the run

### Requirement: Live runs emit structured signals
The platform SHALL require each live Agent run to return a structured signal that includes symbol, direction, size, reason, and optional stop-loss or take-profit information.

#### Scenario: Agent produces a signal
- **WHEN** a live Agent run identifies a trading opportunity
- **THEN** the platform stores a structured signal payload and makes it available for notification delivery and later inspection

### Requirement: Users can inspect recent signals
The platform SHALL provide an API to list recent signals for a live task.

#### Scenario: User checks recent live outputs
- **WHEN** a user requests recent signals for an active or paused live task
- **THEN** the platform returns the latest stored structured signals in reverse chronological order
