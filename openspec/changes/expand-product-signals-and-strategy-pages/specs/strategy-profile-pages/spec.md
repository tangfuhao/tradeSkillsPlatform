## ADDED Requirements

### Requirement: Product routes SHALL provide strategy discovery and profile pages
The product-facing experience SHALL provide routes that allow users to browse available strategies and open a dedicated profile for an individual strategy.

#### Scenario: User opens strategies navigation
- **WHEN** a user chooses to explore strategies from the product shell or homepage
- **THEN** the system provides a strategy destination that lists available strategies and links to individual strategy profile routes

### Requirement: Strategy profiles SHALL translate skill metadata into readable sections
The strategy profile page SHALL present cadence, validation, risk, tooling, and recent execution context as product-readable sections rather than raw debug JSON.

#### Scenario: User opens a strategy profile
- **WHEN** a user navigates to a strategy profile route for an existing skill
- **THEN** the system renders readable strategy sections built from the skill and related execution data
