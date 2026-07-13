"""Map OpenAI SDK/API failures to user-facing error categories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config import llm_provider_name, openai_model


@dataclass(frozen=True)
class LlmErrorInfo:
    category: str
    message: str
    http_status: int
    technical_detail: str
    model: str | None = None
    retry_after_seconds: float | None = None

    def as_detail(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "message": self.message,
            "technical_detail": self.technical_detail,
        }
        if self.model:
            payload["model"] = self.model
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload


class LlmAuditError(Exception):
    """Raised when an LLM compliance audit cannot complete."""

    def __init__(self, info: LlmErrorInfo):
        self.info = info
        super().__init__(info.message)


_RETRY_AFTER_RE = re.compile(r"retry after ([0-9.]+)", re.IGNORECASE)
_TRY_AGAIN_IN_RE = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)


def extract_retry_after(text: str) -> float | None:
    for pattern in (_RETRY_AFTER_RE, _TRY_AGAIN_IN_RE):
        match = pattern.search(text)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            continue
    return None


def retry_after_from_exception(exc: BaseException) -> float | None:
    retry_after = extract_retry_after(str(exc))
    if retry_after is not None:
        return retry_after

    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            header_value = headers.get("retry-after")
            if header_value:
                try:
                    return float(header_value)
                except ValueError:
                    pass
    return None


_extract_retry_after = extract_retry_after


def classify_llm_error(exc: BaseException, *, model: str | None = None) -> LlmErrorInfo:
    text = str(exc)
    lower = text.lower()
    model_name = model or openai_model()
    provider_name = llm_provider_name()
    api_key_name = "GROQ_API_KEY" if provider_name == "Groq" else "OPENAI_API_KEY"
    retry_after = extract_retry_after(text)

    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            RateLimitError,
        )
    except ImportError:
        AuthenticationError = RateLimitError = APIStatusError = None  # type: ignore
        APITimeoutError = APIConnectionError = BadRequestError = NotFoundError = None  # type: ignore

    if APITimeoutError is not None and isinstance(exc, APITimeoutError):
        return LlmErrorInfo(
            category="timeout",
            message=f"{provider_name} request timed out. Wait a moment and try again.",
            http_status=504,
            technical_detail=text,
            model=model_name,
        )

    if APIConnectionError is not None and isinstance(exc, APIConnectionError):
        return LlmErrorInfo(
            category="service_unavailable",
            message=f"Could not reach {provider_name}. Check your network and try again.",
            http_status=503,
            technical_detail=text,
            model=model_name,
        )

    if AuthenticationError is not None and isinstance(exc, AuthenticationError):
        return LlmErrorInfo(
            category="invalid_api_key",
            message=(
                "OpenAI rejected the API key. Verify OPENAI_API_KEY in backend/.env.local "
                f"and restart the server."
            ) if provider_name == "OpenAI" else (
                f"{provider_name} rejected the API key. Verify {api_key_name} in backend/.env.local "
                "and restart the server."
            ),
            http_status=401,
            technical_detail=text,
            model=model_name,
        )

    if RateLimitError is not None and isinstance(exc, RateLimitError):
        return LlmErrorInfo(
            category="rate_limit_exceeded",
            message=(
                f"{provider_name} rate limit or quota exceeded. Wait a moment and try again."
                + (f" Suggested retry after {int(retry_after)} seconds." if retry_after else "")
            ),
            http_status=429,
            technical_detail=text,
            model=model_name,
            retry_after_seconds=retry_after,
        )

    if NotFoundError is not None and isinstance(exc, NotFoundError):
        return LlmErrorInfo(
            category="unsupported_model",
            message=(
                f"The configured {provider_name} model ({model_name}) is not available. "
                + (
                    "Set GROQ_MODEL to a supported Groq model such as llama-3.1-8b-instant in .env.local."
                    if provider_name == "Groq"
                    else "Set OPENAI_MODEL to a supported model such as gpt-4o-mini in .env.local."
                )
            ),
            http_status=404,
            technical_detail=text,
            model=model_name,
        )

    if APIStatusError is not None and isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", 502) or 502
        if status == 503:
            return LlmErrorInfo(
                category="service_unavailable",
                message=f"{provider_name} is temporarily overloaded. Wait a few seconds and try again.",
                http_status=503,
                technical_detail=text,
                model=model_name,
                retry_after_seconds=retry_after or 5.0,
            )
        if status in {401, 403}:
            return LlmErrorInfo(
                category="invalid_api_key",
                message=(
                    f"{provider_name} rejected the API key. Verify {api_key_name} in backend/.env.local."
                ),
                http_status=int(status),
                technical_detail=text,
                model=model_name,
            )
        if status == 429:
            return LlmErrorInfo(
                category="rate_limit_exceeded",
                message=f"{provider_name} rate limit exceeded. Wait and try again.",
                http_status=429,
                technical_detail=text,
                model=model_name,
                retry_after_seconds=retry_after,
            )

    if BadRequestError is not None and isinstance(exc, BadRequestError):
        if "model" in lower and ("not found" in lower or "does not exist" in lower):
            return LlmErrorInfo(
                category="unsupported_model",
                message=(
                    f"The configured {provider_name} model ({model_name}) is not available. "
                    + (
                        "Set GROQ_MODEL in backend/.env.local."
                        if provider_name == "Groq"
                        else "Set OPENAI_MODEL in backend/.env.local."
                    )
                ),
                http_status=404,
                technical_detail=text,
                model=model_name,
            )

    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        code_match = re.search(r"\b(401|403|404|429|500|503)\b", text)
        if code_match:
            status_code = int(code_match.group(1))

    if "not configured" in lower or ("missing" in lower and "api key" in lower):
        return LlmErrorInfo(
            category="missing_api_key",
            message=(
                f"{provider_name} API key is not configured. Add {api_key_name} to backend/.env.local "
                "and restart the server."
            ),
            http_status=503,
            technical_detail=text,
            model=model_name,
        )

    return LlmErrorInfo(
        category="llm_api_error",
        message=f"{provider_name} request failed due to an unexpected API error. See technical details below.",
        http_status=int(status_code) if status_code else 502,
        technical_detail=text,
        model=model_name,
        retry_after_seconds=retry_after,
    )
