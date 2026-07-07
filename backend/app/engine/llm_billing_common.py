"""Shared helpers for LLM billing audits and unit calculations."""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import load_env_files, openai_model
from app.engine.llm_billing_rules import (
    build_llm_billing_payload,
    timing_rules_system_instructions,
)
from app.engine.llm_errors import LlmAuditError, LlmErrorInfo, classify_llm_error
from app.engine.llm_provider import generate_json_schema, is_configured
from app.engine.loader import MetadataStore

load_env_files()

_RETRYABLE_STATUS = {429, 503}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LLM_TIMEOUT_SECONDS = 60

_MISSING_KEY_MESSAGE = (
    "OpenAI API key is not configured. Add OPENAI_API_KEY to backend/.env.local "
    "and restart the server."
)


def ruleset_label(billing_rule: str) -> str:
    if billing_rule == "ama_rule_of_8":
        return "AMA Rule of Eight"
    return "Medicare 8-Minute Rule"


def build_billing_payload(
    lines: list[dict[str, Any]],
    billing_rule: str,
    store: MetadataStore,
) -> dict[str, Any]:
    return build_llm_billing_payload(
        lines,
        billing_rule,
        ruleset_label(billing_rule),
        store,
    )


async def call_openai_json_schema(
    *,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict[str, Any],
    temperature: float = 0.1,
    timeout: float | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    missing_key_message: str = _MISSING_KEY_MESSAGE,
    failure_message: str = "OpenAI request failed after multiple attempts.",
    timeout_message: str | None = None,
) -> dict[str, Any]:
    if not is_configured():
        raise LlmAuditError(
            LlmErrorInfo(
                category="missing_api_key",
                message=missing_key_message,
                http_status=503,
                technical_detail="OPENAI_API_KEY is unset.",
            )
        )

    model_name = openai_model()
    last_error: LlmAuditError | None = None
    for attempt in range(max_attempts):
        try:
            coro = generate_json_schema(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=json_schema,
                temperature=temperature,
            )
            if timeout is not None:
                return await asyncio.wait_for(coro, timeout=timeout)
            return await coro
        except TimeoutError as exc:
            raise LlmAuditError(
                LlmErrorInfo(
                    category="timeout",
                    message=timeout_message or "OpenAI request timed out.",
                    http_status=504,
                    technical_detail=(
                        f"Exceeded {timeout}s"
                        if timeout is not None
                        else "Request timed out."
                    ),
                    model=model_name,
                )
            ) from exc
        except Exception as exc:
            info = classify_llm_error(exc, model=model_name)
            last_error = LlmAuditError(info)
            if info.http_status in _RETRYABLE_STATUS and attempt < max_attempts - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise last_error from exc

    raise last_error or LlmAuditError(
        LlmErrorInfo(
            category="llm_api_error",
            message=failure_message,
            http_status=502,
            technical_detail="No response received.",
            model=model_name,
        )
    )


__all__ = [
    "DEFAULT_LLM_TIMEOUT_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "build_billing_payload",
    "build_llm_billing_payload",
    "call_openai_json_schema",
    "ruleset_label",
    "timing_rules_system_instructions",
]
