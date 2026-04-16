## MODIFIED Requirements

### Requirement: Live tasks can be triggered by the sync loop or the manual trigger API
The platform SHALL invoke a short-lived Agent execution for each live trigger, SHALL gate execution on the latest aggregated market coverage snapshot, and SHALL coordinate executable-slot claims through PostgreSQL-backed leases and idempotency constraints so only one committed live run exists per task and cadence slot across all API and worker processes.

#### Scenario: Coverage advancement triggers a live run
- **WHEN** market sync processing advances `dispatch_as_of_ms` and a live task has a newer cadence-aligned executable slot than its checkpoint
- **THEN** the platform records a PostgreSQL-backed claim for that slot, invokes the Agent exactly once for the winning claim, stores the resulting signal record, and exits the run

#### Scenario: User manually triggers a live task
- **WHEN** a user calls the live-task trigger endpoint for an active task while market coverage is `healthy` or `degraded` and exposes a pending executable slot
- **THEN** the platform executes one short-lived live run for that same gated slot and returns the stored signal record or the already-claimed result for that slot instead of creating a duplicate run

#### Scenario: Manual trigger is rejected on stale or blocked coverage
- **WHEN** a user calls the live-task trigger endpoint but the latest coverage snapshot is stale, blocked, or has no pending slot aligned with `dispatch_as_of_ms`
- **THEN** the platform rejects the request with an explicit conflict-style error instead of running on an older snapshot

## ADDED Requirements

### Requirement: Live slot claims are durable and recoverable
The platform SHALL persist live slot claim ownership, heartbeat, and terminal outcome in PostgreSQL so abandoned work can be reclaimed safely without duplicate committed side effects.

#### Scenario: Worker crashes after claiming a live slot
- **WHEN** a worker claims a live slot and fails before completing the run
- **THEN** the platform leaves a durable timed claim record that another worker can reclaim after lease expiry while still preventing more than one committed signal for that slot
