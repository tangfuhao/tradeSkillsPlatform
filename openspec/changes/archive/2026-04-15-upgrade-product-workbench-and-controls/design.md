## Context

The current frontend already separates product routes from the operator console, but the product-facing experience still reuses a single card-heavy visual language and a narrative-first information architecture. This makes the application feel expressive but not operational: high-value data and controls do not stand out clearly, the homepage mixes overview and marketing copy, and the list/detail pages for strategies, replays, and signals do not yet reflect the product's true entity relationships.

The current backend also exposes only part of the control surface the proposed workbench needs. Strategies can be created and read, backtests can be created and read, and live tasks can be created, listed, and manually triggered. However, there is no public lifecycle API for pausing, stopping, resuming, or deleting executions; live-task portfolio data exists but is not consumed in the product UI; and the data model still allows multiple live tasks per strategy even though the intended product model is one strategy to many backtests and at most one live runtime.

There is one especially important technical constraint: backtests currently run inside a single FastAPI background task loop. That architecture supports queued and completed states, but it is not a safe foundation for pause/resume/stop semantics because the run is not checkpointed at a platform-level control boundary between steps.

## Goals / Non-Goals

**Goals:**
- Establish a disciplined trading-workbench visual and navigation system that improves information hierarchy and action clarity.
- Restructure the homepage into a concise operational hub with direct visibility into live performance, recent backtests, recent strategies, and strategy entry.
- Make strategies the primary product entity, with explicit associations to many backtests and at most one live runtime.
- Introduce lifecycle controls and progress reporting for backtests and live runtimes in a way the UI can consume consistently.
- Preserve read-only strategy detail pages while making the strategies index a management surface.
- Keep the operator console available as a separate route during and after the redesign.

**Non-Goals:**
- Introduce authentication, multi-user ownership, or role-based permissions.
- Change the core decision schema returned by the agent runtime.
- Rebuild the operator console as part of this change.
- Deliver advanced performance analytics beyond the summary metrics needed for the workbench.
- Introduce a full job queue platform if a simpler persisted execution driver can satisfy lifecycle controls.

## Decisions

### 1. Keep the existing route tree, but reinterpret product routes as a workbench
The product route tree remains centered on `/`, `/replays`, `/replays/:runId`, `/signals`, and `/strategies`, with `/console` preserved as a separate operator route. The redesign changes the shell, wording, and page composition rather than introducing a parallel app.

Rationale:
- Preserves current navigation investment and minimizes migration risk.
- Keeps implementation focused on hierarchy and control surfaces instead of route churn.
- Avoids breaking deep links to existing product pages.

Alternatives considered:
- Introduce a brand-new route tree for an admin app: rejected because it increases migration and content duplication.
- Push all management behavior back into `/console`: rejected because the user-facing product routes must now support real operations, not just storytelling.

### 2. Make strategy the primary entity and enforce one live runtime per strategy
Frontend view models and backend lifecycle rules will treat a strategy as the primary product entity. A strategy can own many backtests and at most one live runtime. The strategies index will surface those associations directly, while the strategy detail page remains read-only and describes the immutable strategy artifact plus linked execution context.

Rationale:
- Matches the intended product mental model and simplifies navigation.
- Prevents duplicate live runtimes from causing inconsistent portfolio and signal context.
- Makes destructive actions explainable because related executions are attached to one strategy anchor.

Alternatives considered:
- Continue allowing multiple live tasks per strategy and resolve ambiguity in the UI: rejected because it weakens operability and makes strategy-level monitoring noisy.
- Remove strategy detail pages and make the list row the only surface: rejected because read-only profiles still provide useful context for validation, risk, and tooling.

### 3. Separate strategy management and strategy reading within the same capability family
The `/strategies` route becomes a management surface with denser rows, linked execution summaries, create/delete actions, and control affordances. The `/strategies/:skillId` route remains a read-only profile page that focuses on immutable strategy metadata and linked execution evidence rather than inline editing.

Rationale:
- Aligns list pages with action-heavy operator needs without losing a stable detail page.
- Supports the immutability rule that strategies cannot be edited after creation.
- Lets the homepage and signals page deep-link into either management or details depending on intent.

Alternatives considered:
- Put destructive and lifecycle controls on the profile page only: rejected because bulk operational work starts from the index.
- Allow inline editing of strategy text: rejected because it would desynchronize existing live/backtest artifacts from the strategy definition they were created from.

### 4. Introduce a shared execution lifecycle contract with scope-specific available actions
Backtests and live runtimes will expose a common response shape for lifecycle metadata:
- current status
- progress summary (when applicable)
- last activity timestamps
- supported/available actions
- linked strategy id

The concrete state machines remain scope-specific:
- Backtests: `queued`, `running`, `paused`, `stopping`, `stopped`, `completed`, `failed`
- Live runtimes: `active`, `paused`, `stopped`, `failed`

Control APIs will use a shared command pattern such as `POST /api/v1/backtests/{id}/control` and `POST /api/v1/live-tasks/{id}/control` with action payloads, plus explicit delete endpoints for permanent removal.

Rationale:
- Gives the frontend one consistent way to render badges, progress, and action menus.
- Avoids pretending both execution scopes share identical lifecycle semantics.
- Keeps future actions extensible without multiplying one-off endpoints.

Alternatives considered:
- Separate bespoke endpoints for each action (`/pause`, `/resume`, `/stop`): rejected because it fragments the client contract and complicates action availability handling.
- A single global status enum for every execution scope: rejected because backtests and live runtimes have materially different behavior.

