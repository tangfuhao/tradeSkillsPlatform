from __future__ import annotations

import sys
from typing import Iterable

from runner.config import Settings, resolve_execute_reasoning_effort, settings
from runner.services.model_routing import (
    is_official_azure_openai_base_url,
    is_official_novita_base_url,
    resolve_model_route,
)


EXPECTED_PYTHON_MAJOR_MINOR = (3, 12)
EXPECTED_OPENAI_VERSION = "1.77.0"
MIN_TIMEOUT_SECONDS_FOR_GPT54_HIGH_REASONING = 120.0


def collect_startup_preflight_errors(
    config: Settings | None = None,
    *,
    runtime_python: tuple[int, int] | None = None,
    openai_version: str | None = None,
) -> list[str]:
    effective_config = config or settings
    errors: list[str] = []

    current_python = runtime_python or sys.version_info[:2]
    if current_python != EXPECTED_PYTHON_MAJOR_MINOR:
        errors.append(
            "Runner requires Python "
            f"{EXPECTED_PYTHON_MAJOR_MINOR[0]}.{EXPECTED_PYTHON_MAJOR_MINOR[1]}.x "
            f"to match the service Docker image and validated SDK matrix; found {current_python[0]}.{current_python[1]}."
        )

    installed_openai_version = openai_version or _detect_openai_version()
    if installed_openai_version != EXPECTED_OPENAI_VERSION:
        errors.append(
            f"Runner requires openai=={EXPECTED_OPENAI_VERSION}; found {installed_openai_version}."
        )

    if effective_config.openai_wire_api != "responses":
        errors.append(
            f"Unsupported AGENT_RUNNER_OPENAI_WIRE_API={effective_config.openai_wire_api!r}; only 'responses' is supported."
        )

    route = resolve_model_route(effective_config.openai_model, effective_config)
    if not route.requested_model_name:
        errors.append("AGENT_RUNNER_OPENAI_MODEL must not be empty.")

    effective_execute_reasoning = str(resolve_execute_reasoning_effort(effective_config) or "").lower()
    effective_global_reasoning = str(effective_config.openai_reasoning_effort or "").strip().lower()
    if (
        route.requested_model_name == "pa/gpt-5.4"
        and {effective_execute_reasoning, effective_global_reasoning}.intersection({"high", "xhigh"})
        and float(effective_config.openai_timeout_seconds or 0.0) < MIN_TIMEOUT_SECONDS_FOR_GPT54_HIGH_REASONING
    ):
        errors.append(
            "AGENT_RUNNER_OPENAI_TIMEOUT_SECONDS must be at least "
            f"{MIN_TIMEOUT_SECONDS_FOR_GPT54_HIGH_REASONING:.0f} "
            "when `pa/gpt-5.4` runs with high/xhigh reasoning, otherwise tool rounds can hit read timeouts."
        )

    if route.client_key == "openai":
        if not effective_config.openai_api_key:
            errors.append("AGENT_RUNNER_OPENAI_API_KEY is required for OpenAI routes.")
        if not effective_config.openai_base_url:
            errors.append("AGENT_RUNNER_OPENAI_BASE_URL is required for OpenAI routes.")

    if route.client_key == "novita":
        if not (effective_config.novita_api_key or effective_config.openai_api_key):
            errors.append(
                "AGENT_RUNNER_NOVITA_API_KEY is required for Novita routes "
                "(or explicitly mirror it to AGENT_RUNNER_OPENAI_API_KEY)."
            )
        if not effective_config.novita_base_url:
            errors.append("AGENT_RUNNER_NOVITA_BASE_URL is required for Novita routes.")
        if (
            route.requested_model_name.startswith("pa/")
            and route.using_compat_prefix_routing
            and not effective_config.allow_compat_model_prefix_routing
        ):
            errors.append(
                "Prefixed Novita models (`pa/*`) require the official Novita base URL "
                "`https://api.novita.ai/openai/v1`. Set AGENT_RUNNER_NOVITA_BASE_URL accordingly "
                "or explicitly opt in with AGENT_RUNNER_ALLOW_COMPAT_MODEL_PREFIX_ROUTING=true."
            )
        if effective_config.novita_base_url and not (
            is_official_novita_base_url(effective_config.novita_base_url)
            or effective_config.allow_compat_model_prefix_routing
        ):
            errors.append(
                "Non-official Novita base URLs are blocked by default. "
                "If you intentionally need a compatibility gateway, set "
                "AGENT_RUNNER_ALLOW_COMPAT_MODEL_PREFIX_ROUTING=true."
            )

    if route.client_key == "azure_openai":
        if not (effective_config.azure_openai_api_key or effective_config.openai_api_key):
            errors.append(
                "AGENT_RUNNER_AZURE_OPENAI_API_KEY is required for Azure routes "
                "(or explicitly mirror it to AGENT_RUNNER_OPENAI_API_KEY)."
            )
        if not effective_config.azure_openai_base_url:
            errors.append("AGENT_RUNNER_AZURE_OPENAI_BASE_URL is required for Azure routes.")
        if (
            route.requested_model_name.startswith("az/")
            and effective_config.azure_openai_base_url
            and not is_official_azure_openai_base_url(effective_config.azure_openai_base_url)
            and not effective_config.allow_compat_model_prefix_routing
        ):
            errors.append(
                "Prefixed Azure models (`az/*`) require an official Azure OpenAI base URL "
                "ending in `.openai.azure.com/openai`. To bypass intentionally, set "
                "AGENT_RUNNER_ALLOW_COMPAT_MODEL_PREFIX_ROUTING=true."
            )

    return errors


def assert_startup_preflight(config: Settings | None = None) -> None:
    errors = collect_startup_preflight_errors(config)
    if not errors:
        return
    raise RuntimeError(_format_preflight_errors(errors))


def _detect_openai_version() -> str:
    try:
        import openai  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return f"import-error:{exc}"
    return str(getattr(openai, "__version__", "unknown"))


def _format_preflight_errors(errors: Iterable[str]) -> str:
    formatted = "\n".join(f"- {item}" for item in errors)
    return (
        "Agent Runner startup preflight failed.\n"
        f"{formatted}\n"
        "Recreate the local environment to match the pinned runtime before starting the service."
    )
