# product-web-shell Specification

## Purpose
Define the shared product-facing application shell, default entry experience, and route-level presentation rules for the TradeSkills web interface.

## Requirements
### Requirement: Product-facing routes SHALL provide a direct experience-first entry
The web application SHALL expose a product-facing default route that presents TradeSkills as an operational trading workbench rather than as a theatrical preview or operator console.

#### Scenario: User opens the default route
- **WHEN** a user navigates to the web application's root path
- **THEN** the system shows a concise workbench hub with direct visibility into live performance, recent backtests, recent strategies, and strategy entry

### Requirement: Product routes SHALL share a Neon Noir application shell
All product-facing routes SHALL use a consistent workbench shell with disciplined hierarchy, restrained branding, and responsive layout, and SHALL not rely on a single repeated card treatment to communicate structure.

#### Scenario: User navigates between product routes
- **WHEN** a user moves between supported product-facing routes
- **THEN** the system preserves consistent navigation, responsive spacing, and distinct surface types for summary, list, and action regions across those routes

### Requirement: Product routes SHALL not require authentication in this iteration
The system SHALL allow access to the product-facing experience without login, session establishment, or user identity prompts in this change.

#### Scenario: Anonymous user enters the app
- **WHEN** a user opens a product-facing route without any prior session
- **THEN** the system renders the route normally without redirecting to login or showing account gating

