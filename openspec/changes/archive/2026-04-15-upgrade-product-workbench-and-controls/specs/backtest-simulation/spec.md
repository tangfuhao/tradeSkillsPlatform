## MODIFIED Requirements

### Requirement: Backtest runs expose lifecycle status and trace data
The platform SHALL track lifecycle states of `queued`, `running`, `paused`, `stopping`, `stopped`, `completed`, and `failed` for backtest runs, SHALL retain per-trigger trace records, and SHALL expose progress metadata for product and operator surfaces.

#### Scenario: Completed replay stores traces
- **WHEN** a backtest finishes successfully
- **THEN** the platform stores the result summary, progress-complete state, and per-trigger decisions, reasoning summaries, tool calls, and portfolio execution details for later inspection

#### Scenario: User inspects a non-terminal or interrupted replay
- **WHEN** a user requests a backtest that is queued, running, paused, stopping, or stopped
- **THEN** the platform returns the current lifecycle state together with completed-step and total-step progress metadata

## ADDED Requirements

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
