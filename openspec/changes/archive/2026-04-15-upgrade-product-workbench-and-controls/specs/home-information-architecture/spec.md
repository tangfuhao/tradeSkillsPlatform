## MODIFIED Requirements

### Requirement: The homepage SHALL guide users into replay, signals, and strategy destinations
The product homepage SHALL act as a structured workbench hub that prioritizes current live performance, recent backtests, recent strategies, and direct strategy entry while still guiding users into deeper replay, signals, and strategy destinations.

#### Scenario: User lands on the homepage
- **WHEN** a user opens the product homepage
- **THEN** the page presents prioritized operational modules with clear entry points into replay exploration, signal monitoring, and strategy management

### Requirement: Homepage previews SHALL remain summary-level
The homepage SHALL keep live, backtest, and strategy modules at a summary level and SHALL defer full management and detail workflows to their dedicated routes.

#### Scenario: Homepage shows operational previews
- **WHEN** the homepage renders live, backtest, or strategy summaries
- **THEN** those modules show only high-value fields and include navigation controls to the fuller dedicated pages

## ADDED Requirements

### Requirement: Homepage SHALL provide direct strategy-skill entry
The homepage SHALL provide a direct input surface for submitting a new strategy skill without requiring the user to enter the operator console first.

#### Scenario: User creates a strategy from the homepage
- **WHEN** a user enters strategy skill text from the homepage input surface and submits it
- **THEN** the system creates the strategy through the standard skill-creation flow and updates the product surfaces to include the new strategy
