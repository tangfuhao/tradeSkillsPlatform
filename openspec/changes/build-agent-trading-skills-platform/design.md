## Context

`tradeSkills` is a greenfield project. After requirement clarification, the core system is now defined as a Skill-driven Agent runtime for trading workflows.

The important shift is this:
- the user uploads a natural-language Markdown Skill
- the platform extracts a Skill Envelope that describes how to run the Skill
- at runtime, an Agent is invoked with the raw Skill, the Skill Envelope, platform tools, and current context
- the Agent returns a structured decision
- the platform either simulates that decision in backtest mode or notifies the user in live mode

This means the MVP should not be designed as a classic deterministic rule compiler. The first version should instead optimize for a runnable demo on a single public-IP development machine where frontend, backend, scheduler, and Agent components are easy to inspect.

Primary stakeholders:
- the product builder validating the demo end-to-end
- a strategy author uploading Skills as plain text
- an operator reviewing Skills for larger historical windows
- a user consuming backtest results and live signals

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
- Full OKX data ingestion and storage completeness on day one.
- Strong deterministic reproducibility across repeated backtests.
- A generic user-defined code runtime.

## Decisions

### 1. Treat the raw Skill as the source of intent and Skill Envelope as the runtime contract
- Decision: persist the uploaded Markdown Skill as-is and extract a lightweight `Skill Envelope` instead of compiling the entire strategy into a deterministic IR.
- The envelope records only what the platform must know before execution: cadence, modes, tools, output contract, market scope, and hard risk rules.
- Rationale: the user explicitly wants the Agent to think dynamically at most triggers, so over-compiling the strategy at upload time would work against the product intent.

### 2. Invoke the Agent at each trigger using current context
- Decision: in both backtest and live modes, the platform invokes the Agent for each trigger and expects a structured decision response.
- The Agent may use helper scripts or tools to reason about data, but the platform controls the tool surface.
- Rationale: this preserves the "AI reasons every time" requirement while still letting the platform enforce run boundaries and schemas.

### 3. Use Tool Gateway adapters instead of direct data access
- Decision: the Agent interacts only through Tool Gateway interfaces such as `scan_market`, `get_candles`, `get_strategy_state`, `save_strategy_state`, `simulate_order`, and `emit_signal`.
- Rationale: this keeps the prompt stable, prevents future-data leaks in backtests, and makes the runtime replaceable when real adapters are added later.

### 4. Separate backtest replay from live scheduling
- Decision: the platform models every invocation as a `Run`, but uses different trigger sources:
  - `backtest`: replay driver advances historical time and invokes the Agent at each replay step
  - `live_signal`: a platform scheduler triggers short-lived runs based on the Skill cadence
- Rationale: the user wants one Skill and one Agent runtime, with different input clocks and output consumers.

### 5. Keep long-term state in platform storage, not inside the Agent
- Decision: strategy state is stored by the backend and retrieved through tools. The Agent itself is stateless across runs.
- Rationale: this matches the user's requirement and makes short-lived containers viable.

### 6. Use a pragmatic single-machine demo stack
- Decision: implement a monorepo with:
  - `apps/web`: lightweight React/Vite dashboard
  - `apps/api`: FastAPI app with SQLite-backed demo persistence and APScheduler
  - `services/agent-runner`: FastAPI-based Agent Runner boundary with a pluggable decision engine
  - `packages/shared-schemas`: JSON contracts shared across services
  - `packages/shared-skill-examples`: example Markdown Skills
  - `infra/docker/compose`: local compose setup
- Rationale: this keeps local iteration simple while respecting service boundaries.

### 7. Use synthetic/demo execution assumptions first, then swap in real adapters
- Decision: the first implementation can use demo-safe adapters and synthetic replay calculations where real historical or live adapters are not ready yet, as long as the contract boundaries are correct and explicitly labeled.
- Rationale: the repo is empty, and the user asked to start implementation immediately. A working skeleton is more valuable than blocking on full market integration.

### 8. Benchmark is system-defaulted, not user-required
- Decision: the API keeps benchmark selection optional and applies a system default in result summaries.
- Rationale: this matches prior product decisions and reduces UX friction.

## Risks / Trade-offs

- [Agent output is less reproducible than deterministic rule execution] -> keep structured traces, decision schemas, and tool-call summaries.
- [Demo-safe adapters may be mistaken for production-ready trading logic] -> label synthetic/demo assumptions clearly in API responses and UI.
- [Running scheduler inside the API process is fragile at scale] -> acceptable for a single-machine demo and can later be extracted.
- [Skill parsing from text is imperfect] -> fail closed when cadence, AI reasoning, or risk controls cannot be recognized with enough confidence.
- [No built-in Agent memory] -> use platform strategy-state storage and surface it as tools.

## Migration Plan

Because this is a greenfield repo, migration means implementing the agreed target architecture in phases:

1. Align OpenSpec artifacts to the clarified Skill-driven Agent Runtime design.
2. Scaffold the monorepo and shared contracts.
3. Implement the API skeleton for Skills, backtests, live tasks, and signals.
4. Implement the Agent Runner boundary with a demo decision engine and structured response schema.
5. Implement replay and live scheduling skeletons that call the Agent Runner.
6. Add the minimal web dashboard and local compose setup.
7. Replace demo adapters with real OKX history/live adapters incrementally.

## Open Questions

- Which real OKX endpoints and retention windows should be wired first after the demo skeleton is stable?
- Should live notifications default to webhook first or Telegram first?
- When the real LLM provider is attached, which model and cost controls should become the default?
