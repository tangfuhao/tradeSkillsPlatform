# backtest-simulation Specification

## Purpose
TBD - created by archiving change build-agent-trading-skills-platform. Update Purpose after archive.
## Requirements
### Requirement: Users can create replay-based backtest runs from a validated Skill
The platform SHALL allow a user to create a backtest run by selecting a validated Skill, a historical date range, and an initial capital amount, and SHALL persist a run record before replay execution starts.

#### Scenario: Valid backtest request creates a queued run
- **WHEN** a user submits a backtest request for an existing Skill and the requested window fits local historical coverage
- **THEN** the platform creates a `queued` backtest run, initializes execution-scoped portfolio and state storage, and starts replay asynchronously

#### Scenario: Backtest request outside local coverage is rejected
- **WHEN** the requested historical window falls outside the locally available market-data coverage or does not span at least one full cadence interval
- **THEN** the platform rejects the request with a validation error

### Requirement: Replay driver triggers the Agent according to the Skill cadence
The platform SHALL derive replay trigger times from the Skill Envelope cadence and invoke the Agent at each historical trigger point.

#### Scenario: Fifteen-minute Skill is replayed at 15-minute intervals
- **WHEN** a Skill Envelope declares a `15m` cadence for a backtest window
- **THEN** the replay driver generates 15-minute trigger points across the requested window and invokes the Agent on each trigger

### Requirement: Backtest tools enforce historical as-of boundaries
The platform SHALL ensure that market and portfolio tools used during backtest runs only expose information available at or before the current replay timestamp.

#### Scenario: Agent cannot read future candles during replay
- **WHEN** the Agent requests market data at replay time `T`
- **THEN** the Tool Gateway returns only data with timestamps less than or equal to `T`

### Requirement: Structured Agent decisions drive simulated execution
The platform SHALL consume the Agent's structured decisions during backtest runs and apply them to the simulated portfolio engine for the current execution scope.

#### Scenario: Open-position decision updates the simulated account
- **WHEN** the Agent returns an `open_position` decision during a backtest run
- **THEN** the platform records the decision, applies the simulated execution assumptions, and updates the run's position and PnL state

### Requirement: Backtest runs expose lifecycle status and trace data
The platform SHALL track lifecycle states of `queued`, `running`, `paused`, `stopping`, `stopped`, `completed`, and `failed` for backtest runs, SHALL retain per-trigger trace records, and SHALL expose progress metadata for product and operator surfaces.

#### Scenario: Completed replay stores traces
- **WHEN** a backtest finishes successfully
- **THEN** the platform stores the result summary, progress-complete state, and per-trigger decisions, reasoning summaries, tool calls, and portfolio execution details for later inspection

#### Scenario: User inspects a non-terminal or interrupted replay
- **WHEN** a user requests a backtest that is queued, running, paused, stopping, or stopped
- **THEN** the platform returns the current lifecycle state together with completed-step and total-step progress metadata

### Requirement: Backtest runs SHALL support lifecycle control actions
The platform SHALL allow supported lifecycle actions such as pause, resume, stop, and delete to be issued against backtest runs and SHALL expose which actions are currently available for each run.

#### Scenario: User pauses a running backtest
- **WHEN** a user issues a pause action for a running backtest
- **THEN** the platform checkpoints execution progress and transitions the run into a paused state without losing completed traces

#### Scenario: User stops a queued or running backtest
- **WHEN** a user issues a stop action for a queued or running backtest
- **THEN** the platform halts further replay progress at a safe checkpoint and records the run as stopped or stopping until the halt completes

#### Scenario: User deletes a backtest
- **WHEN** a user deletes a backtest whose current state permits deletion
- **THEN** the platform removes the run and its run-scoped traces and portfolio state

