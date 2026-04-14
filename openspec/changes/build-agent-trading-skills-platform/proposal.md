## Why

The current repository has already converged on a Skill-driven Agent Runtime demo.

Users submit a natural-language trading Skill in Markdown. The platform extracts a lightweight runtime contract from that text, launches an Agent with platform tools, and supports two execution modes:
- historical replay backtests that simulate portfolio behavior over historical trigger times
- live periodic signal generation that stores structured signal records for later inspection

The immediate goal remains a single-machine demo that runs frontend, backend, and Agent services on one public-IP development machine for easy testing and debugging. The system only needs to prove the end-to-end loop, not multi-tenant scale.

## What Changes

- Keep the Skill-driven Agent Runtime architecture centered on raw Skill text, Skill Envelope extraction, Tool Gateway access, and structured Agent decisions.
- Keep the monorepo scaffold for `web`, `api`, and `agent-runner` services plus shared schemas, demo skill examples, and local Docker-based development.
- Keep Skill ingestion APIs that store the raw Markdown Skill, validate required sections, extract a Skill Envelope, and make the Skill available for immediate execution when validation succeeds.
- Keep a backtest workflow that replays historical trigger times, invokes the Agent on each trigger, records traces, simulates paper-trading outcomes through the current portfolio engine, and returns a result summary.
- Keep a live-signal workflow that activates a periodic task from the Skill cadence, launches short-lived Agent executions, and stores structured signal records.
- Keep a Tool Gateway boundary so Agents consume stable business tools instead of directly querying databases or third-party APIs.

## Capabilities

### New Capabilities
- `strategy-skill-management`: Users can upload natural-language trading Skills, validate them, extract runtime metadata, and run validated Skills in the current demo runtime.
- `historical-market-data-management`: The platform can manage locally stored historical OKX-style market data for replay-safe backtests and expose time-bounded reads to Agent tools.
- `backtest-simulation`: The platform can create replay-based backtest runs that trigger the Agent according to the Skill cadence and simulate portfolio behavior from the Agent's structured decisions.
- `backtest-results-reporting`: The platform can store and return core backtest metrics, execution assumptions, trace samples, and decision history.
- `live-signal-execution`: The platform can activate periodic live signal tasks, trigger short-lived Agent runs, and store structured signal records.

### Modified Capabilities
- None.

## Impact

- Application code lives in `apps/web`, `apps/api`, `services/agent-runner`, and shared schema/example packages.
- The backend contract is based on runtime envelope extraction and Agent tool execution, not deterministic IR-first compilation.
- The demo relies on local persistence, local scheduler state, and container-friendly service boundaries instead of distributed production infrastructure.
- The architecture leaves room for later replacement of demo adapters with real OKX historical storage, live market adapters, and richer notification delivery.
