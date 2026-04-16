from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.utils import ms_to_datetime


class SkillCreateRequest(BaseModel):
    title: str | None = None
    skill_text: str = Field(min_length=20)


class ExecutionProgressResponse(BaseModel):
    total_steps: int = 0
    completed_steps: int = 0
    percent: float = 0.0
    last_processed_trace_index: int | None = None
    last_processed_trigger_time_ms: int | None = None


class ExecutionControlRequest(BaseModel):
    action: str = Field(min_length=1)
    expected_revision: int | None = Field(default=None, ge=1)


class SkillResponse(BaseModel):
    id: str
    title: str
    validation_status: str
    source_hash: str
    envelope: dict[str, Any]
    extraction_method: Literal["rule_only", "llm_fallback"] = "rule_only"
    fallback_used: bool = False
    validation_errors: list[str]
    validation_warnings: list[str]
    immutable: bool = True
    raw_text: str
    available_actions: list[str] = Field(default_factory=list)
    active_live_task_id: str | None = None
    created_at_ms: int
    updated_at_ms: int


class BacktestCreateRequest(BaseModel):
    skill_id: str
    start_time_ms: int
    end_time_ms: int
    initial_capital: float = Field(default=10000.0, gt=0)

    @property
    def start_time(self):
        return ms_to_datetime(self.start_time_ms)

    @property
    def end_time(self):
        return ms_to_datetime(self.end_time_ms)


class TraceResponse(BaseModel):
    id: str
    trace_index: int
    trigger_time_ms: int
    reasoning_summary: str
    decision: dict[str, Any]
    execution_timing: dict[str, Any] | None = None
    execution_breakdown: dict[str, Any] | None = None
    llm_rounds: list[dict[str, Any]] = Field(default_factory=list)
    recovery: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]]
    portfolio_before: dict[str, Any] | None = None
    portfolio_after: dict[str, Any] | None = None
    fills: list[dict[str, Any]] = Field(default_factory=list)


class BacktestResponse(BaseModel):
    id: str
    skill_id: str
    revision: int = 1
    status: str
    scope: str
    benchmark_name: str
    start_time_ms: int
    end_time_ms: int
    initial_capital: float
    claim_owner: str | None = None
    claim_expires_at_ms: int | None = None
    run_started_at_ms: int | None = None
    finished_at_ms: int | None = None
    progress: ExecutionProgressResponse = Field(default_factory=ExecutionProgressResponse)
    pending_action: str | None = None
    available_actions: list[str] = Field(default_factory=list)
    last_activity_at_ms: int | None = None
    summary: dict[str, Any] | None
    last_runtime_error: dict[str, Any] | None = None
    error_message: str | None
    created_at_ms: int
    updated_at_ms: int


class LiveTaskCreateRequest(BaseModel):
    skill_id: str


class LiveTaskResponse(BaseModel):
    id: str
    skill_id: str
    revision: int = 1
    status: str
    cadence: str
    cadence_seconds: int
    claim_owner: str | None = None
    claim_expires_at_ms: int | None = None
    available_actions: list[str] = Field(default_factory=list)
    last_activity_at_ms: int | None = None
    last_triggered_at_ms: int | None
    last_completed_slot_as_of_ms: int | None = None
    last_claimed_slot_as_of_ms: int | None = None
    created_at_ms: int
    updated_at_ms: int


class LiveSignalResponse(BaseModel):
    id: str
    live_task_id: str
    trigger_time_ms: int
    execution_time_ms: int
    dispatch_as_of_ms: int | None = None
    trigger_origin: str
    delivery_status: str
    signal: dict[str, Any]
    created_at_ms: int


class DatabaseHealthResponse(BaseModel):
    url: str
    backend: str
    driver: str
    status: str
    server_version: str | None = None
    current_revision: str | None = None
    required_revision: str | None = None
    compatible: bool = False
    writable: bool = False
    in_recovery: bool | None = None
    pool: dict[str, Any] = Field(default_factory=dict)
    market_candle_partitions: list[str] = Field(default_factory=list)
    error: str | None = None


class HealthResponse(BaseModel):
    name: str
    status: str
    database_url: str
    database: DatabaseHealthResponse
    agent_runner_base_url: str
    ingest_backlog: dict[str, Any] = Field(default_factory=dict)
    market_sync: dict[str, Any] = Field(default_factory=dict)
    market_sync_loop_running: bool
    last_sync_started_at_ms: int | None = None
    last_sync_completed_at_ms: int | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    server_time_ms: int


class CsvIngestionJobResponse(BaseModel):
    id: str
    source_path: str
    status: str
    requested_at_ms: int
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    runner_id: str | None = None
    rows_seen: int = 0
    rows_staged: int = 0
    rows_inserted: int = 0
    rows_filtered: int = 0
    coverage_start_ms: int | None = None
    coverage_end_ms: int | None = None
    error_message: str | None = None
    notes: dict[str, Any] = Field(default_factory=dict)


class CsvIngestionBacklogResponse(BaseModel):
    status: str
    pending_count: int = 0
    running_count: int = 0
    failed_count: int = 0
    completed_count: int = 0
    oldest_pending_requested_at_ms: int | None = None
    latest_completed_at_ms: int | None = None
    pending_paths_sample: list[str] = Field(default_factory=list)


