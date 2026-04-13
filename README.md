# TradeSkills

TradeSkills is a single-machine demo platform for natural-language trading Skills.

Users upload a Markdown Skill, the platform extracts a Skill Envelope, and the same Skill can run in two modes:
- `backtest`: replay historical trigger times and simulate paper-trading behavior
- `live_signal`: trigger periodic Agent runs and store structured trade signals

This repository is intentionally organized as a monorepo so the web app, API, and Agent Runner stay easy to debug on one public-IP development machine.

## Monorepo layout

```text
tradeSkills/
|- apps/
|  |- api/                FastAPI app, SQLite demo persistence, startup sync, scheduler
|  \- web/                Vite + React demo dashboard
|- services/
|  \- agent-runner/       Agent execution boundary with pluggable decision engine
|- packages/
|  |- shared-schemas/     Shared JSON contracts for envelopes and decisions
|  \- shared-skill-examples/
|- infra/
|  |- docker/compose/     Local compose setup
|  \- env/                Example environment files
|- data/
|  \- runtime/            Local runtime storage
\- openspec/              Product/spec artifacts
```

## What works now

- Skill upload, validation, envelope extraction, review-state update, and list/detail APIs
- Backtest creation, replay execution, summary/traces retrieval, and live signal task activation
- Blocking startup sync for historical market data:
  1. import local OKX CSV seed files into SQLite
  2. try small incremental API catch-up for active OKX `USDT-SWAP` symbols
- Historical candle query APIs with dynamic aggregation from stored `1m` bars into `15m`, `4h`, or other intervals
- React demo dashboard with service pulse, market coverage, skill review controls, backtest launch, and recent signals
- Agent Runner service boundary with a real OpenAI-compatible LLM tool runtime plus a heuristic fallback for rate-limit or provider failures
- Internal Tool Gateway HTTP path so the runner fetches market/state data on demand instead of relying on preloaded candle blobs

## Historical data behavior

The current demo is opinionated around the requirements already clarified in product discussion:

- Store only `*-USDT-SWAP`
- Keep `#OLD#` / delisted contracts in historical storage for backtest realism
- Store base candles as `1m` and derive larger timeframes dynamically at query time
- Run startup sync in blocking mode so the API is only considered ready after market data sync completes
- Protect startup from OKX API rate limits with `TRADE_SKILLS_OKX_INCREMENTAL_MAX_GAP_DAYS`
  - if the gap from local coverage to the target cutoff is too large, the symbol is marked `skipped`
  - large backfills should be handled by pre-downloaded CSV seed files, not by startup API pagination

### Seed-first workflow

Recommended local workflow:

1. Download OKX historical candle CSV files into the sibling `../data` directory.
2. Start the API.
3. On startup, the API imports unseen CSVs into SQLite.
4. After CSV import, the API attempts incremental catch-up only for small missing windows.
5. The dashboard and `/api/v1/market-data/overview` show what was imported and what was skipped.

This is designed for a debug-heavy development machine where services restart often.

## Review-state workflow

A Skill has two practical backtest scopes in the demo:

- `preview_ready`: can run only inside the default recent preview window
- `approved_full_window`: can run larger historical windows after manual approval

The web dashboard now exposes both review controls so you can quickly test:

- upload Skill -> preview-ready immediately
- approve Skill -> unlock older seeded history for replay

If your local CSV coverage is old data only, a preview-ready Skill may correctly fail for out-of-window backtests until you approve it.

## Quick start

1. Create a Python virtual environment at the repo root.
2. Install the API dependencies.
3. Install the Agent Runner dependencies.
4. Install the web dependencies.
5. Start the three services in separate terminals.

```bash
python3 -m venv .venv
source .venv/bin/activate

make api-install
make runner-install
make web-install

make runner-dev
make api-dev
make web-dev
```

Default local endpoints:
- Web: `http://localhost:5173`
- API: `http://localhost:8000`
- Agent Runner: `http://localhost:8100`

## Important API endpoints

- `GET /api/v1/health`
- `GET /api/v1/market-data/overview`
- `GET /api/v1/market-data/symbols`
- `GET /api/v1/market-data/candles?market_symbol=BTC-USDT-SWAP&timeframe=15m&limit=100`
- `POST /api/v1/skills`
- `POST /api/v1/skills/{skill_id}/review-state`
- `POST /api/v1/backtests`
- `GET /api/v1/backtests/{run_id}/traces`
- `POST /api/v1/live-tasks`
- `POST /api/v1/live-tasks/{task_id}/trigger`

## Agent runtime notes

- The Agent Runner now reads raw Skill Markdown, lets the LLM call local tools, and returns a structured decision payload.
- Backtest and live mode share the same tool-driven runtime; only the trigger clock and downstream consumer differ.
- The runner now calls the API's internal Tool Gateway over HTTP for `scan_market`, `get_candles`, `get_strategy_state`, `save_strategy_state`, `get_funding_rate`, and `get_open_interest`.
- This removes the earlier preloaded `tool_context` dependency and makes the runner architecture closer to a real remote Agent runtime.
- The Tool Gateway is now capability-layered into `market/*`, `state/*`, and `signal/*` internal handlers, while `/execute` remains as a compatibility dispatcher.
- The current OpenAI-compatible provider used in local testing requires `stream=true` for `/v1/chat/completions`, so the runner uses a streamed tool loop internally.
- If the LLM provider returns `429` or transient `5xx` errors, the runner retries with backoff and then falls back to the local heuristic engine so the platform still completes the run.
- If your API runs on a non-default host or port, set `TRADE_SKILLS_TOOL_GATEWAY_BASE_URL` so the runner callback URL points at the API process correctly.
- Because your dev machine has a public IP, set `TRADE_SKILLS_TOOL_GATEWAY_SHARED_SECRET` to protect `/api/v1/internal/tool-gateway/execute`.
- The web dashboard reads both API and runner health directly from the browser, so if you access the dashboard from another device you should set both `TRADE_SKILLS_ALLOWED_ORIGINS` and `AGENT_RUNNER_ALLOWED_ORIGINS` to include that web origin.

## Example environment variables

See `infra/env/api.env.example`, especially:

- `TRADE_SKILLS_HISTORICAL_DATA_DIR`
- `TRADE_SKILLS_HISTORICAL_CSV_GLOB`
- `TRADE_SKILLS_HISTORICAL_BASE_TIMEFRAME`
- `TRADE_SKILLS_STARTUP_SYNC_BLOCKING`
- `TRADE_SKILLS_OKX_INCREMENTAL_MAX_GAP_DAYS`
- `TRADE_SKILLS_STARTUP_SYNC_TARGET_OFFSET_DAYS`
- `TRADE_SKILLS_TOOL_GATEWAY_BASE_URL`
- `TRADE_SKILLS_TOOL_GATEWAY_SHARED_SECRET`

See `infra/env/agent-runner.env.example`, especially:

- `AGENT_RUNNER_ALLOWED_ORIGINS`
- `AGENT_RUNNER_OPENAI_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`

## Useful commands

```bash
make smoke-python
make smoke-web-json
```

## Notes for the next iteration

1. Replace the current demo market enrichments with real OKX funding-rate and open-interest adapters.
2. Add a proper migration layer instead of relying on `create_all` for schema evolution.
3. Expose sync status and replay traces in richer operator views.
4. Add stronger provider-side rate controls or queueing for larger backtests.