### 5. Refactor backtests from fire-and-forget loops to checkpointed execution batches
Backtests will move away from a single long-running FastAPI background task and into a checkpointed execution driver that commits progress after one or a small batch of trigger steps. Each batch checks the persisted control state before continuing.

The run record (or closely related execution metadata) will persist:
- total trigger count
- completed trigger count
- last processed trigger index/time
- current control state
- progress percent / current phase

Rationale:
- Makes pause, resume, and stop semantics technically reliable.
- Enables progress reporting without guessing from trace counts alone.
- Improves crash recovery because runs can resume from persisted checkpoints.

Alternatives considered:
- Keep the current loop and poll status inside it: rejected because it still leaves long uncontrolled stretches and weak restart behavior.
- Introduce a heavyweight queue system immediately: rejected for now because the product likely needs checkpointing more than infrastructure breadth in this phase.

### 6. Implement live-runtime controls by combining persisted task state with scheduler job management
Live runtimes already have a scheduler abstraction. This change will extend live-task lifecycle management by persisting paused/stopped state and mapping it to scheduler job creation/removal. `pause` unschedules future triggers but preserves state and portfolio; `resume` re-schedules the task; `stop` ends the runtime and disallows further triggers unless a new runtime is created or the system explicitly allows restart semantics.

Rationale:
- Uses the existing APScheduler integration instead of inventing a second trigger system.
- Makes live controls comparatively cheap once task states and delete semantics are formalized.
- Preserves paper-trading portfolio continuity for paused tasks.

Alternatives considered:
- Delete and recreate live tasks for every pause/resume: rejected because it destroys runtime continuity and confuses signals/history.
- Keep a paused scheduler job instead of removing it: rejected because persisted state is the true source of truth and is easier to restore on reboot.

### 7. Hard-delete strategy-linked executions only through explicit cascade semantics
Deleting a strategy will permanently remove the strategy plus its related backtests, traces, live runtime, signals, and scope-specific portfolio/state records. The UI must present the cascade clearly before confirmation. Standalone execution deletion remains available from its own list surfaces.

Rationale:
- Matches the user's requested management model and avoids orphaned execution records.
- Keeps the data model explainable: executions belong to strategies.
- Makes the destructive action meaningful enough to require clear confirmation copy.

Alternatives considered:
- Soft-delete strategies but keep executions visible: rejected because it complicates the product mental model and leaves unresolved ownership.
- Forbid strategy deletion once executions exist: rejected because the user explicitly wants strategy-level cleanup.

### 8. Use a denser view-model layer instead of introducing a new backend aggregation endpoint first
The frontend will continue to compose most workbench data from existing list/read APIs plus a limited number of additional lifecycle and live-portfolio endpoints. The view-model layer in `apps/web/src/lib/*` will be expanded to derive strategy summaries, runtime states, and homepage modules.

Rationale:
- Keeps the API surface focused on lifecycle and persistence gaps rather than pre-optimizing for a bundle endpoint.
- Leverages current frontend composition patterns already present in `lib/product.ts`.
- Leaves room for a later summary endpoint if active runtime counts grow.

Alternatives considered:
- Add one large `/dashboard` aggregation endpoint now: rejected because the change is already introducing lifecycle APIs and runner changes; a bundle endpoint can come later if needed.

## Risks / Trade-offs

- [Backtest pause/resume requires more execution refactoring than expected] → Mitigation: implement checkpointed execution first, then layer UI controls on top of persisted state rather than simulating controls client-side.
- [Cascade deletion removes data users later want to keep] → Mitigation: require explicit confirmation copy that enumerates affected artifacts before delete proceeds.
- [Fetching live portfolio state for multiple runtimes increases frontend request volume] → Mitigation: restrict portfolio fetches to active runtimes and cache/reuse summaries within a refresh cycle.
- [The workbench redesign loses too much of the current visual identity] → Mitigation: preserve strong branding cues in a restrained shell while shifting hierarchy, density, and typography toward professional use.
- [UI exposes actions before the backend can enforce them consistently] → Mitigation: render controls from `available_actions` metadata returned by lifecycle endpoints rather than hard-coding assumptions.

## Migration Plan

1. Extend data models and schemas for execution lifecycle state, progress metadata, and strategy ownership constraints.
2. Refactor backtest execution into checkpointed batches and add control endpoints plus delete semantics.
3. Extend live-task lifecycle APIs and scheduler integration for pause/resume/stop/delete.
4. Update frontend API utilities and view-model composition to consume lifecycle metadata and live portfolio summaries.
5. Redesign product shell, homepage, replay pages, signals page, and strategies surfaces around the new workbench IA.
6. Validate destructive flows, execution recovery, and route behavior; keep `/console` available as an operational fallback throughout rollout.

Rollback strategy:
- Frontend route/layout changes can be rolled back independently by redeploying the prior web build.
- Backend lifecycle changes should be guarded so legacy list/read behavior continues to work while new control fields are additive.
- If checkpointed backtest execution proves unstable, the system can temporarily disable pause/resume UI affordances and fall back to stop/delete-only behavior while preserving the new response shape.

## Open Questions

- Whether stopped live runtimes should be resumable in place or whether resume should be limited to paused runtimes only.
- Whether strategy deletion should hard-delete signal history immediately or archive it into a separate audit export before removal.
- Whether active-runtime portfolio summaries should continue to be composed client-side or be promoted to a small server-side summary endpoint in a follow-up.
