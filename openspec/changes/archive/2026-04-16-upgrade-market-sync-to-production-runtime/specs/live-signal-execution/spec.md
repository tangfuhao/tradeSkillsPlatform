## MODIFIED Requirements

### Requirement: Live tasks can be triggered by the sync loop or the manual trigger API
The platform SHALL invoke a short-lived Agent execution for each live trigger, SHALL gate execution on the latest aggregated market coverage snapshot, and SHALL not rely on whole-sweep success or in-process wall-clock scheduler jobs for automatic live dispatch.

#### Scenario: Coverage advancement triggers a live run
- **WHEN** market sync processing advances `dispatch_as_of_ms` and a live task has a newer cadence-aligned executable slot than its checkpoint
- **THEN** the platform creates a live run context for that slot, invokes the Agent, stores the resulting signal record, and exits the run

#### Scenario: User manually triggers a live task
- **WHEN** a user calls the live-task trigger endpoint for an active task while market coverage is `healthy` or `degraded` and exposes a pending executable slot
- **THEN** the platform executes one short-lived live run for that same gated slot and returns the stored signal record

#### Scenario: Manual trigger is rejected on stale or blocked coverage
- **WHEN** a user calls the live-task trigger endpoint but the latest coverage snapshot is stale, blocked, or has no pending slot aligned with `dispatch_as_of_ms`
- **THEN** the platform rejects the request with an explicit conflict-style error instead of running on an older snapshot

### Requirement: Live runs store structured signal records
The platform SHALL require each live Agent run to produce a structured stored signal record for later inspection, and those records SHALL include the market coverage metadata used to authorize the run.

#### Scenario: Agent produces a stored signal record
- **WHEN** a live Agent run completes successfully
- **THEN** the platform stores a structured signal payload containing the final decision, reasoning summary, execution context, the slot `execution_time_ms`, the `trigger_origin`, a `delivery_status` of `stored`, and the `dispatch_as_of_ms`, coverage ratio, degraded flag, and missing-symbol summary used for that run

#### Scenario: Live run failure is captured
- **WHEN** a live Agent run fails before producing a normal decision payload
- **THEN** the platform stores a failed signal record with `delivery_status` set to `failed` and includes the error context plus any available coverage metadata for inspection

## ADDED Requirements

### Requirement: Live execution SHALL support degraded market coverage safely
The platform SHALL allow live execution to continue when the aggregated market gate is degraded but still qualified, and SHALL constrain each run to the fresh portion of the market universe.

#### Scenario: Scan-style live execution uses only fresh symbols
- **WHEN** a live task runs while the market coverage gate is marked `degraded`
- **THEN** the platform builds the market scan context only from symbols whose freshness satisfies the current `dispatch_as_of_ms`

#### Scenario: Watchlist task blocks on missing fresh symbols
- **WHEN** a live task declares an explicit watchlist and any watchlist symbol is absent from the fresh coverage set for the current `dispatch_as_of_ms`
- **THEN** the platform rejects that run instead of silently evaluating the task against incomplete market context
