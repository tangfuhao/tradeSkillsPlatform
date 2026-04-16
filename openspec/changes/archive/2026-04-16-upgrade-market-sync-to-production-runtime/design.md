## Context

The original live market sync path couples three concerns into one loop: discovering what to sync, fetching new candles, and deciding whether live tasks may run. That works for a small locally seeded symbol set, but it breaks down once the platform must track the full OKX swap universe, absorb new listings automatically, and keep dispatch moving when a few symbols are stale or failing.

This branch already implements a broader production-style design: persistent instrument and sync-state tables, queue-backed worker orchestration, per-symbol sync attempts, aggregated coverage snapshots, and live dispatch keyed off `dispatch_as_of_ms` rather than a whole-sweep success bit. The OpenSpec change needs to document that behavior as the intended contract.

## Goals / Non-Goals

**Goals:**
- Track the full active OKX `SWAP` universe in persistence, including lifecycle changes for suspended and delisted contracts.
- Sync recent market data independently per symbol so new listings, long backlogs, and symbol-level failures do not block the whole runtime.
- Produce one aggregated market coverage gate that live dispatch and manual triggers can both trust.
- Allow degraded live execution when the configured active coverage threshold is met and all `tier1` symbols are fresh.
- Expose enough health and operator status metadata to debug freshness, bootstrap, backlog, and blocked dispatch reasons.
- Preserve compatibility with the existing application process by letting `MarketSyncLoopSnapshot` mirror worker heartbeat state.

**Non-Goals:**
- Introduce websocket market data ingestion or tick-level trading.
- Guarantee 100 percent fresh coverage for every active symbol before each live dispatch.
- Backfill full historical depth before a newly listed symbol becomes live-eligible.
- Replace the existing historical CSV seeding workflow.

## Decisions

### 1. Split universe discovery from symbol sync execution
- Persist instrument metadata in `MarketInstrument` and update it from periodic OKX `SWAP` discovery calls.
- Classify instruments as `active`, `suspended`, or `delisted`, retain history for delisted contracts, and recompute `tier1` membership from observed 24h volume.
- Chosen because live coverage should follow the exchange universe, not only symbols already present in local candles.
- Alternative considered: continue inferring the universe from local data. Rejected because new listings would not enter sync until some external seed step created them.

### 2. Move from sweep-scoped sync to symbol-scoped state machines
- Persist one `MarketSyncState` row per symbol/timeframe plus `MarketSyncAttempt` audit rows.
- Schedule due symbols into priority queues, acquire a short lease per symbol, and enforce per-run page/time budgets.
- Use recent bootstrap for new or badly lagging symbols, keep deeper history as asynchronous backfill, and commit progress page by page.
- Chosen because symbol isolation keeps backlog and retry behavior bounded.
- Alternative considered: keep a single cursor per sweep. Rejected because a single slow symbol can delay or poison the entire cadence.

### 3. Use Redis queues and worker heartbeat as the production control plane
- Introduce Redis queues for universe refresh, symbol sync, coverage aggregation, and live dispatch.
- Let the external worker publish heartbeat state; the in-process loop becomes a compatibility view that reads that heartbeat when queue mode is enabled.
- Chosen because the worker can scale independently from the API process and makes scheduling/dispatch observable.
- Alternative considered: keep all scheduling inside the API process. Rejected because it couples runtime health to web process lifetime and makes queue-level isolation impossible.

### 4. Promote coverage snapshots to the only live dispatch gate
- Recompute `MarketCoverageSnapshot` whenever universe or symbol sync state changes.
- Advance `dispatch_as_of_ms` only when all `tier1` active symbols are fresh and the configured active coverage ratio is satisfied.
- Enqueue live dispatch only when that aggregated `dispatch_as_of_ms` moves forward.
- Chosen because dispatch should depend on market-wide readiness, not whether an arbitrary sync loop iteration happened to succeed.
- Alternative considered: dispatch on every symbol success. Rejected because different live tasks would observe inconsistent market cutoffs.

### 5. Allow degraded live execution, but constrain the candidate set
- Pass coverage metadata into live execution context and stored signals.
- Limit scan-style market snapshots to fresh symbols when coverage is degraded, and block any watchlist-based task whose required symbols are not fresh.
- Chosen because this keeps live execution moving without silently evaluating stale symbols.
- Alternative considered: block all dispatch unless coverage is 100 percent. Rejected because it makes the system too brittle for large universes.

### 6. Keep rollout incremental and backwards compatible
- Retain the existing `sync_incremental_okx_history` entry point and `MarketSyncLoopSnapshot` shape so existing health consumers do not break immediately.
- Surface the new worker-based data through `/health`, `/market-data/overview`, `/market-data/sync-status`, and `/market-data/universe`.
- Chosen because the system already has consumers of the previous runtime snapshot fields.

## Risks / Trade-offs

- [Redis outage blocks queue mode] -> Expose blocked health state through heartbeat/snapshot fields and keep the legacy in-process path available when queue mode is disabled.
- [Universe growth increases sync cost] -> Tier the active set, budget symbol work per run, and divert deep gaps into low-priority backfill.
- [Coverage snapshots can flap around the threshold] -> Use `dispatch_as_of_ms` advancement as the dispatch trigger so repeated recomputes do not cause duplicate live runs.
- [Worker crash may leave an abandoned symbol lease] -> Store lease expiry in `MarketSyncState` and allow later workers to reclaim expired symbols.
- [Degraded execution can hide missing symbols] -> Record coverage metadata and missing symbol samples in signal payloads and health/overview APIs.

## Migration Plan

1. Apply schema changes for instruments, sync states, sync attempts, and coverage snapshots.
2. Deploy API code that can read the new models and expose compatibility health fields.
3. Enable Redis and start the market sync worker in environments that want queue-backed orchestration.
4. Turn on `market_sync_queue_enabled` so startup enqueues universe refresh and the API loop switches to worker-heartbeat mode.
5. Monitor coverage ratio, blocked reasons, and worker heartbeat before relying on the new gate for manual/live operations.
6. If rollback is needed, disable queue mode and fall back to the legacy in-process sync loop while keeping the added tables intact.

## Open Questions

- Whether `tier1` should remain volume-ranked only or incorporate strategy/watchlist demand in a later change.
- Whether deeper historical backfill should eventually move to a separate worker pool with its own throughput controls.
- Whether future production deployments should replace REST-only recent sync with websocket-assisted freshness for the hottest symbols.
