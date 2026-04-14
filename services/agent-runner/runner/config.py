from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    app_name: str = "TradeSkills Agent Runner"
    provider: str = "openai-tools"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    tool_gateway_timeout_seconds: float = 20.0
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    azure_openai_api_key: str = ""
    azure_openai_base_url: str = ""
    azure_openai_api_version: str = "2025-04-01-preview"
    novita_api_key: str = ""
    novita_base_url: str = "https://api.novita.ai/openai/v1"
    allow_compat_model_prefix_routing: bool = False
    openai_wire_api: str = "responses"
    openai_model: str = "pa/gpt-5.4"
    openai_reasoning_effort: str = "medium"
    openai_timeout_seconds: float = 120.0
    openai_temperature: float = 0.1
    openai_max_tool_rounds: int = 8
    openai_max_retries: int = 4
    openai_retry_base_delay_seconds: float = 2.0
    openai_retry_max_delay_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_prefix="AGENT_RUNNER_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
