## Why

The current web app presents TradeSkills as a single operational console, which makes the product feel debug-oriented rather than like a user-facing trading experience. We now need a product-first surface that lets users immediately understand what the Agent saw, what it traded, and what happened, while still preserving the existing console as a separate operator view.

This change is needed now because the backend already exposes the replay, trace, signal, and candle data required for a richer product experience, but the frontend does not yet organize those capabilities into a coherent information architecture.

## What Changes

- Introduce a product-facing web information architecture with dedicated routes for the product home, replay exploration, and console access.
- Reposition the existing single-page dashboard as a separate `/console` route for operator workflows, debugging, and raw inspection.
- Establish a new Neon Noir visual system for the product-facing experience, including product shell, theme tokens, navigation, and atmospheric styling.
- Add a replay-focused experience that frames backtests as multi-symbol trading stories rather than raw records, preparing the UI for chart overlays, trace context, and trade markers.
- Refactor the frontend into reusable route-level pages, layout primitives, and data-view models so future charting and live-signal experiences can be added without another monolithic page rewrite.

## Capabilities

### New Capabilities
- `product-web-shell`: Product-facing routing, navigation, and themed page shell for user-oriented exploration of TradeSkills.
- `replay-theater`: Multi-symbol replay browsing experience that turns backtest runs into a navigable trading narrative with clear entry points for charts, decisions, and outcomes.
- `operator-console-routing`: Dedicated operator console route that preserves the existing debug-heavy workflows without dominating the product surface.

### Modified Capabilities
- None.

## Impact

- Affected code: `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/*`, especially app bootstrapping, page structure, theme styling, and data composition.
- Public APIs remain compatible, but the frontend will rely more explicitly on `/api/v1/backtests`, `/api/v1/backtests/{run_id}/traces`, `/api/v1/backtests/{run_id}/portfolio`, and `/api/v1/market-data/candles`.
- New frontend dependencies are expected for routing and chart-ready UI scaffolding, starting with route management and preparing for `lightweight-charts` integration.
- This lays the groundwork for future replay bundles, richer chart overlays, and session-aware personalization without requiring those features in this change.
