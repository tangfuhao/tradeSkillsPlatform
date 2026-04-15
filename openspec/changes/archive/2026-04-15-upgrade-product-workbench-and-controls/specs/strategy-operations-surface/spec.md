## ADDED Requirements

### Requirement: Strategy operations surface SHALL present linked execution ownership
The product-facing strategy management surface SHALL list strategies with immutable identity, linked live-runtime state, recent backtest context, and primary actions.

#### Scenario: User opens the strategy management surface
- **WHEN** a user navigates to the strategy management route
- **THEN** the system renders strategies with enough ownership context to understand which executions belong to each strategy and what actions are currently available

### Requirement: Strategy operations surface SHALL provide direct strategy-skill entry
The product-facing strategy management surface SHALL allow a user to paste strategy skill text and create a new immutable strategy without using the operator console.

#### Scenario: User creates a strategy from the management surface
- **WHEN** a user submits valid strategy skill text from the strategy management surface
- **THEN** the system creates a new strategy artifact and refreshes the management surface to include it

### Requirement: Strategy operations surface SHALL expose execution and destructive actions safely
The strategy management surface SHALL expose create, delete, backtest, and live-runtime actions for each strategy and SHALL clarify cascade or lifecycle consequences before destructive actions execute.

#### Scenario: User opens actions for a strategy
- **WHEN** a user expands or invokes the actions menu for a strategy
- **THEN** the system shows only the actions currently available for that strategy and explains the impact of destructive actions before confirmation
