from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVICE_ROOT.parents[1] if SERVICE_ROOT.parent.name == "apps" else SERVICE_ROOT
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "runtime"
DEFAULT_HISTORICAL_DATA_DIR = REPO_ROOT.parent / "data"
DEFAULT_DATABASE_URL = "postgresql+psycopg://tradeskills:tradeskills@127.0.0.1:5432/tradeskills"


class Settings(BaseSettings):
    app_name: str = "TradeSkills API"
    api_prefix: str = "/api/v1"
    data_dir: Path = DEFAULT_DATA_DIR
    database_url: str = DEFAULT_DATABASE_URL
    database_pool_size: int = 20
    database_max_overflow: int = 20
    database_pool_timeout_seconds: float = 30.0
    database_pool_recycle_seconds: float = 1800.0
    database_connect_timeout_seconds: int = 10
    database_statement_timeout_ms: int = 30000
    database_bulk_statement_timeout_ms: int = 0
    database_lock_timeout_ms: int = 5000
    database_health_slow_query_ms: int = 1000
    agent_runner_base_url: str = "http://localhost:8100"
    tool_gateway_base_url: str = "http://localhost:8000"
    tool_gateway_shared_secret: str = ""
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    default_benchmark: str = "market_passive_reference"
    agent_runner_timeout_seconds: float = 180.0
    historical_data_dir: Path = DEFAULT_HISTORICAL_DATA_DIR
    historical_csv_glob: str = "allswap-candlesticks-*.csv"
    historical_base_timeframe: str = "1m"
    startup_sync_blocking: bool = True
    startup_sync_require_success: bool = True
    okx_api_base_url: str = "https://www.okx.com"
    okx_incremental_sync_enabled: bool = False
    okx_request_pause_seconds: float = 0.15
    okx_history_limit: int = 100
    okx_incremental_max_gap_days: int = 7
    market_scan_limit_default: int = 50
    startup_sync_target_offset_days: int = 1
    market_sync_loop_interval_seconds: float = 60.0
    live_data_freshness_seconds: float = 180.0
    market_universe_refresh_interval_seconds: float = 300.0
    market_sync_schedule_interval_seconds: float = 15.0
    market_sync_cycle_symbol_limit: int = 40
    market_sync_tier1_target_seconds: float = 60.0
    market_sync_tier2_target_seconds: float = 180.0
    market_sync_tier3_target_seconds: float = 900.0
    market_sync_symbol_max_pages_per_run: int = 20
    market_sync_symbol_time_budget_seconds: float = 20.0
    market_sync_retry_limit: int = 3
    market_sync_non_retryable_delay_seconds: float = 900.0
    market_sync_lease_ttl_seconds: float = 600.0
    market_sync_bootstrap_window_hours: int = 72
    market_sync_tier1_symbol_count: int = 50
    market_sync_required_coverage_ratio: float = 0.95
    market_sync_delist_after_missed_refreshes: int = 3
    market_sync_queue_enabled: bool = False
    market_sync_redis_url: str = "redis://localhost:6379/0"
    market_sync_worker_poll_seconds: float = 1.0
    market_sync_worker_heartbeat_ttl_seconds: float = 30.0
    live_task_execution_claim_ttl_seconds: float = 300.0
    backtest_run_claim_ttl_seconds: float = 900.0
    market_candle_partition_months_back: int = 24
    market_candle_partition_months_ahead: int = 3
    market_candle_hot_retention_months: int = 36

    model_config = SettingsConfigDict(
        env_prefix="TRADE_SKILLS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def safe_database_url(self) -> str:
        return make_url(self.database_url).render_as_string(hide_password=True)

    @property
    def database_backend(self) -> str:
        return make_url(self.database_url).get_backend_name()

    @property
    def database_driver(self) -> str:
        return make_url(self.database_url).get_driver_name()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.historical_data_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
