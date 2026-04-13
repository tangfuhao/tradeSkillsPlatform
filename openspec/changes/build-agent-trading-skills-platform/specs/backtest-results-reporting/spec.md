## ADDED Requirements

### Requirement: Completed backtests return a core result summary
The platform SHALL compute and store a core summary for every completed backtest, including net PnL, total return, max drawdown, trade count, win rate, fees paid, and the benchmark summary used for display.

#### Scenario: User views a completed backtest summary
- **WHEN** a backtest run reaches `completed`
- **THEN** the API returns the stored summary metrics and identifies the benchmark and execution assumptions used

### Requirement: Result views include preview scope and trust labels
The platform SHALL label each backtest result with its execution scope and any important warnings about assumptions or data quality.

#### Scenario: Preview result is clearly labeled
- **WHEN** a result comes from a preview-scope backtest
- **THEN** the platform marks the run as preview-scope and indicates that it was not approved for a larger historical window

### Requirement: Result views expose trace samples and decision history
The platform SHALL retain and expose the Agent's structured decisions, reasoning summaries, and tool-call summaries for completed backtests.

#### Scenario: User inspects a trace sample
- **WHEN** a user opens a completed backtest run
- **THEN** the platform returns per-trigger trace entries including timestamp, final decision, and reasoning summary

### Requirement: Result artifacts are exportable
The platform SHALL allow export of machine-readable backtest artifacts including the run manifest, summary metrics, and trace or ledger data.

#### Scenario: User exports a backtest artifact bundle
- **WHEN** a user requests an export for a completed backtest
- **THEN** the platform returns a downloadable artifact containing the summary and detailed trace data
