## Why

The current market sync runtime still behaves like a demo loop: one in-process sweep tries to advance local history, and live dispatch depends on that sweep finishing cleanly end to end. That model does not scale to the full OKX active swap universe, misses newly listed contracts unless they already exist locally, and lets backlog or single-symbol failures stall live execution.

## What Changes

- Replace sweep-scoped OKX sync gating with a production-style market sync runtime built around full-universe discovery, symbol-level sync state, and aggregated coverage snapshots.
- Persist the OKX active/suspended/delisted swap universe so new listings are bootstrapped automatically, delisted contracts keep their history, and high-frequency sync only targets eligible symbols.
- Introduce queue-backed symbol sync workers with per-symbol leases, retry/backoff, recent bootstrap windows, and backfill separation so large gaps do not block fresh coverage.
- Gate live dispatch and manual triggers on a shared `dispatch_as_of_ms` coverage snapshot that requires full `tier1` freshness and a configurable active-universe coverage ratio, while allowing degraded execution over the fresh subset.
- Expose operator-facing health, sync-status, overview, and universe metadata for freshness, bootstrap, backlog, and blocked-state inspection.
- Add Redis-backed worker runtime wiring and supporting configuration for local/dev and production deployment.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `historical-market-data-management`: historical market sync now manages the full active OKX swap universe with per-symbol lifecycle, coverage aggregation, and operator-visible sync status.
- `live-signal-execution`: live dispatch now uses aggregated market coverage gates, supports degraded fresh-symbol execution, and records coverage metadata with each live signal.

## Impact

- Affected code: `apps/api/app/services/market_data_sync.py`, `apps/api/app/services/market_data_store.py`, `apps/api/app/services/live_service.py`, `apps/api/app/runtime/market_sync_loop.py`, `apps/api/app/runtime/market_sync_queue.py`, `apps/api/app/runtime/market_sync_worker.py`, `apps/api/app/models.py`, `apps/api/app/api/routes/health.py`, `apps/api/app/api/routes/market_data.py`, `apps/api/app/schemas.py`, `apps/api/app/main.py`, `apps/api/app/tool_gateway/demo_gateway.py`.
- Dependencies and infra: add Redis client dependency and worker/container wiring in `apps/api/requirements.txt`, `infra/docker/compose/docker-compose.yml`, `infra/env/api.env.example`, and `scripts/dev-*.sh`.
- APIs: extend `/health` and `/market-data/overview`, and add `/market-data/sync-status` plus `/market-data/universe`.
- Operations: live signal freshness is now driven by aggregated coverage snapshots instead of whole-sweep success.
