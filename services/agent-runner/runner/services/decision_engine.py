from __future__ import annotations

from runner.config import settings
from runner.services.openai_runtime import OpenAIToolDecisionEngine


def get_engine() -> OpenAIToolDecisionEngine:
    return OpenAIToolDecisionEngine(provider=settings.provider)
