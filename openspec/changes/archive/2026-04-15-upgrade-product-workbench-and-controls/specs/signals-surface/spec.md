## MODIFIED Requirements

### Requirement: Product routes SHALL provide a dedicated signals feed
The product-facing web experience SHALL expose a signals route that organizes recent live signals around actively running strategies rather than only as a flat reverse-chronological feed.

#### Scenario: User opens the signals route
- **WHEN** a user navigates to the signals route
- **THEN** the system renders grouped real-time monitoring surfaces for active or recently active strategies with signal summaries and runtime context

### Requirement: Signals SHALL link to their related strategies when possible
The signals experience SHALL connect each signal to its underlying strategy and runtime context when the relationship can be derived from platform data.

#### Scenario: Signal has resolvable strategy context
- **WHEN** the frontend can map a signal through its live runtime to a strategy
- **THEN** the signals page shows the strategy title, runtime state, and a navigation path to the related strategy detail surface

## ADDED Requirements

### Requirement: Signals surface SHALL show live performance context for active runtimes
The signals surface SHALL display paper-trading performance and recent runtime state alongside signals for strategies that currently own a live runtime.

#### Scenario: Active runtime has portfolio context
- **WHEN** a strategy has an active or paused live runtime and portfolio summary data is available
- **THEN** the signals surface shows recent performance indicators, last activity, and recent signal flow together for that runtime
