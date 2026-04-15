## Context

The current web frontend is implemented as a single monolithic React component that combines product messaging, operator controls, health checks, backtest management, live task actions, and raw execution traces on one page. This structure makes the experience useful for debugging but weak for user-facing storytelling, especially now that the product needs to present TradeSkills as a direct, explorable trading experience.

The backend already provides the main primitives needed for a richer frontend: backtest lists, traces, portfolio snapshots, live signals, market overview, and candle queries. The design challenge is therefore primarily on the frontend side: route separation, page composition, view-model shaping, and a visual language that can support both a product-facing surface and an operator console without duplicating logic.

Constraints for this change:
- No login, user session, or personalized account model is introduced in this iteration.
- The existing operator workflows must remain available, but no longer dominate the default route.
- Backtest runs often rotate across multiple symbols, so replay UX cannot assume a single-symbol narrative.
- The product-facing experience should adopt a Neon Noir visual direction while remaining responsive and readable.

## Goals / Non-Goals

**Goals:**
- Split the frontend into a product-facing route tree and a dedicated operator console route.
- Establish a reusable app shell, route-level pages, and a shared data/view-model layer instead of a monolithic `App.tsx`.
- Introduce a Neon Noir theme foundation that can support atmospheric product pages and chart-heavy replay views.
- Create a replay experience structure that can handle multi-symbol backtests and prepare for `lightweight-charts` overlays.
- Preserve the existing operational controls so development and debugging remain possible during the transition.

**Non-Goals:**
- Implement authentication, session storage, or per-user workspaces.
- Deliver the final replay chart overlay system in the first implementation slice.
- Change backend persistence or public API contracts unless a small frontend-enabling addition becomes necessary later.
- Rebuild the entire operator console UX in this first pass.

## Decisions

### 1. Introduce route-based frontend architecture
The app will move from a single-page dashboard to a route-based structure with product and console branches. The initial route tree will include `/`, `/replays/:runId`, and `/console`, with additional product routes able to land incrementally.

Rationale:
- Creates clear separation between user-facing exploration and operator workflows.
- Allows the product home to become the primary experience without deleting debug capabilities.
- Reduces the need for a single giant stateful component.

Alternatives considered:
- Keep one page and toggle between “product mode” and “console mode”: rejected because it preserves the same monolithic information architecture.
- Create a separate frontend app for console: rejected for now because it would duplicate data wiring and slow iteration.

### 2. Extract the current dashboard into a `ConsolePage`
The current dashboard logic will be preserved as a dedicated route component with minimal behavioral change during the first pass. The product-facing pages will sit alongside it rather than replacing it immediately.

Rationale:
- Lowest-risk path to preserve debugging value.
- Lets us improve product perception without stalling ongoing development workflows.
- Gives a clean baseline to iterate on the console independently later.

Alternatives considered:
- Rewrite the console at the same time as the product pages: rejected because it increases scope and slows down the product-facing transition.

### 3. Build a shared app shell and design-token system first
The product-facing routes will share a `ProductLayout` with global navigation, page framing, and theme tokens. The Neon Noir system will be implemented through CSS variables and reusable surface primitives rather than page-local styling.

Rationale:
- Ensures visual consistency across the home page, replay experience, and future signal pages.
- Makes the thematic direction maintainable instead of hard-coded in one stylesheet.
- Supports a gradual migration away from the current warm editorial styling.

Alternatives considered:
- Apply Neon Noir styling directly inside existing classes: rejected because it would entrench old structure and limit reuse.

### 4. Model replay views around run + symbol slices
Replay pages will treat a backtest as a collection of symbol-specific moments rather than a single-symbol chart. The frontend will derive symbol slices from traces, fills, and decisions so the user can switch context within the same run.

Rationale:
- Matches the product reality that backtests rotate across multiple symbols.
- Prevents the replay page from breaking when a run has several traded assets.
- Creates a stable view-model that can later drive chart overlays and trade markers.

Alternatives considered:
- Assume one run equals one symbol: rejected because it conflicts with current strategy behavior.
- Force a single aggregate chart across all symbols: rejected because the price series would be misleading and hard to interpret.

### 5. Stage charting behind chart-ready view models
The first implementation slice will not fully integrate `lightweight-charts`, but it will create the route, layout, symbol switching, and data-composition seams required for chart adoption in the next slice. The replay page will expose selected run, selected symbol, grouped traces, and chart placeholder regions.

Rationale:
- Lets us improve information architecture and route structure immediately.
- Reduces risk by not combining a large UI refactor with a full charting integration in one pass.
- Makes the next charting step mostly additive.

Alternatives considered:
- Defer replay restructuring until charting is ready: rejected because the information architecture problem exists even without charts.
- Add charts directly inside the current dashboard: rejected because it would compound the monolith.

## Risks / Trade-offs

- [Product and console drift into separate patterns too early] → Mitigation: keep shared data fetch utilities and primitive UI components where practical.
- [Neon Noir styling harms readability or looks gimmicky] → Mitigation: implement theme tokens with strong contrast and readable typography, then validate on desktop and mobile.
- [Replay pages need more aggregated data than current APIs provide] → Mitigation: compose a frontend view model first; if pain remains, add a replay bundle API in a follow-up.
- [Moving the current page into `/console` introduces regressions] → Mitigation: preserve current logic first, refactor internals after routing is stable.
- [Users land on product pages that promise charting before it exists] → Mitigation: make placeholders explicit about “replay theater” progress and show meaningful multi-symbol trace views from day one.

## Migration Plan

1. Add routing and a product-facing app shell while preserving the existing dashboard behavior inside a `ConsolePage`.
2. Move the current default experience behind `/console` and switch `/` to the product home.
3. Introduce Neon Noir tokens and product layouts, then migrate product routes to the new styling.
4. Add replay route data composition for run selection, symbol slicing, and chart-ready page regions.
5. Validate the build and keep fallback access to `/console` throughout the migration.

Rollback strategy:
- Because the initial change is frontend-only, rollback is a simple redeploy to the previous web build if route or styling changes regress local workflows.

## Open Questions

- Whether the first replay theater iteration should prioritize per-symbol trade timelines, equity summaries, or chart overlays once `lightweight-charts` is integrated.
- Whether future product pages need dedicated routes for strategies and live signals, or whether the product home should remain the main aggregator for those views.
