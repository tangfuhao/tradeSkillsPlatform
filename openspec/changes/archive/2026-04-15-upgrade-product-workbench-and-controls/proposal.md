## Why

The current product frontend has route separation, but it still feels like a stylized debug console rather than a high-confidence trading workbench. The visual system is overly card-driven and theatrical, the homepage carries too much explanatory content, and the core execution surfaces do not yet support the operational controls users now expect for strategies, backtests, and live runtimes.

This change is needed now because the product already has enough data relationships to present a tighter workbench experience, and the next round of frontend improvements will only feel coherent if the UI hierarchy, strategy associations, and execution lifecycle controls are specified together.

## What Changes

- Replace the current product-facing visual direction with a more disciplined trading workbench style that improves hierarchy, density, readability, and action affordances across desktop and mobile.
- Rebuild the homepage into a concise operational hub centered on four modules: current live strategy performance, recent backtests, recent strategies, and a direct strategy-skill input entry.
- Turn the replay list into an execution management surface with richer status, progress, and lifecycle actions, and refocus replay detail pages on the currently selected run instead of nearby run browsing.
- Reorganize the signals experience around actively running strategies so users can inspect real-time signal flow, paper-trading performance, and runtime state together.
- Convert the strategies route into a management surface that supports strategy creation entry, linked execution overview, destructive actions, and a read-only immutable strategy model after creation.
- Extend platform lifecycle controls so backtests and live runtimes can expose progress and user actions such as stop, pause, resume, and delete where supported.
- Enforce the product relationship that one strategy may own many backtests and at most one live runtime, and define cascade behavior when a strategy is deleted.

## Capabilities

### New Capabilities
- `strategy-operations-surface`: Product-facing strategy management surface with creation entry, association summaries, immutable strategy presentation, and linked execution actions.
- `execution-control-lifecycle`: Shared lifecycle and control model for backtests and live runtimes, including progress visibility, user-triggered control actions, and deletion semantics.

### Modified Capabilities
- `product-web-shell`: The product shell shifts from theatrical Neon Noir framing to a more disciplined workbench-oriented navigation and visual hierarchy.
- `home-information-architecture`: The homepage changes from a broad preview surface into a compact workbench hub with prioritized operational modules.
- `replay-theater`: Replay routes gain operational list behaviors and a more focused run-detail layout centered on the current backtest.
- `signals-surface`: The signals route changes from a flat recent-feed view to a strategy-grouped real-time monitoring surface with live performance context.
- `strategy-profile-pages`: Strategy routes distinguish between a management list surface and a read-only strategy detail surface tied to linked executions.
- `strategy-skill-management`: Strategy lifecycle rules expand to cover immutable strategies after creation, one-live-runtime-per-strategy constraints, and cascade deletion behavior.
- `backtest-simulation`: Backtest requirements expand to include progress reporting and controllable lifecycle states beyond fire-and-forget execution.
- `live-signal-execution`: Live execution requirements expand to include controllable runtime states and explicit constraints around unique active runtime ownership per strategy.

## Impact

- Affected frontend code: `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/layout/*`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/pages/*`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/styles.css`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/api.ts`, and `/Users/fuhao/Documents/hackson/tradeSkills/apps/web/src/lib/product.ts`.
- Affected backend code: `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/models.py`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/schemas.py`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/api/routes/backtests.py`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/api/routes/live_tasks.py`, `/Users/fuhao/Documents/hackson/tradeSkills/apps/api/app/api/routes/skills.py`, related services, and scheduler behavior.
- Public APIs will expand for strategy deletion and execution lifecycle controls; existing list/read flows remain, but UI behavior will depend on the new control and progress endpoints.
- The change may require modest persistence and scheduler updates to support controllable execution states, progress tracking, and one-live-runtime-per-strategy enforcement.
