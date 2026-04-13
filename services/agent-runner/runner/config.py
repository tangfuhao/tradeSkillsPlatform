import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TradeSkills Agent Runner"
    provider: str = "openai-tools"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    tool_gateway_timeout_seconds: float = float(os.getenv("AGENT_RUNNER_TOOL_GATEWAY_TIMEOUT_SECONDS") or 20.0)
    openai_api_key: str = os.getenv("AGENT_RUNNER_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    openai_base_url: str = os.getenv("AGENT_RUNNER_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com"
    openai_model: str = os.getenv("AGENT_RUNNER_OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.1-codex-mini"
    openai_timeout_seconds: float = float(os.getenv("AGENT_RUNNER_OPENAI_TIMEOUT_SECONDS") or 60.0)
    openai_temperature: float = float(os.getenv("AGENT_RUNNER_OPENAI_TEMPERATURE") or 0.1)
    openai_max_tool_rounds: int = int(os.getenv("AGENT_RUNNER_OPENAI_MAX_TOOL_ROUNDS") or 8)
    openai_max_retries: int = int(os.getenv("AGENT_RUNNER_OPENAI_MAX_RETRIES") or 4)
    openai_retry_base_delay_seconds: float = float(os.getenv("AGENT_RUNNER_OPENAI_RETRY_BASE_DELAY_SECONDS") or 2.0)
    openai_retry_max_delay_seconds: float = float(os.getenv("AGENT_RUNNER_OPENAI_RETRY_MAX_DELAY_SECONDS") or 30.0)

    model_config = SettingsConfigDict(
        env_prefix="AGENT_RUNNER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
