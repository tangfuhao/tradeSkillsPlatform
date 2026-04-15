## MODIFIED Requirements

### Requirement: Skills can be activated for live periodic signal generation
The platform SHALL allow a validated Skill to be activated as a live runtime using the cadence extracted from the Skill Envelope, and SHALL enforce that at most one non-terminal live runtime exists for a given Skill at a time.

#### Scenario: Live task is created from a Skill
- **WHEN** a user activates live mode for a Skill that has no active or paused live runtime
- **THEN** the platform creates a live task bound to that Skill and schedules periodic triggers according to the extracted cadence

#### Scenario: Existing live runtime blocks duplicate activation
- **WHEN** a user attempts to activate live mode for a Skill that already owns an active or paused live runtime
- **THEN** the platform prevents creation of a second live runtime for that Skill and returns the existing ownership state or a validation error

## ADDED Requirements

### Requirement: Strategies SHALL become immutable after creation
The platform SHALL treat each stored Skill as an immutable strategy artifact once creation succeeds and SHALL require users to create a new strategy if they want a revised definition.

#### Scenario: User wants to revise a stored strategy
- **WHEN** a user attempts to change the definition of an existing stored strategy
- **THEN** the platform does not provide an in-place edit path and instead requires creation of a new strategy artifact

### Requirement: Strategy deletion SHALL cascade to linked executions
The platform SHALL allow strategy deletion and SHALL remove linked backtests, live runtime records, signals, traces, and scope-specific state owned by that strategy as part of the same destructive action.

#### Scenario: User deletes a strategy with linked executions
- **WHEN** a user confirms deletion of a strategy that owns backtests or a live runtime
- **THEN** the platform removes the strategy and its owned execution artifacts together so no orphaned execution state remains
