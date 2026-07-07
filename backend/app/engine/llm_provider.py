"""LLM chat completions for structured JSON responses."""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import (
    groq_base_url,
    llm_provider_name,
    load_env_files,
    openai_api_key,
    openai_model,
)

load_env_files()

logger = logging.getLogger(__name__)

_client = None
T = TypeVar("T", bound=BaseModel)


def get_async_client():
    global _client
    api_key = openai_api_key()
    if not api_key:
        return None
    if _client is None:
        from openai import AsyncOpenAI

        if llm_provider_name() == "Groq":
            _client = AsyncOpenAI(api_key=api_key, base_url=groq_base_url())
        else:
            _client = AsyncOpenAI(api_key=api_key)
    return _client


def is_configured() -> bool:
    return bool(openai_api_key())


def _build_schema_instruction(json_schema: dict[str, Any]) -> str:
    schema_hint = json.dumps(json_schema, indent=2)
    return (
        "Return ONLY valid JSON matching this schema (no markdown fences):\n"
        f"{schema_hint}"
    )


def _inject_schema_instruction(
    messages: list[dict[str, str]], json_schema: dict[str, Any]
) -> list[dict[str, str]]:
    schema_instruction = _build_schema_instruction(json_schema)
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

    completion = await client.chat.completions.create(
        model=openai_model(),
        messages=_inject_schema_instruction(messages, response_model.model_json_schema()),
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ValueError(f"{llm_provider_name()} returned an empty response.")
    parsed = response_model.model_validate_json(content)
    return parsed.model_dump()


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
    system += f"\n\n{_build_schema_instruction(json_schema)}"

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

    completion = await client.chat.completions.create(**kwargs)
    content = completion.choices[0].message.content
    if not content:
        raise ValueError(f"{llm_provider_name()} returned an empty response.")
    return json.loads(content)
