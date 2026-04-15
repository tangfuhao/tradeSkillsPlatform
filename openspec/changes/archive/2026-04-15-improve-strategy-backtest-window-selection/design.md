## Context

The current strategy operations page loads market coverage through the same `getMarketOverview()` call already used elsewhere, but it only derives a single `defaultBacktestWindow` and wires the backtest action to an immediate confirmation dialog. This makes the product-facing strategy route less trustworthy than the operator console, even though the backend already accepts arbitrary start and end times inside local historical coverage and rejects invalid windows.

The change spans multiple frontend concerns: strategy actions, shared date-window helpers, validation messaging, and parity with the console's backtest launcher. The backend contract can remain unchanged as long as the strategy page reuses existing market-overview coverage metadata and the existing create-backtest API.

## Goals / Non-Goals

**Goals:**
- Let users launch a strategy-page backtest with explicit start time, end time, and initial capital.
- Constrain the visible and selectable replay window to the locally available historical coverage.
- Keep a recent-24-hour default or preset for convenience without making it the only launch path.
- Reduce divergence between the strategy page and the console by reusing shared validation and default-window logic.

**Non-Goals:**
- Redesign the operator console backtest experience.
- Change backend backtest creation semantics or add new API endpoints unless implementation reveals a hard blocker.
- Add advanced preset systems such as "last 7 days" or symbol-specific coverage calculations in this change.

## Decisions

### Decision: Replace the one-click confirm flow with a lightweight launch surface
The strategy page will stop mapping `create_backtest` directly to a `window.confirm` call. Instead, that action opens a small launch surface in-context (modal, drawer, or inline panel) where the selected strategy is fixed and the user edits the backtest inputs before submission.

Why:
- It preserves the strategy page as the entry point while adding the control users expect.
- It avoids overloading destructive-style browser confirms with form behavior.
- It keeps the lifecycle action model intact: the action still starts from the strategy card, but execution only begins after explicit configuration.

Alternatives considered:
- Navigate users to the console for all backtests: rejected because the user wants the strategy page itself to be robust.
- Keep one-click launch and add more presets only: rejected because presets still do not cover arbitrary replay windows.

### Decision: Use market coverage metadata as the authoritative UI bound
The strategy page launcher will use the existing `MarketOverview.coverage_start_ms` and `coverage_end_ms` values to display the available historical window, seed defaults, and set input bounds. The UI will reject obviously invalid entries before calling `createBacktest`, while the backend remains the final validator.

Why:
- The data already exists in the product web app and is the same source used by the console.
- It keeps the visible affordances aligned with actual system constraints.
- It avoids adding a strategy-specific coverage endpoint for a global market-data constraint.

Alternatives considered:
- Infer valid bounds locally from the default 24-hour window: rejected because it hides the true coverage range.
- Depend on backend-only validation with no UI bounds: rejected because it creates a trial-and-error experience.

### Decision: Extract shared backtest-launch helpers instead of duplicating logic again
The current `getDefaultBacktestWindow` logic already exists in multiple web files. This change should centralize the reusable parts of backtest-launch state shaping and validation so the strategy page and console speak the same rules for default values, displayed coverage, and basic input validation.

Why:
- The user explicitly expects strategy-page behavior to match the console.
- Shared logic lowers the risk of one surface allowing values the other one hides or formats differently.
- It keeps future launcher improvements from splitting across pages.

Alternatives considered:
- Copy the console form into the strategy page and tune it separately: rejected because it repeats the problem that caused the current drift.

## Risks / Trade-offs

- [Strategy page gains more UI complexity than a single action button] → Mitigation: keep the launcher focused on three required inputs plus coverage context, and defer advanced presets.
- [Frontend validation can drift from cadence-aware backend validation] → Mitigation: reuse shared helpers for obvious checks, but treat backend errors as the source of truth and surface them directly.
- [Local `datetime-local` handling may create timezone confusion near coverage edges] → Mitigation: continue using the existing local datetime formatting helpers and show the full coverage timestamps alongside the editable fields.
- [Shared helper extraction touches both strategy and console code] → Mitigation: keep the shared module narrow and migrate callers incrementally rather than rewriting both pages at once.

## Migration Plan

1. Introduce shared backtest-launch helper logic in the web app for default coverage-aligned values and simple field validation.
2. Replace the strategy-page one-click confirm with a configuration surface wired to the selected strategy.
3. Validate the chosen values against coverage bounds before calling `createBacktest`, while preserving backend error handling for final enforcement.
4. Update strategy-page copy and metrics so "recent 24 hours" is presented as a default/preset instead of the only supported window.

Rollback strategy:
- If the new launcher proves unstable, the strategy page can temporarily hide the configurable surface and fall back to routing users to the console launcher, while preserving the new shared helpers for later reuse.

## Open Questions

- Whether the strategy page should open the launcher as a modal or as an expanded inline card beneath the selected strategy.
- Whether initial capital should keep the current fixed `10_000` default or inherit a shared default from the console if one is later centralized.
