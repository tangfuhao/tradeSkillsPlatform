## Why

The new product-facing shell and replay theater give TradeSkills a strong entry point, but the product surface still lacks two critical destinations: a signal view that turns live outputs into a browsable feed, and a strategy view that turns raw Skill records into readable product profiles. Without those pages, the home route still carries too much of the product story by itself.

This change is needed now because the homepage is ready to become a true hub rather than a stopgap landing page, and the backend already exposes enough data to build product-grade signals and strategy profile surfaces without introducing login or backend schema changes.

## What Changes

- Add a product-facing signals page that organizes recent live signals into a richer feed with linked strategy context.
- Add product-facing strategy profile pages that present a Skill as a readable strategy artifact with validation, cadence, risk, and recent execution context.
- Strengthen the product home information architecture so it routes users more clearly into replays, signals, and strategy exploration.
- Extend the product route tree and navigation to support the new destinations without changing the operator console model.

## Capabilities

### New Capabilities
- `signals-surface`: Product-facing live signal feed with strategy linkage, delivery context, and user-readable signal summaries.
- `strategy-profile-pages`: Product-facing strategy profile routes that translate Skill metadata into readable strategy cards and execution context.
- `home-information-architecture`: Stronger homepage structure that acts as a hub for replay, signal, and strategy discovery.

### Modified Capabilities
- None.

## Impact

- Affected code: `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/*`, especially route definitions, page components, API helpers, and homepage composition.
- Public APIs remain compatible; the frontend will rely more heavily on `/api/v1/skills`, `/api/v1/live-tasks`, `/api/v1/live-signals`, and `/api/v1/backtests` to compose product-facing relationships.
- No backend migration is required; this is a frontend product expansion using existing data contracts.
