## 1. Data model and universe management

- [x] 1.1 Add persistent market instrument, sync state, sync attempt, and coverage snapshot models for the new market sync runtime.
- [x] 1.2 Implement OKX `SWAP` universe discovery, lifecycle transitions, priority-tier assignment, and symbol sync-state initialization.
- [x] 1.3 Add recent bootstrap and deferred backfill behavior so new or deeply lagged symbols can become live-eligible without waiting for full history.

## 2. Queue-backed sync runtime

- [x] 2.1 Introduce Redis-backed queue primitives and a worker process for universe refresh, symbol sync, coverage aggregation, and live dispatch jobs.
- [x] 2.2 Refactor market sync execution to run per symbol with leases, retry/backoff, attempt auditing, and bounded per-run sync budgets.
- [x] 2.3 Preserve API-process compatibility by exposing worker heartbeat state through the existing market sync loop snapshot interface.

## 3. Live gating and operator surfaces

- [x] 3.1 Replace whole-sweep live gating with aggregated `dispatch_as_of_ms` coverage snapshots and degraded execution support.
- [x] 3.2 Propagate coverage metadata and fresh-symbol filtering into live execution, watchlist validation, and stored signal records.
- [x] 3.3 Extend health and market-data APIs with sync status, universe inspection, coverage, bootstrap, and backlog metrics.

## 4. Runtime wiring and validation

- [x] 4.1 Add Redis dependency, environment settings, docker worker wiring, and local dev scripts for the queue-backed runtime.
- [x] 4.2 Add market sync engine tests covering coverage thresholds, degraded dispatch, API status fields, and worker heartbeat compatibility.
- [x] 4.3 Validate the updated API and runtime entry points with unit tests and import checks.
