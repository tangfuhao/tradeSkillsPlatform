## Context

`tradeSkills` is a Skill-driven Agent Runtime demo.

The current implementation follows this path:
- the user uploads a natural-language Markdown Skill
- the platform extracts a Skill Envelope that describes how to run the Skill
- at runtime, an Agent is invoked with the raw Skill, the Skill Envelope, platform tools, and current context
- the Agent returns a structured decision
- the platform either simulates that decision in backtest mode or stores a structured signal record in live mode

This means the MVP should be described as a runnable demo on a single public-IP development machine where frontend, backend, scheduler, and Agent components are easy to inspect.

Primary stakeholders:
- the product builder validating the demo end-to-end
- a strategy author uploading Skills as plain text
- a user inspecting backtest results and live signals
- an operator managing local historical data coverage and service health

## Goals / Non-Goals

**Goals:**
- Support Markdown Skill upload with required AI reasoning steps and explicit risk-control sections.
- Extract a Skill Envelope that captures cadence, supported modes, required tools, output schema, and hard risk bounds.
- Run the same Skill in two modes: `backtest` and `live_signal`.
- Keep Agent state outside the Agent process and accessible through platform tools.
- Launch short-lived Agent executions from a platform scheduler instead of relying on cron inside containers.
- Produce a minimal but runnable monorepo with web, API, Agent Runner, shared contracts, and local startup instructions.

**Non-Goals:**
- Real money execution in the MVP.
- High-concurrency scheduling or multi-tenant isolation.
- Export-bundle management and approval workflows.
- Full OKX data ingestion and storage completeness on day one.
- Strong deterministic reproducibility across repeated backtests.
- A generic user-defined code runtime.

## Decisions

### 1. Treat the raw Skill as the source of intent and Skill Envelope as the runtime contract
- Decision: persist the uploaded Markdown Skill as-is and extract a lightweight `Skill Envelope` instead of compiling the entire strategy into a deterministic IR.
- The envelope records only what the platform must know before execution: cadence, modes, tools, output contract, market scope, and hard risk rules.
- Rationale: the current product intent is to let the Agent think dynamically at each trigger, while the platform still controls boundaries and schemas.

### 2. Invoke the Agent at each trigger using current context
- Decision: in both backtest and live modes, the platform invokes the Agent for each trigger and expects a structured decision response.
- The Agent may use helper scripts or tools to reason about data, but the platform controls the tool surface.
- Rationale: this preserves the “AI reasons every time” requirement while still letting the platform enforce run boundaries and output structure.

### 3. Use Tool Gateway adapters instead of direct data access
- Decision: the Agent interacts only through Tool Gateway interfaces such as `scan_market`, `get_market_metadata`, `get_candles`, `get_strategy_state`, `save_strategy_state`, `get_portfolio_state`, `simulate_order`, and `emit_signal`.
- Rationale: this keeps the runtime surface stable, prevents future-data leaks in backtests, and makes the execution boundary replaceable later.

### 4. Separate backtest replay from live scheduling
- Decision: the platform models both modes as short-lived execution cycles, but uses different trigger sources:
  - `backtest`: the API creates a run record and executes replay in a FastAPI background task
  - `live_signal`: APScheduler triggers short-lived runs based on the Skill cadence
- Rationale: the user wants one Skill and one Agent runtime, with different clocks and different output consumers.

### 5. Keep long-term state in platform storage, not inside the Agent
- Decision: execution state is stored by the backend and retrieved through tools. The Agent itself is stateless across runs.
- Rationale: this matches the current requirement and makes short-lived execution boundaries viable.

### 6. Use a pragmatic single-machine demo stack
- Decision: implement a monorepo with:
  - `apps/web`: lightweight React/Vite dashboard
  - `apps/api`: FastAPI app with SQLite-backed demo persistence and APScheduler
  - `services/agent-runner`: FastAPI-based Agent Runner boundary with an OpenAI Responses API tool runtime
  - `packages/shared-schemas`: JSON contracts shared across services
  - `packages/shared-skill-examples`: example Markdown Skills
  - `infra/docker/compose`: local compose setup
- Rationale: this keeps local iteration simple while respecting service boundaries.

### 7. Use demo-safe execution assumptions first, then swap in real adapters
- Decision: the implementation may use demo-safe market enrichments and simplified execution assumptions where real adapters are not ready, as long as the contract boundaries are correct and clearly labeled.
- Rationale: a working skeleton is more valuable than blocking on full market integration.

### 8. Benchmark remains system-defaulted
- Decision: the API keeps benchmark selection optional and applies a system default in result summaries.
- Rationale: this matches the current simplified UX and reduces friction.

## Risks / Trade-offs

- [Agent output is less reproducible than deterministic rule execution] -> keep structured traces, decision schemas, tool-call summaries, and explicit summary assumptions.
- [Demo-safe adapters may be mistaken for production-ready trading logic] -> label assumptions clearly in API responses and documentation.
- [Running scheduler inside the API process is fragile at scale] -> acceptable for a single-machine demo and can later be extracted.
- [Skill parsing from text is imperfect] -> fail closed when cadence, AI reasoning, or risk controls cannot be recognized.
- [No built-in Agent memory] -> use execution-scoped platform state and surface it as tools.

## Migration Plan

Because this is still a demo-oriented repository, migration means evolving the current architecture in place:

1. Keep the current Skill-driven Agent Runtime architecture aligned with the running code.
2. Keep the monorepo scaffold and shared contracts stable.
3. Improve the API surface for Skills, backtests, live tasks, and signals without reintroducing obsolete approval resources.
4. Strengthen the Agent Runner boundary and tool loop.
5. Improve replay and live scheduling robustness.
6. Improve dashboard observability.
7. Replace demo adapters with real market integrations incrementally.

## Open Questions

- Which real OKX endpoints and retention windows should be wired first after the demo skeleton is stable?
- Should live signals remain storage-only, or should notification delivery become a first-class runtime concern?
- Which runner model routing and cost-control defaults should become the long-term baseline?
