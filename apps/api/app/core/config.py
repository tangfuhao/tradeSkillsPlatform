from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVICE_ROOT.parents[1] if SERVICE_ROOT.parent.name == "apps" else SERVICE_ROOT
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "runtime"
DEFAULT_HISTORICAL_DATA_DIR = REPO_ROOT.parent / "data"


class Settings(BaseSettings):
    app_name: str = "TradeSkills API"
    api_prefix: str = "/api/v1"
    data_dir: Path = DEFAULT_DATA_DIR
    database_url: str = f"sqlite:///{(DEFAULT_DATA_DIR / 'trade_skills.db').as_posix()}"
    agent_runner_base_url: str = "http://localhost:8100"
    tool_gateway_base_url: str = "http://localhost:8000"
    tool_gateway_shared_secret: str = ""
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    preview_window_days: int = 90
    default_benchmark: str = "market_passive_reference"
    scheduler_timezone: str = "UTC"
    scheduler_coalesce: bool = True
    agent_runner_timeout_seconds: float = 60.0
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

    model_config = SettingsConfigDict(
        env_prefix="TRADE_SKILLS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.historical_data_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
