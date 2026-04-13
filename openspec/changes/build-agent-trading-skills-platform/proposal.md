## Why

The product direction was clarified after the initial proposal: this project is not primarily a traditional deterministic backtesting platform. It is a Skill-driven Agent runtime for trading ideas.

Users submit a natural-language trading Skill in Markdown. The platform extracts a lightweight runtime contract from that text, launches an Agent with platform tools, and supports two execution modes:
- historical replay backtests that simulate time and paper execution
- live periodic signal generation that notifies the user when the Agent finds an opportunity

The immediate goal is a single-machine demo that runs frontend, backend, and Agent services on one public-IP development machine for easy testing and debugging. The system only needs to prove the end-to-end loop, not multi-tenant scale.

## What Changes

- Replace the earlier IR-first implementation direction with a Skill-driven Agent Runtime architecture centered on raw Skill text, Skill Envelope extraction, Tool Gateway access, and structured Agent decisions.
- Add a monorepo scaffold for `web`, `api`, and `agent-runner` services plus shared schemas, demo skill examples, and local Docker-based development.
- Add Skill ingestion APIs that store the raw Markdown Skill, validate required sections, extract a Skill Envelope, and place the Skill into preview-ready or review-required states.
- Add a backtest workflow that replays historical trigger times, invokes the Agent on each trigger, records traces, simulates paper-trading outcomes, and returns a result summary.
- Add a live-signal workflow that activates a periodic task from the Skill cadence, launches short-lived Agent executions, stores structured signals, and emits user notifications.
- Add a Tool Gateway boundary so Agents consume stable business tools instead of directly querying databases or third-party APIs.

## Capabilities

### New Capabilities
- `strategy-skill-management`: Users can upload natural-language trading Skills, validate them, extract runtime metadata, and manage preview-vs-approved execution eligibility.
- `historical-market-data-management`: The platform can manage locally stored historical OKX-style market data for replay-safe backtests and expose time-bounded reads to Agent tools.
- `backtest-simulation`: The platform can create replay-based backtest runs that trigger the Agent according to the Skill cadence and simulate portfolio behavior from the Agent's structured decisions.
- `backtest-results-reporting`: The platform can store and return core backtest metrics, trace samples, decision history, and exportable run artifacts.
- `live-signal-execution`: The platform can activate periodic live signal tasks, trigger short-lived Agent runs, store structured signals, and notify the user.

### Modified Capabilities
- None.

## Impact

- New application code will be introduced for `apps/web`, `apps/api`, `services/agent-runner`, and shared schema/example packages.
- The backend contract shifts from "compile everything into a deterministic IR" to "extract a runtime envelope and invoke an Agent with tools at execution time".
- The demo will rely on local persistence, local scheduler state, and container-friendly service boundaries instead of distributed production infrastructure.
- The architecture leaves room for later replacement of demo adapters with real OKX historical storage, live market adapters, and LLM-backed decision engines.
