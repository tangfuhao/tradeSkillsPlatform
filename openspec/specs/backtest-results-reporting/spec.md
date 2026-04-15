# backtest-results-reporting Specification

## Purpose
TBD - created by archiving change build-agent-trading-skills-platform. Update Purpose after archive.
## Requirements
### Requirement: Completed backtests return a core result summary
The platform SHALL compute and store a core summary for every completed backtest, including realized PnL, unrealized PnL at the end of the window, net PnL, total return, benchmark comparison, max drawdown, trade count, win rate, fees paid, final equity, replay step count, and execution assumptions.

#### Scenario: User views a completed backtest summary
- **WHEN** a backtest run reaches `completed`
- **THEN** the API returns the stored summary metrics together with the benchmark name and assumption notes used for display

### Requirement: Result views expose trace samples and decision history
The platform SHALL retain and expose the Agent's structured decisions, reasoning summaries, tool-call summaries, and per-step portfolio execution details for completed backtests.

#### Scenario: User inspects a trace sample
- **WHEN** a user opens a completed backtest run
- **THEN** the platform returns per-trigger trace entries including timestamp, final decision, reasoning summary, tool calls, and portfolio before/after snapshots

### Requirement: Users can inspect execution-scoped portfolio state for a run
The platform SHALL expose the simulated portfolio account, open positions, and recent fills for a backtest run.

#### Scenario: User opens the backtest portfolio view
- **WHEN** a user requests the portfolio for an existing backtest run
- **THEN** the platform returns the run-scoped account snapshot, current positions, and recent fills

### Requirement: Failed runs expose explicit error information
The platform SHALL retain the run status and failure message when replay execution cannot complete.

#### Scenario: Backtest step fails
- **WHEN** replay execution raises an error at a specific trigger step
- **THEN** the platform marks the run as `failed` and returns an error message describing the failing step and timestamp

