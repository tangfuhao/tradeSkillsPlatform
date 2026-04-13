## 1. Specification alignment and repo foundation

- [x] 1.1 Align the OpenSpec change artifacts with the clarified Skill-driven Agent Runtime architecture
- [x] 1.2 Scaffold the monorepo for `apps/web`, `apps/api`, `services/agent-runner`, shared packages, and local infrastructure
- [x] 1.3 Add root developer ergonomics: `README`, `Makefile`, `.gitignore`, env examples, and local Docker Compose

## 2. Shared contracts and demo assets

- [x] 2.1 Define shared JSON contracts for Skill Envelope and Agent decision payloads
- [x] 2.2 Add demo Skill examples that match the required Markdown Skill format

## 3. API service

- [x] 3.1 Implement the FastAPI app skeleton with configuration, persistence, and health endpoints
- [x] 3.2 Implement Skill upload, validation, envelope extraction, list, and detail APIs
- [x] 3.3 Implement backtest run creation, status, summary, and trace retrieval APIs
- [x] 3.4 Implement live task creation, list, and recent signal retrieval APIs

## 4. Agent runtime and scheduling skeleton

- [x] 4.1 Implement the Agent Runner service boundary and structured run execution endpoint
- [x] 4.2 Add a pluggable demo decision engine that can be replaced by a real LLM-backed engine later
- [x] 4.3 Implement a replay driver skeleton that triggers backtest runs from the extracted cadence
- [x] 4.4 Implement a live scheduler skeleton that triggers short-lived live runs from the extracted cadence

## 5. Demo UX and local verification

- [x] 5.1 Implement a minimal web dashboard for health, Skill upload, backtest triggering, live task activation, and recent results
- [x] 5.2 Wire cross-service local development and Docker startup configuration
- [x] 5.3 Run basic self-checks for the monorepo skeleton and record any remaining gaps
