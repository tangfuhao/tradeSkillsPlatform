# signals-surface Specification

## Purpose
TBD - created by archiving change expand-product-signals-and-strategy-pages. Update Purpose after archive.
## Requirements
### Requirement: Product routes SHALL provide a dedicated signals feed
The product-facing web experience SHALL expose a signals page that presents recent live signals as a browsable destination rather than only as a homepage preview.

#### Scenario: User opens the signals route
- **WHEN** a user navigates to the signals route
- **THEN** the system renders a product-facing feed of recent live signals with delivery context and signal summaries

### Requirement: Signals SHALL link to their related strategies when possible
The signals experience SHALL connect a signal to its underlying strategy context when the relationship can be derived from existing frontend data.

#### Scenario: Signal has resolvable strategy context
- **WHEN** the frontend can map a signal through its live task to a skill
- **THEN** the signals page shows the strategy title and provides a navigation path to the related strategy profile

