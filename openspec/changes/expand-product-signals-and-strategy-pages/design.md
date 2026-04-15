## Context

The previous product refactor established a route-based shell, a dedicated console page, and a replay theater that made TradeSkills feel like a product rather than a single debug dashboard. However, the product surface still lacks destination pages for two other major concepts already present in the backend: live signals and strategy profiles.

The current homepage shows a small sample of recent signals and strategies, but it still does too much of the information architecture work itself. Users need deeper pages they can navigate to directly, and those pages need to stay consistent with the Neon Noir shell while reusing the same frontend data layer.

Constraints for this change:
- No user login or session state is introduced.
- Existing APIs must be composed client-side rather than replaced with new backend aggregation endpoints in this iteration.
- The new pages should strengthen product discoverability without weakening the existing replay theater or console paths.

## Goals / Non-Goals

**Goals:**
- Add a dedicated product-facing signals route.
- Add product-facing strategy listing/profile routes, with at minimum direct profile pages for individual skills.
- Upgrade the homepage so it acts as a more complete hub for the product's three core surfaces: replays, signals, and strategies.
- Reuse and extend the existing product shell, card patterns, and data helpers.

**Non-Goals:**
- Change backend schemas or add new public API endpoints.
- Add account personalization, saved views, or watchlists.
- Rework the replay theater information architecture again in this pass.

## Decisions

### 1. Add explicit routes for signals and strategies
The route tree will be expanded with `/signals`, `/strategies`, and `/strategies/:skillId`.

Rationale:
- A signal feed deserves a stable product destination.
- Strategy profiles need a routeable identity if the homepage is to become a real hub.
- A lightweight strategy index page avoids awkward navigation to a purely dynamic profile route.

Alternatives considered:
- Put all strategy detail only on the homepage: rejected because it keeps discovery shallow and makes the home route overloaded.
- Link signals directly to the console only: rejected because it preserves the operator-first mental model.

### 2. Compose signal-to-strategy relationships on the client
The signals page will resolve strategy context by joining `live_signals`, `live_tasks`, and `skills` in the frontend.

Rationale:
- Existing APIs already expose enough information to reconstruct the relationship.
- Avoids backend changes for a product-layer improvement.
- Keeps the implementation incremental.

Alternatives considered:
- Add a new backend feed endpoint first: rejected for now because the current data volume and product scope do not require it yet.

### 3. Present strategy profiles as product-readable summaries, not raw envelopes
The strategy profile page will translate cadence, validation, tool contracts, risk rules, and recent execution history into readable product sections rather than dumping raw JSON.

Rationale:
- Aligns with the product-first direction.
- Makes the strategy page useful to non-operators.
- Preserves raw inspection inside `/console`.

Alternatives considered:
- Reuse the console strategy box inside a product page: rejected because it would leak debug-first UX into the product surface.

### 4. Upgrade the homepage into a hub with stronger sectioned navigation
The homepage will be expanded with clearer directional sections and cross-links into signals and strategy pages.

Rationale:
- Lets the home route guide user flow rather than acting only as a hero plus previews.
- Makes the information architecture feel intentional and complete.

Alternatives considered:
- Leave home mostly unchanged and rely on top navigation only: rejected because the product is still new and benefits from stronger in-page orientation.

## Risks / Trade-offs

- [Client-side joins become brittle if API shapes drift] -> Mitigation: keep mapping logic centralized and typed.
- [Homepage becomes crowded again] -> Mitigation: segment content into distinct product sections with clear hierarchy and destination links.
- [Strategy pages feel thin when a skill has little execution history] -> Mitigation: show useful empty states and rely on cadence/risk/tool sections when history is sparse.
- [Signals page duplicates some home content] -> Mitigation: keep home to preview-level cards and reserve deeper feed context for `/signals`.

## Migration Plan

1. Extend routing and navigation to include signals and strategy destinations.
2. Add data helpers for individual skill retrieval and frontend joins between signals, live tasks, and skills.
3. Build strategy index/profile pages and the signals page.
4. Expand the homepage sections and cross-linking to the new destinations.
5. Rebuild and verify route rendering.

Rollback strategy:
- Frontend-only rollback to the previous build remains sufficient if the new product routes regress.
