# TradeSkills

TradeSkills is a single-machine demo platform for natural-language trading Skills.

Users upload a Markdown Skill, the platform extracts a Skill Envelope, and the same Skill can run in two modes:
- `backtest`: replay historical trigger times and simulate paper-trading behavior with the current portfolio engine
- `live_signal`: trigger periodic Agent runs and store structured signal records for later inspection

This repository is intentionally organized as a monorepo so the web app, API, and Agent Runner stay easy to debug on one public-IP development machine.

## Monorepo layout

```text
tradeSkills/
|- apps/
|  |- api/                FastAPI app, SQLite demo persistence, startup sync, scheduler
|  \- web/                Vite + React demo dashboard
|- services/
|  \- agent-runner/       Agent execution boundary with OpenAI Responses tool runtime
|- packages/
|  |- shared-schemas/     Shared JSON contracts for envelopes and decisions
|  \- shared-skill-examples/
|- infra/
|  |- docker/compose/     Local compose setup
|  \- env/                Example environment files
|- data/
|  \- runtime/            Local runtime storage
\- openspec/              Product/spec artifacts and historical design notes
```

## Current implementation scope

The current codebase is centered on a simple demo workflow:

1. Upload a Markdown Skill.
2. Run rule-first validation and Skill Envelope extraction, then fall back to an LLM-assisted patch only when deterministic extraction is incomplete.
3. Run the Skill in `backtest` or `live_signal` mode.
4. Persist traces, simulated portfolio state, and live signal records.
5. Inspect results in the React dashboard.

What works now:

- Skill upload, rule-first validation, hybrid envelope extraction, and list/detail APIs
- Backtest creation, replay execution, summary retrieval, trace retrieval, and backtest portfolio inspection
- Live task creation, periodic scheduling, manual triggering, recent signal retrieval, and live-task portfolio inspection
- Blocking startup sync for operator-managed historical market data:
  1. import local OKX CSV seed files into SQLite
  2. optionally try small incremental API catch-up for active OKX `USDT-SWAP` symbols
- Historical candle query APIs with dynamic aggregation from stored `1m` bars into `15m`, `4h`, or other intervals
- React demo dashboard with service pulse, market coverage, skill upload, backtest launch, live task activation, and recent signals
- Agent Runner service boundary with an OpenAI Responses API tool loop plus structured decision sanitization
- Internal Tool Gateway HTTP path so the runner fetches market, state, and portfolio data on demand instead of relying on preloaded candle blobs

What is intentionally not part of the current implementation:

- The old `preview -> review -> approved_full_window` workflow
- Public review-state APIs or dashboard review controls
- An active `strategy` / `strategy_version` / `review_request` public resource model
- Export bundles for backtest artifacts
- Real notification delivery channels such as Telegram or webhook dispatch
- IR-first strategy compilation as the runtime execution path

## Current public API surface

The current public API is defined by the FastAPI routes under `apps/api/app/api/routes/`.

Public endpoints:

- `GET /api/v1/health`
- `GET /api/v1/market-data/overview`
- `GET /api/v1/market-data/symbols`
- `GET /api/v1/market-data/candles?market_symbol=BTC-USDT-SWAP&timeframe=15m&limit=100`
- `GET /api/v1/skills`
- `POST /api/v1/skills`
- `GET /api/v1/skills/{skill_id}`
- `GET /api/v1/backtests`
- `POST /api/v1/backtests`
- `GET /api/v1/backtests/{run_id}`
- `GET /api/v1/backtests/{run_id}/summary`
- `GET /api/v1/backtests/{run_id}/traces`
- `GET /api/v1/backtests/{run_id}/portfolio`
- `GET /api/v1/live-tasks`
- `POST /api/v1/live-tasks`
- `POST /api/v1/live-tasks/{task_id}/trigger`
- `GET /api/v1/live-tasks/{task_id}/portfolio`
- `GET /api/v1/live-signals`

Internal-only endpoints exist under `/api/v1/internal/tool-gateway/*` for the Agent Runner and should not be treated as public API.

## Current data model

The demo persists its runtime state in SQLite. The core tables represented in `apps/api/app/models.py` are:

