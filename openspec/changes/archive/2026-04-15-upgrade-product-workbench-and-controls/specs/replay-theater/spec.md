## MODIFIED Requirements

### Requirement: Replay pages SHALL present run context before raw trace detail
The replay experience SHALL summarize the selected run's status, progress, timing, linked strategy, and outcome in a focused current-run layout before exposing low-level execution detail.

#### Scenario: User opens a replay page
- **WHEN** a user lands on a replay route for an existing run
- **THEN** the system first shows selected-run overview information such as status, timing, progress, return, and linked strategy context in a product-facing layout

## ADDED Requirements

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
