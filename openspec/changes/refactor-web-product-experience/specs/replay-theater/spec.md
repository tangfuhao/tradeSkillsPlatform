## ADDED Requirements

### Requirement: Replay pages SHALL treat a backtest run as a multi-symbol experience
The replay experience SHALL support backtest runs that rotate across multiple symbols and SHALL let the user inspect symbol-specific slices within the same run.

#### Scenario: Run contains multiple traded symbols
- **WHEN** a user opens a replay page for a run whose traces or fills reference more than one symbol
- **THEN** the system shows a symbol selection mechanism and updates the replay context according to the selected symbol

### Requirement: Replay pages SHALL present run context before raw trace detail
The replay experience SHALL summarize run status, timing, and outcome in a user-facing narrative layer before exposing low-level execution detail.

#### Scenario: User opens a replay page
- **WHEN** a user lands on a replay route for an existing run
- **THEN** the system first shows run overview information such as status, timing, return, or activity summary in a product-facing layout

### Requirement: Replay pages SHALL be chart-ready for future trade overlays
The replay experience SHALL organize data so that price series, symbol-specific trades, and decision moments can be attached to a chart region without reworking route structure.

#### Scenario: Replay page loads selected symbol context
- **WHEN** a replay page resolves a selected symbol for a run
- **THEN** the system prepares a dedicated replay visualization region and symbol-scoped decision context suitable for later chart integration