- `skills`
- `backtest_runs`
- `run_traces`
- `live_tasks`
- `live_signals`
- `strategy_states`
- `execution_strategy_states`
- `portfolio_books`
- `portfolio_positions`
- `portfolio_fills`
- `trace_execution_details`
- `market_candles`
- `csv_ingestion_jobs`
- `market_sync_cursors`

Notable implementation details:

- The active runtime state path is execution-scoped: `PortfolioEngine` reads and writes `execution_strategy_states` for each `backtest_run` or `live_task`
- `skills.review_status` and the `strategy_states` table still exist in the schema as legacy artifacts, but the current public workflow does not use them as review gates
- Backtest summaries are stored inline on `backtest_runs.summary_json`
- Live outputs are stored as signal records on `live_signals.signal_json`, with `delivery_status` currently used only to distinguish stored vs failed runs
- There is no separate review-request, export-bundle, or dataset-version table in the current demo

## Historical data behavior

The current demo is opinionated around the requirements already clarified in product discussion:

- Store only `*-USDT-SWAP`
- Keep `#OLD#` / delisted contracts in historical storage for backtest realism
- Store base candles as `1m` and derive larger timeframes dynamically at query time
- Run startup sync in blocking mode so the API is only considered ready after market data sync completes
- Protect startup from OKX API rate limits with `TRADE_SKILLS_OKX_INCREMENTAL_MAX_GAP_DAYS`
  - if the gap from local coverage to the target cutoff is too large, the symbol is marked `skipped`
  - large backfills should be handled by pre-downloaded CSV seed files, not by startup API pagination
- For UI-first local debugging, you can set `TRADE_SKILLS_OKX_INCREMENTAL_SYNC_ENABLED=false` so startup still imports local CSVs but skips all OKX API catch-up

### Seed-first workflow

Recommended local workflow:

1. Download OKX historical candle CSV files into the sibling `../data` directory.
2. Start the API.
3. On startup, the API imports unseen CSVs into SQLite.
4. After CSV import, the API optionally attempts incremental catch-up only for small missing windows.
5. The dashboard and `/api/v1/market-data/overview` show what was imported and what was skipped.

This is designed for a debug-heavy development machine where services restart often.

## Current execution semantics

### Skill validation and envelope extraction

A valid Skill currently needs:

- a title (rule extraction may fall back to the Runner when the title is only implicit in natural language)
- an identifiable execution cadence such as `Every 15 minutes` or `每 15 分钟`
- an identifiable AI reasoning section
- explicit risk-control guidance plus explicit numeric hard limits for position size, daily drawdown, and concurrent positions

The current upload flow is synchronous and hybrid:

- first run deterministic rule extraction
- if the rule result is incomplete, call the Agent Runner once for a JSON-only conservative patch
- merge with rule-first precedence, apply platform defaults, and run shared-schema plus platform validation

If extraction succeeds, the API stores the raw Markdown, the extracted Skill Envelope, and minimal extraction metadata. If extraction still fails, upload is rejected with validation errors.

### Backtest window rules

Current backtest creation rules are code-driven and intentionally simple:

- the requested window must satisfy `end_time > start_time`
- the requested window must fit entirely inside local historical data coverage
- the window must span at least one full cadence interval
- there is no preview-only or approval-gated time window in the current implementation

### Portfolio simulation

The current backtest and live runtime share the same `PortfolioEngine` model:

- decisions can `open_position`, `close_position`, `reduce_position`, `skip`, `watch`, or `hold`
- fills and positions are persisted per execution scope
- unrealized PnL is computed by mark-to-market against historical close prices available at the current `as_of` time
- summary metrics are derived from the simulated portfolio state and closed-trade statistics

## Agent runtime notes