class CsvIngestionDiscoveryResponse(BaseModel):
    scanned_count: int
    discovered_count: int
    jobs: list[CsvIngestionJobResponse] = Field(default_factory=list)
    backlog: CsvIngestionBacklogResponse


class CsvIngestionRunResponse(BaseModel):
    requested_limit: int | None = None
    completed_count: int = 0
    failed_count: int = 0
    jobs: list[CsvIngestionJobResponse] = Field(default_factory=list)
    discovery: CsvIngestionDiscoveryResponse | None = None
    backlog: CsvIngestionBacklogResponse


class MarketCandleResponse(BaseModel):
    market_symbol: str
    base_symbol: str
    timeframe: str
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    vol: float
    vol_ccy: float | None
    vol_quote: float | None
    confirm: bool
    source: str


class MarketOverviewResponse(BaseModel):
    historical_data_dir: str
    base_timeframe: str
    total_candles: int
    total_symbols: int
    coverage_start_ms: int | None
    coverage_end_ms: int | None
    coverage_ranges: list[dict[str, int]] = Field(default_factory=list)
    recent_csv_jobs: list[CsvIngestionJobResponse]
    ingest_backlog: CsvIngestionBacklogResponse
    sync_cursors: list[dict[str, Any]]
    tier1_freshness_ms_p95: int | None = None
    tier2_freshness_ms_p95: int | None = None
    bootstrap_pending_count: int = 0
    backfill_lag_symbol_count: int = 0
    market_sync: dict[str, Any] = Field(default_factory=dict)
    latest_coverage_snapshot: dict[str, Any] = Field(default_factory=dict)


class MarketSyncStatusResponse(BaseModel):
    status: str
    dispatch_as_of_ms: int | None = None
    coverage_ratio: float = 0.0
    degraded: bool = False
    blocked_reason: str | None = None
    snapshot_age_ms: int | None = None
    universe_active_count: int = 0
    fresh_symbol_count: int = 0
    missing_symbol_count: int = 0
    missing_symbols_sample: list[str] = Field(default_factory=list)
    universe_version: int | None = None
    ingest_backlog: CsvIngestionBacklogResponse
    latest_snapshot: dict[str, Any] = Field(default_factory=dict)
    recent_errors: list[dict[str, Any]] = Field(default_factory=list)


class MarketUniverseItemResponse(BaseModel):
    instrument_id: str
    base_symbol: str
    quote_asset: str
    instrument_type: str
    lifecycle_status: str
    priority_tier: str
    bootstrap_status: str
    last_trade_price: float | None = None
    volume_24h_usd: float | None = None
    discovered_at_ms: int
    last_seen_active_at_ms: int | None = None
    delisted_at_ms: int | None = None
    sync_state: dict[str, Any] | None = None


class ToolGatewayExecuteRequest(BaseModel):
    tool_name: str
    skill_id: str
    scope_kind: str
    scope_id: str
    mode: Literal["backtest", "live_signal"]
    trigger_time_ms: int
    as_of_ms: int | None = None
    trace_index: int | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    @property
    def trigger_time(self):
        return ms_to_datetime(self.trigger_time_ms)

    @property
    def as_of(self):
        return ms_to_datetime(self.as_of_ms) if self.as_of_ms is not None else None


class ToolGatewayExecuteResponse(BaseModel):
    status: str
    content: dict[str, Any] = Field(default_factory=dict)


class ToolGatewayBaseRequest(BaseModel):
    skill_id: str
    scope_kind: str
    scope_id: str
    mode: Literal["backtest", "live_signal"]
    trigger_time_ms: int
    as_of_ms: int | None = None
    trace_index: int | None = None

    @property
    def trigger_time(self):
        return ms_to_datetime(self.trigger_time_ms)

    @property
    def as_of(self):
        return ms_to_datetime(self.as_of_ms) if self.as_of_ms is not None else None


class ToolGatewayMarketScanRequest(ToolGatewayBaseRequest):
    top_n: int = Field(default=8, ge=1, le=20)
    sort_by: str = "volume_24h_usd"


class ToolGatewayMarketSymbolRequest(ToolGatewayBaseRequest):
    market_symbol: str = Field(min_length=1)


class ToolGatewayMarketCandlesRequest(ToolGatewayMarketSymbolRequest):
    timeframe: str = Field(min_length=1)
    limit: int = Field(default=80, ge=1, le=240)


class ToolGatewayStateGetRequest(ToolGatewayBaseRequest):
    pass


class ToolGatewayStateSaveRequest(ToolGatewayBaseRequest):
    patch: dict[str, Any] = Field(default_factory=dict)


class ToolGatewayPortfolioStateRequest(ToolGatewayBaseRequest):
    pass


class ToolGatewaySignalIntentRequest(ToolGatewayBaseRequest):
    action: str | None = None
    symbol: str | None = None
    direction: str | None = None
    size_pct: float = 0.0
    reason: str | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class PortfolioStateResponse(BaseModel):
    scope_kind: str
    scope_id: str
    skill_id: str
    account: dict[str, Any]
    positions: list[dict[str, Any]] = Field(default_factory=list)
    recent_fills: list[dict[str, Any]] = Field(default_factory=list)
