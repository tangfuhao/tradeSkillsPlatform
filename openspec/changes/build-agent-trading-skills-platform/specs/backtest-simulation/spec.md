## ADDED Requirements

### Requirement: Users can create replay-based backtest runs from a Skill version
The platform SHALL allow a user to create a backtest run by selecting a Skill version, date range, initial capital, and optional runtime overrides, and SHALL persist a run record before execution starts.

#### Scenario: Valid backtest request creates a run
- **WHEN** a user submits a backtest request for a preview-eligible or approved Skill version within the allowed date range
- **THEN** the platform creates a queued backtest run and stores the selected configuration

#### Scenario: Backtest request is rejected outside the allowed window
- **WHEN** a user requests a historical range not permitted by the Skill's current review state
- **THEN** the platform rejects the request and explains that a larger history window requires approval

### Requirement: Replay driver triggers the Agent according to the Skill cadence
The platform SHALL derive replay trigger times from the Skill Envelope cadence and invoke the Agent at each historical trigger point.

#### Scenario: Fifteen-minute Skill is replayed at 15-minute intervals
- **WHEN** a Skill Envelope declares a `15m` cadence for a backtest window
- **THEN** the replay driver generates 15-minute trigger points across the requested window and invokes the Agent on each trigger

### Requirement: Backtest tools enforce historical as-of boundaries
The platform SHALL ensure that market and state tools used during backtest runs only expose information available at or before the current replay timestamp.

#### Scenario: Agent cannot read future candles during replay
- **WHEN** the Agent requests market data at replay time `T`
- **THEN** the Tool Gateway returns only data with timestamps less than or equal to `T`

### Requirement: Structured Agent decisions drive simulated execution
The platform SHALL consume the Agent's structured decisions during backtest runs and apply them to a simulated paper-trading account.

#### Scenario: Open-position decision updates the simulated account
- **WHEN** the Agent returns an `open_position` decision during a backtest run
- **THEN** the platform records the decision, applies simulated execution assumptions, and updates the run's position and PnL state

### Requirement: Backtest runs expose lifecycle status and trace data
The platform SHALL track lifecycle states of `queued`, `running`, `completed`, and `failed` for backtest runs and retain per-trigger trace records.

#### Scenario: Completed replay stores traces
- **WHEN** a backtest finishes successfully
- **THEN** the platform stores the result summary and the per-trigger decisions or trace samples for later inspection
