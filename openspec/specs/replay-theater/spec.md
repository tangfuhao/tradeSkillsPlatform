# replay-theater Specification

## Purpose
Define the product-facing replay experience for browsing backtest runs, inspecting run context, and preparing symbol-scoped execution detail for deeper analysis.

## Requirements
### Requirement: Replay pages SHALL treat a backtest run as a multi-symbol experience
The replay experience SHALL support backtest runs that rotate across multiple symbols and SHALL let the user inspect symbol-specific slices within the same run.

#### Scenario: Run contains multiple traded symbols
- **WHEN** a user opens a replay page for a run whose traces or fills reference more than one symbol
- **THEN** the system shows a symbol selection mechanism and updates the replay context according to the selected symbol

### Requirement: Replay pages SHALL present run context before raw trace detail
The replay experience SHALL summarize the selected run's status, progress, timing, linked strategy, and outcome in a focused current-run layout before exposing low-level execution detail.

#### Scenario: User opens a replay page
- **WHEN** a user lands on a replay route for an existing run
- **THEN** the system first shows selected-run overview information such as status, timing, progress, return, and linked strategy context in a product-facing layout

### Requirement: Replay pages SHALL be chart-ready for future trade overlays
The replay experience SHALL organize data so that price series, symbol-specific trades, and decision moments can be attached to a chart region without reworking route structure.

#### Scenario: Replay page loads selected symbol context
- **WHEN** a replay page resolves a selected symbol for a run
- **THEN** the system prepares a dedicated replay visualization region and symbol-scoped decision context suitable for later chart integration

### Requirement: Replay lists SHALL expose operational summaries and actions
The replay list route SHALL render backtests as operational records with strategy context, execution window, lifecycle state, progress or result summary, and currently supported actions.

#### Scenario: User opens the replay list route
- **WHEN** a user navigates to the replay list route
- **THEN** the system shows backtests with enough operational detail to stop, pause, delete, or open them according to the actions available for each run

### Requirement: Replay detail SHALL focus on the selected run
The replay detail page SHALL focus on the currently selected run and SHALL not require nearby-run browsing to remain visible as a competing primary panel.

#### Scenario: User inspects a replay detail page
- **WHEN** a user opens a replay detail route
- **THEN** the page centers the selected run's controls, metrics, chart region, and decision timeline ahead of any secondary navigation to other runs

