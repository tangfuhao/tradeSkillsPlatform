# operator-console-routing Specification

## Purpose
Define how operator-oriented tooling remains accessible under a dedicated console route while staying reachable from the product-facing experience.

## Requirements
### Requirement: Operator workflows SHALL remain available under a dedicated console route
The system SHALL preserve the current operator-focused dashboard capabilities behind a separate console route.

#### Scenario: Operator opens the console
- **WHEN** a user navigates to `/console`
- **THEN** the system renders the existing operator workflows for skills, backtests, live tasks, service health, and execution traces

### Requirement: Console access SHALL remain reachable from the product experience
The product-facing experience SHALL provide a visible navigation path to the operator console without making the console the default landing page.

#### Scenario: User wants debugging tools from a product page
- **WHEN** a user is on a product-facing route and chooses to inspect operational tooling
- **THEN** the system provides a navigation control that leads to the console route

