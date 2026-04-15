## ADDED Requirements

### Requirement: Product-facing routes SHALL provide a direct experience-first entry
The web application SHALL expose a product-facing default route that presents TradeSkills as an explorable trading product rather than as an operator console.

#### Scenario: User opens the default route
- **WHEN** a user navigates to the web application's root path
- **THEN** the system shows a product-facing page with branded navigation, product framing, and direct access to replay exploration

### Requirement: Product routes SHALL share a Neon Noir application shell
All product-facing routes SHALL use a consistent layout, theme token system, and visual framing aligned with the Neon Noir direction.

#### Scenario: User navigates between product routes
- **WHEN** a user moves between supported product-facing routes
- **THEN** the system preserves consistent navigation, atmospheric theming, and page shell behavior across those routes

### Requirement: Product routes SHALL not require authentication in this iteration
The system SHALL allow access to the product-facing experience without login, session establishment, or user identity prompts in this change.

#### Scenario: Anonymous user enters the app
- **WHEN** a user opens a product-facing route without any prior session
- **THEN** the system renders the route normally without redirecting to login or showing account gating