- The Agent Runner reads raw Skill Markdown, lets the model call runtime tools, and returns a structured decision payload.
- Backtest and live mode share the same tool-driven runtime; only the trigger clock and downstream consumer differ.
- The runner calls the API's internal Tool Gateway over HTTP for market, state, portfolio, and signal-staging operations.
- The current toolset includes `scan_market`, `get_market_metadata`, `get_candles`, `compute_indicators`, `get_funding_rate`, `get_open_interest`, `get_strategy_state`, `save_strategy_state`, `get_portfolio_state`, `simulate_order`, `emit_signal`, and `python_exec`.
- For a detailed runtime tool catalog, execution notes, and Chinese case-by-case walkthroughs, see [the agent tools guide](docs/agent-tools.zh-CN.md).
- The runner currently uses the OpenAI Responses API tool loop, not the older chat-completions flow.
- If the model returns a non-JSON final answer after tool use, the runtime fails closed to a `skip` decision instead of applying an unstructured action.
- If your API runs on a non-default host or port, set `TRADE_SKILLS_TOOL_GATEWAY_BASE_URL` so the runner callback URL points at the API process correctly.
- Because your dev machine has a public IP, set `TRADE_SKILLS_TOOL_GATEWAY_SHARED_SECRET` to protect `/api/v1/internal/tool-gateway/*`.
- The web dashboard reads both API and runner health directly from the browser, so if you access the dashboard from another device you should set both `TRADE_SKILLS_ALLOWED_ORIGINS` and `AGENT_RUNNER_ALLOWED_ORIGINS` to include that web origin.

## Quick start

Bootstrap the local virtual environment plus Python/web dependencies once:

```bash
make bootstrap
```

Then start the three services in separate terminals if you want foreground logs:

```bash
make runner-dev
make api-dev
make web-dev
```

Default local endpoints:
- Web: `http://localhost:5173`
- API: `http://localhost:8000`
- Agent Runner: `http://localhost:8100`

### One-command local startup

If you prefer a single command for local debugging:

```bash
make dev-up
```

This will:

- create `.venv` automatically when missing
- install or refresh Python dependencies when either requirements file changes
- install or refresh web dependencies when `package.json` or `package-lock.json` changes
- read `apps/api/.env`, `services/agent-runner/.env`, and `apps/web/.env.local`
- start all three services in the background
- write PID files under `.dev/pids`
- write logs under `.dev/logs`

Useful companion commands:

```bash
make dev-status
make dev-down
```

## Example environment variables

See `infra/env/api.env.example`, especially:

- `TRADE_SKILLS_HISTORICAL_DATA_DIR`
- `TRADE_SKILLS_HISTORICAL_CSV_GLOB`
- `TRADE_SKILLS_HISTORICAL_BASE_TIMEFRAME`
- `TRADE_SKILLS_STARTUP_SYNC_BLOCKING`
- `TRADE_SKILLS_OKX_INCREMENTAL_MAX_GAP_DAYS`
- `TRADE_SKILLS_OKX_INCREMENTAL_SYNC_ENABLED`
- `TRADE_SKILLS_STARTUP_SYNC_TARGET_OFFSET_DAYS`
- `TRADE_SKILLS_TOOL_GATEWAY_BASE_URL`
- `TRADE_SKILLS_TOOL_GATEWAY_SHARED_SECRET`

See `infra/env/agent-runner.env.example`, especially:

- `AGENT_RUNNER_ALLOWED_ORIGINS`
- `AGENT_RUNNER_OPENAI_API_KEY`
- `AGENT_RUNNER_OPENAI_BASE_URL`
- `AGENT_RUNNER_OPENAI_MODEL`
- `AGENT_RUNNER_OPENAI_WIRE_API`
- `AGENT_RUNNER_OPENAI_REASONING_EFFORT`
- `AGENT_RUNNER_EXECUTE_REASONING_EFFORT` (leave blank to omit reasoning for run execution while keeping envelope extraction unchanged)

## Useful commands

```bash
make smoke-python
make smoke-web-json
```

## Document status

- `README.md` and `docs/historical-backtest-flow.md` describe the current implementation.
- Several files under `openspec/changes/build-agent-trading-skills-platform/` are preserved as historical design material. If those documents disagree with the running code, treat the code as authoritative.

## Notes for the next iteration

1. Replace the current demo market enrichments with real OKX funding-rate and open-interest adapters.
2. Add a proper migration layer instead of relying on `create_all` for schema evolution.
3. Expose sync status and replay traces in richer operator views.
4. Add stronger provider-side rate controls or queueing for larger backtests.
5. Decide whether live signals should remain storage-only or grow a real notification delivery path.
