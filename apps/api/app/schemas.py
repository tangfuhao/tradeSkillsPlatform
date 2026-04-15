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
    tool_calls: list[dict[str, Any]]
    portfolio_before: dict[str, Any] | None = None
    portfolio_after: dict[str, Any] | None = None
    fills: list[dict[str, Any]] = Field(default_factory=list)


class BacktestResponse(BaseModel):
    id: str
    skill_id: str
    status: str
    scope: str
    benchmark_name: str
    start_time_ms: int
    end_time_ms: int
    initial_capital: float
    progress: ExecutionProgressResponse = Field(default_factory=ExecutionProgressResponse)
    pending_action: str | None = None
    available_actions: list[str] = Field(default_factory=list)
    last_activity_at_ms: int | None = None
    summary: dict[str, Any] | None
    error_message: str | None
    created_at_ms: int
    updated_at_ms: int


class LiveTaskCreateRequest(BaseModel):
    skill_id: str


class LiveTaskResponse(BaseModel):
    id: str
    skill_id: str
    status: str
    cadence: str
    cadence_seconds: int
    available_actions: list[str] = Field(default_factory=list)
    last_activity_at_ms: int | None = None
    last_triggered_at_ms: int | None
    created_at_ms: int
    updated_at_ms: int


class LiveSignalResponse(BaseModel):
    id: str
    live_task_id: str
    trigger_time_ms: int
    delivery_status: str
    signal: dict[str, Any]
    created_at_ms: int


class HealthResponse(BaseModel):
    name: str
    status: str
    database_url: str
    agent_runner_base_url: str
    scheduler_running: bool
    active_scheduler_jobs: int
    server_time_ms: int


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
    recent_csv_jobs: list[dict[str, Any]]
    sync_cursors: list[dict[str, Any]]


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
