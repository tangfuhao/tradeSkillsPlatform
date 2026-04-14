from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openai import OpenAI

from runner.config import settings


AZURE_OPENAI_MODEL_PREFIX = "az/"
AZURE_OPENAI_RESPONSES_MODEL_PREFIX = "az/gpt-"
NOVITA_MODEL_PREFIX = "pa/"
NOVITA_RESPONSES_MODEL_PREFIX = "pa/gpt-"


@dataclass(frozen=True, slots=True)
class ModelRoute:
    requested_model_name: str
    upstream_model_name: str
    client_key: str
    base_url: str
    api_key_present: bool
    supports_reasoning: bool = True
    supports_temperature: bool = False
    using_compat_prefix_routing: bool = False


def resolve_model_route(model_name: str, config: Any | None = None) -> ModelRoute:
    effective_config = config or settings
    normalized_model_name = str(model_name or "").strip()

    if normalized_model_name.startswith(AZURE_OPENAI_MODEL_PREFIX):
        base_url = effective_config.azure_openai_base_url or effective_config.openai_base_url
        return ModelRoute(
            requested_model_name=normalized_model_name,
            upstream_model_name=normalized_model_name[len(AZURE_OPENAI_MODEL_PREFIX) :],
            client_key="azure_openai",
            base_url=base_url,
            api_key_present=bool(effective_config.azure_openai_api_key or effective_config.openai_api_key),
            using_compat_prefix_routing=not is_official_azure_openai_base_url(base_url),
        )

    if normalized_model_name.startswith(NOVITA_MODEL_PREFIX):
        base_url = effective_config.novita_base_url
        use_compat_prefix_routing = not is_official_novita_base_url(base_url)
        upstream_model_name = (
            normalized_model_name[len(NOVITA_MODEL_PREFIX) :]
            if use_compat_prefix_routing
            else normalized_model_name
        )
        return ModelRoute(
            requested_model_name=normalized_model_name,
            upstream_model_name=upstream_model_name,
            client_key="novita",
            base_url=base_url,
            api_key_present=bool(effective_config.novita_api_key or effective_config.openai_api_key),
            using_compat_prefix_routing=use_compat_prefix_routing,
        )

    return ModelRoute(
        requested_model_name=normalized_model_name,
        upstream_model_name=normalized_model_name,
        client_key="openai",
        base_url=effective_config.openai_base_url,
        api_key_present=bool(effective_config.openai_api_key),
    )


def resolve_upstream_model_name(model_name: str) -> str:
    return resolve_model_route(model_name).upstream_model_name


def get_responses_client_key(model_name: str) -> str:
    return resolve_model_route(model_name).client_key


def get_responses_client(model_name: str) -> OpenAI:
    client_key = get_responses_client_key(model_name)
    if client_key == "azure_openai":
        return _azure_openai_client()
    if client_key == "novita":
        return _novita_client()
    return _openai_client()


def is_official_novita_base_url(base_url: str) -> bool:
    normalized = str(base_url or "").strip().lower().rstrip("/")
    return normalized.startswith("https://api.novita.ai/")


def is_official_azure_openai_base_url(base_url: str) -> bool:
    normalized = str(base_url or "").strip().lower().rstrip("/")
    return normalized.startswith("https://") and ".openai.azure.com/openai" in normalized


def _build_client(
    *,
    api_key: str,
    base_url: str,
    default_query: dict[str, str] | None = None,
) -> OpenAI:
    client_kwargs: dict[str, object] = {
        "api_key": api_key,
        "timeout": settings.openai_timeout_seconds,
        "max_retries": settings.openai_max_retries,
    }
    normalized_base_url = str(base_url or "").strip()
    if normalized_base_url:
        client_kwargs["base_url"] = normalized_base_url.rstrip("/")
    if default_query:
        client_kwargs["default_query"] = default_query
    return OpenAI(**client_kwargs)


@lru_cache(maxsize=1)
def _openai_client() -> OpenAI:
    return _build_client(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


@lru_cache(maxsize=1)
def _azure_openai_client() -> OpenAI:
    default_query = None
    if str(settings.azure_openai_base_url or "").strip():
        default_query = {"api-version": settings.azure_openai_api_version}
    return _build_client(
        api_key=settings.azure_openai_api_key or settings.openai_api_key,
        base_url=settings.azure_openai_base_url or settings.openai_base_url,
        default_query=default_query,
    )


@lru_cache(maxsize=1)
def _novita_client() -> OpenAI:
    return _build_client(
        api_key=settings.novita_api_key or settings.openai_api_key,
        base_url=settings.novita_base_url,
    )
