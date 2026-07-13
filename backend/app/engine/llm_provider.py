"""LLM chat completions for structured JSON responses."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

from app.config import (
    LLM_GROQ_MIN_INTERVAL_SECONDS,
    LLM_REQUEST_INTERVAL_SECONDS,
    groq_base_url,
    llm_provider_name,
    load_env_files,
    openai_api_key,
    openai_model,
)
from app.engine.llm_errors import retry_after_from_exception
from app.engine.llm_quota import is_quota_error, mark_quota_exhausted

load_env_files()

logger = logging.getLogger(__name__)

_client = None
T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

_llm_request_lock = asyncio.Lock()
_last_llm_request_finished_at: float | None = None


def _effective_request_interval() -> float:
    interval = LLM_REQUEST_INTERVAL_SECONDS
    if llm_provider_name() == "Groq":
        return max(interval, LLM_GROQ_MIN_INTERVAL_SECONDS)
    return interval


async def _await_llm_request_slot() -> None:
    """Wait until the configured interval has elapsed since the last LLM call finished."""
    global _last_llm_request_finished_at
    interval = _effective_request_interval()
    if interval <= 0:
        return
    if _last_llm_request_finished_at is not None:
        elapsed = time.monotonic() - _last_llm_request_finished_at
        wait = interval - elapsed
        if wait > 0:
            logger.info(
                "LLM throttle: waiting %.1fs before next request (interval=%.1fs)",
                wait,
                interval,
            )
            await asyncio.sleep(wait)


def _mark_llm_request_finished() -> None:
    global _last_llm_request_finished_at
    _last_llm_request_finished_at = time.monotonic()


async def _run_throttled(coro_factory: Callable[[], Awaitable[R]]) -> R:
    """Run one LLM HTTP request with global spacing and mutual exclusion."""
    async with _llm_request_lock:
        await _await_llm_request_slot()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = await coro_factory()
                _mark_llm_request_finished()
                return result
            except Exception as exc:
                last_error = exc
                if attempt == 0 and is_quota_error(exc):
                    mark_quota_exhausted(exc)
                    retry_after = retry_after_from_exception(exc) or _effective_request_interval()
                    retry_after = max(retry_after + 1.0, _effective_request_interval())
                    logger.warning(
                        "LLM rate limit hit — waiting %.1fs before one retry",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    _mark_llm_request_finished()
                    continue
                _mark_llm_request_finished()
                raise
        assert last_error is not None
        _mark_llm_request_finished()
        raise last_error


def get_async_client():
    global _client
    api_key = openai_api_key()
    if not api_key:
        return None
    if _client is None:
        from openai import AsyncOpenAI

        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "max_retries": 0,
            "timeout": 60.0,
        }
        if llm_provider_name() == "Groq":
            client_kwargs["base_url"] = groq_base_url()
        _client = AsyncOpenAI(**client_kwargs)
    return _client


def is_configured() -> bool:
    return bool(openai_api_key())


def _example_from_schema_node(node: dict[str, Any], defs: dict[str, Any]) -> Any:
    if "$ref" in node:
        ref_name = node["$ref"].rsplit("/", 1)[-1]
        return _example_from_schema_node(defs[ref_name], defs)
    node_type = node.get("type")
    if node_type == "object":
        props = node.get("properties", {})
        return {
            key: _example_from_schema_node(prop, defs)
            for key, prop in props.items()
        }
    if node_type == "array":
        items = node.get("items", {})
        return [_example_from_schema_node(items, defs)]
    if node_type == "boolean":
        return False
    if node_type == "integer":
        return 0
    if node_type == "number":
        return 0.0
    if node_type == "string":
        return "string"
    if "anyOf" in node:
        for option in node["anyOf"]:
            if option.get("type") != "null":
                return _example_from_schema_node(option, defs)
    return None


def _example_payload_for_model(response_model: type[BaseModel]) -> dict[str, Any]:
    schema = response_model.model_json_schema()
    example = _example_from_schema_node(schema, schema.get("$defs", {}))
    if not isinstance(example, dict):
        return {}
    return example


def _build_schema_instruction(response_model: type[BaseModel]) -> str:
    example = _example_payload_for_model(response_model)
    return (
        "Return ONLY a JSON object with real values using this exact shape. "
        "Do not return a JSON schema, $defs, or property metadata.\n"
        f"{json.dumps(example, indent=2)}"
    )


def _inject_schema_instruction(
    messages: list[dict[str, str]], response_model: type[BaseModel]
) -> list[dict[str, str]]:
    schema_instruction = _build_schema_instruction(response_model)
    augmented_messages = [dict(message) for message in messages]
    if augmented_messages and augmented_messages[0].get("role") == "system":
        augmented_messages[0]["content"] = (
            f'{augmented_messages[0]["content"]}\n\n{schema_instruction}'
        )
        return augmented_messages
    return [{"role": "system", "content": schema_instruction}, *augmented_messages]


async def generate_json_pydantic(
    *,
    user_prompt: str,
    response_model: type[T],
    system_prompt: str | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return await generate_json_pydantic_messages(
        messages=messages,
        response_model=response_model,
        temperature=temperature,
    )


async def generate_json_pydantic_messages(
    *,
    messages: list[dict[str, str]],
    response_model: type[T],
    temperature: float = 0.2,
) -> dict[str, Any]:
    client = get_async_client()
    if client is None:
        raise ValueError(f"{llm_provider_name()} API key is not configured.")

    async def _call() -> dict[str, Any]:
        completion = await client.chat.completions.create(
            model=openai_model(),
            messages=_inject_schema_instruction(messages, response_model),
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError(f"{llm_provider_name()} returned an empty response.")
        try:
            parsed = response_model.model_validate_json(content)
        except Exception as exc:
            payload = json.loads(content)
            if isinstance(payload, dict) and "$defs" in payload:
                raise ValueError(
                    f"{llm_provider_name()} returned a JSON schema instead of data."
                ) from exc
            raise
        return parsed.model_dump()

    return await _run_throttled(_call)


async def generate_json_schema(
    *,
    user_prompt: str,
    json_schema: dict[str, Any],
    system_prompt: str | None = None,
    temperature: float = 0.1,
    timeout: float | None = None,
) -> dict[str, Any]:
    client = get_async_client()
    if client is None:
        raise ValueError(f"{llm_provider_name()} API key is not configured.")

    system = system_prompt or "You are a helpful assistant."
    schema_hint = json.dumps(
        _example_from_schema_node(json_schema, json_schema.get("$defs", {})),
        indent=2,
    )
    system += (
        "\n\nReturn ONLY a JSON object with real values using this exact shape. "
        "Do not return a JSON schema, $defs, or property metadata.\n"
        f"{schema_hint}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    kwargs: dict[str, Any] = {
        "model": openai_model(),
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout

    async def _call() -> dict[str, Any]:
        completion = await client.chat.completions.create(**kwargs)
        content = completion.choices[0].message.content
        if not content:
            raise ValueError(f"{llm_provider_name()} returned an empty response.")
        return json.loads(content)

    return await _run_throttled(_call)
