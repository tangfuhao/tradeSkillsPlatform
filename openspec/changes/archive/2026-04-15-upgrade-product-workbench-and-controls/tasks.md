## 1. Backend lifecycle foundation

- [x] 1.1 Extend strategy, backtest, and live-runtime schemas/models/serializers to expose ownership, lifecycle state, progress metadata, and available actions.
- [x] 1.2 Add lifecycle control and delete endpoints for backtests, live runtimes, and strategies.
- [x] 1.3 Implement shared cleanup utilities so execution-scoped traces, signals, portfolio books, and scheduler registrations are removed consistently.

## 2. Backtest execution controls

- [x] 2.1 Refactor backtest execution into checkpointed batches that persist step progress between control boundaries.
- [x] 2.2 Implement pause, resume, and stop transitions for backtests and wire them to action availability in API responses.
- [x] 2.3 Add backend tests for backtest progress reporting, interruption flows, and deletion cleanup.

## 3. Live runtime controls

- [x] 3.1 Enforce the one-live-runtime-per-strategy rule in activation flows and return clear ownership errors or existing runtime context.
- [x] 3.2 Implement pause, resume, stop, and delete behavior for live runtimes together with scheduler add/remove/restore handling.
- [x] 3.3 Add backend tests for duplicate activation rejection, scheduler restoration, runtime controls, and runtime cleanup.

## 4. Product workbench redesign

- [x] 4.1 Replace the current product shell styling with a denser workbench-oriented layout, hierarchy, and responsive surface system.
- [x] 4.2 Rebuild the homepage around live performance, recent backtests, recent strategies, and direct strategy-skill entry.
- [x] 4.3 Convert replay list and replay detail pages into operational surfaces with lifecycle actions, progress, and focused current-run detail.
- [x] 4.4 Reorganize the signals page around strategy-grouped runtime monitoring with recent signals and live performance context.
- [x] 4.5 Convert the strategies route into a management surface while keeping strategy detail pages read-only and execution-linked.

## 5. Integration and verification

- [x] 5.1 Update frontend API helpers and view-model composition to consume lifecycle metadata, live portfolio summaries, and strategy ownership constraints.
- [x] 5.2 Add confirmation flows, disabled-action states, empty states, and mobile validations for destructive and lifecycle actions.
- [x] 5.3 Run build and targeted backend/frontend checks covering strategy creation, execution controls, strategy deletion cascade, and core product routes.
