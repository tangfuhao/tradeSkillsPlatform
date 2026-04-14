# Future Support TODO - Funding Rate and Open Interest Tools

## Purpose

This document captures the current conclusions for future development of the
`get_funding_rate` and `get_open_interest` tools.

Today these tools are demo-level only:

- `get_funding_rate` returns funding data from the market snapshot placeholder.
- `get_open_interest` returns open-interest data from the same snapshot placeholder.
- The current market snapshot builder fills both fields with `0.0`, so they do
  not yet represent real market structure data.

This TODO is intended to guide the future implementation needed to make these
tools production-like and backtest-safe.

## What These Tools Are Supposed to Mean

### `get_funding_rate`

Goal:

- Return the funding-rate information for a perpetual contract at a given time.
- Help the Agent reason about directional crowding and long/short imbalance.

Why it matters:

- Positive funding usually means longs are crowded.
- Negative funding usually means shorts are crowded.
- Funding is not price action; it is a market-structure signal.

### `get_open_interest`

Goal:

- Return open-interest information for a contract at a given time.
- Help the Agent reason about whether new leveraged positions are entering or
  leaving the market.

Why it matters:

- Rising OI often means new positions are being added.
- Falling OI often means positions are being closed.
- OI helps distinguish trend continuation, short covering, and de-leveraging.

## Intended Design Role in the Agent System

These tools are meant to complement:

- `scan_market` for broad candidate discovery
- `get_candles` for price action
- `compute_indicators` for technical context

Expected usage:

- `scan_market` returns a broad candidate list and, when possible, includes
  funding/OI summary fields.
- `get_funding_rate` and `get_open_interest` are then used for single-symbol
  drill-down before final decision making.

## Problems in the Current Demo Implementation

- Funding and OI are not backed by dedicated market data storage.
- The Tool Gateway handlers read these values from the market snapshot instead
  of querying a real historical/live market structure source.
- The snapshot builder currently hardcodes:
  - `funding_rate = 0.0`
  - `open_interest_change_24h_pct = 0.0`
- This means the Agent sees structurally valid fields but not meaningful data.

## Target Implementation Principles

### 1. Keep one tool interface, but separate live and backtest adapters

The Agent-facing interface should stay stable:

- `get_funding_rate(symbol, as_of)`
- `get_open_interest(symbol, as_of)`

But the backing implementation should differ by mode:

- `backtest`: read only historical snapshots at or before `as_of`
- `live_signal`: read real provider data or the latest synced market structure

### 2. Enforce strict time safety in backtests

Backtest mode must never leak future information.

Rules:

- `get_funding_rate(as_of=T)` must only return funding data known at or before
  `T`
- `get_open_interest(as_of=T)` must only return OI snapshots known at or before
  `T`
- Any derived changes such as `1h`, `4h`, or `24h` OI change must be computed
  only from history available at or before `T`

### 3. Store market-structure data separately from candles

Do not keep funding/OI as ad-hoc fields on the candle-based market snapshot.

Add dedicated storage models for:

- `market_funding_rates`
- `market_open_interest_snapshots`

Suggested fields for `market_funding_rates`:

- `exchange`
- `market_symbol`
- `funding_time_ms`
- `funding_rate`
- `next_funding_time_ms`
- `source`
- `created_at`

Suggested fields for `market_open_interest_snapshots`:

- `exchange`
- `market_symbol`
- `snapshot_time_ms`
- `open_interest_contracts`
- `open_interest_notional_usd`
- `source`
- `created_at`

Derived fields such as OI change rates should preferably be computed at query
time instead of being permanently duplicated in storage.

### 4. Introduce dedicated query services/stores

Add services similar to the candle store:

- `FundingRateStore`
- `OpenInterestStore`

Recommended methods:

- `get_latest_at_or_before(symbol, as_of)`
- `get_window(symbol, end_time, limit)` for funding
- `get_change(symbol, as_of, lookback)` for OI deltas

The Tool Gateway handlers should query these stores directly instead of reading
placeholder fields from the market snapshot.

### 5. Upgrade `scan_market` to join in real market-structure data

Once funding and OI storage exists:

- build the candidate universe from candles and liquidity data
- enrich each candidate with the latest funding snapshot
- enrich each candidate with OI and OI change metrics

This keeps `scan_market` useful for coarse filtering while the dedicated tools
remain useful for detailed per-symbol analysis.

## Recommended Response Shapes

### `get_funding_rate`

Suggested response:

```json
{
  "market_symbol": "DOGE-USDT-SWAP",
  "as_of_ms": 1713009600000,
  "funding_rate": 0.0012,
  "funding_time_ms": 1713009600000,
  "next_funding_time_ms": 1713038400000,
  "source": "okx",
  "staleness_ms": 0
}
```

### `get_open_interest`

Suggested response:

```json
{
  "market_symbol": "DOGE-USDT-SWAP",
  "as_of_ms": 1713009600000,
  "open_interest_contracts": 152340000,
  "open_interest_notional_usd": 318000000,
  "change_1h_pct": 0.034,
  "change_4h_pct": 0.112,
  "change_24h_pct": 0.186,
  "snapshot_time_ms": 1713009600000,
  "source": "okx",
  "staleness_ms": 0
}
```

## Interpretation Rules the Agent Should Eventually Benefit From

These are not hardcoded strategy rules, but they explain why the tools are
useful:

- High funding + rising OI:
  - crowded directional positioning with new leverage entering
- High funding + flat or falling OI:
  - crowding exists, but fresh leverage may be fading
- Negative funding + rising OI:
  - increasingly crowded short positioning
- Price move + OI divergence:
  - may reveal short covering, long liquidation, or weakening continuation

## Known Implementation Pitfalls

- Funding "current estimate" and final settled funding are not always the same;
  backtests must not leak values only known later.
- OI is snapshot data, not OHLCV candle data; missing intervals and stale
  snapshots must be handled explicitly.
- OI change metrics must be computed with historical alignment only, never using
  future points.
- Live mode and backtest mode should not directly share one naive provider call
  path.

## Practical Rollout Plan

### Phase 1 - Minimal Real Version

- Implement live-mode funding/OI provider adapters.
- Keep backtest mode returning `not_available` if historical market-structure
  data is absent.
- Update the Tool Gateway so the tools no longer return fake `0.0` placeholders.

Goal:

- live becomes meaningfully real first
- backtest remains honest instead of pretending data exists

### Phase 2 - Full Historical Support

- Add ingestion/sync jobs for historical funding and OI data.
- Store snapshots in dedicated tables.
- Query them through time-safe Tool Gateway handlers.
- Enrich `scan_market` with real funding/OI snapshots.

Goal:

- live and backtest share the same market-structure semantics
- the Agent can use funding and OI as first-class market tools

## Concrete Code Areas to Revisit Later

Primary follow-up files:

- `apps/api/app/services/market_data_store.py`
- `apps/api/app/tool_gateway/market_handlers.py`
- `apps/api/app/tool_gateway/demo_gateway.py`
- `apps/api/app/models.py`

Likely additions:

- a funding-rate storage/query module
- an open-interest storage/query module
- provider adapters for live market-structure data
- ingestion/sync jobs for historical funding/OI series
