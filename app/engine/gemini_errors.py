"""Map Google Gemini SDK/API failures to user-facing error categories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GeminiErrorInfo:
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


class GeminiAuditError(Exception):
    """Raised when a Gemini compliance audit cannot complete."""

    def __init__(self, info: GeminiErrorInfo):
        self.info = info
        super().__init__(info.message)


_MODEL_RE = re.compile(r"model:\s*([^\s\\n]+)")
_LIMIT_ZERO_RE = re.compile(r"limit:\s*0\b")
_RETRY_AFTER_RE = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)


def _extract_model(text: str) -> str | None:
    match = _MODEL_RE.search(text)
    return match.group(1) if match else None


def _extract_retry_after(text: str) -> float | None:
    match = _RETRY_AFTER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def classify_gemini_error(exc: BaseException, *, model: str | None = None) -> GeminiErrorInfo:
    text = str(exc)
    lower = text.lower()
    detected_model = model or _extract_model(text)
    retry_after = _extract_retry_after(text)
    status_code = getattr(exc, "status_code", None)

    if status_code is None:
        code_match = re.search(r"\b(401|403|404|429|500|503)\b", text)
        if code_match:
            status_code = int(code_match.group(1))

    if status_code == 503 or "unavailable" in lower or "high demand" in lower:
        return GeminiErrorInfo(
            category="service_unavailable",
            message=(
                "Gemini is temporarily overloaded for this model. "
                "Wait a few seconds and click Verify again — the request usually succeeds on retry."
            ),
            http_status=503,
            technical_detail=text,
            model=detected_model,
            retry_after_seconds=retry_after or 5.0,
        )

    if status_code == 500 or "internal error" in lower:
        return GeminiErrorInfo(
            category="service_unavailable",
            message=(
                "Gemini returned a temporary server error. Wait a moment and try verification again."
            ),
            http_status=502,
            technical_detail=text,
            model=detected_model,
            retry_after_seconds=retry_after or 3.0,
        )
        return GeminiErrorInfo(
            category="invalid_api_key",
            message=(
                "The Gemini API key is invalid. Update GEMINI_API_KEY in .env.local "
                "with a key from Google AI Studio, then restart the server."
            ),
            http_status=401,
            technical_detail=text,
            model=detected_model,
        )

    if any(
        phrase in lower
        for phrase in (
            "api key not valid",
            "permission denied",
            "unauthenticated",
            "invalid authentication",
        )
    ):
        return GeminiErrorInfo(
            category="invalid_api_key",
            message=(
                "Gemini rejected the API key (authentication failed). Verify GEMINI_API_KEY "
                "in .env.local and restart the server."
            ),
            http_status=403 if status_code is None else int(status_code),
            technical_detail=text,
            model=detected_model,
        )

    if status_code == 404 or "not found" in lower and "model" in lower:
        return GeminiErrorInfo(
            category="unsupported_model",
            message=(
                f"The configured Gemini model{f' ({detected_model})' if detected_model else ''} "
                "is not available for this API key. Set GEMINI_AUDIT_MODEL to a supported model "
                "such as gemini-2.5-flash in .env.local."
            ),
            http_status=404,
            technical_detail=text,
            model=detected_model,
        )

    if status_code == 429 or "resource_exhausted" in lower or "quota exceeded" in lower:
        if _LIMIT_ZERO_RE.search(text) or "limit: 0" in lower:
            model_note = f" ({detected_model})" if detected_model else ""
            return GeminiErrorInfo(
                category="quota_exhausted",
                message=(
                    f"Gemini free-tier quota for model{model_note} is not available on this "
                    "Google AI Studio project (limit: 0). This project is configured to use "
                    "gemini-2.5-flash for compliance auditing. If the error persists, open "
                    "Google AI Studio → Billing and enable billing to activate free-tier quotas, "
                    "or upgrade to a paid tier."
                ),
                http_status=429,
                technical_detail=text,
                model=detected_model,
                retry_after_seconds=retry_after,
            )

        return GeminiErrorInfo(
            category="rate_limit_exceeded",
            message=(
                "Gemini rate limit exceeded. Wait a moment and try verification again."
                + (
                    f" Suggested retry after {int(retry_after)} seconds."
                    if retry_after
                    else ""
                )
            ),
            http_status=429,
            technical_detail=text,
            model=detected_model,
            retry_after_seconds=retry_after,
        )

    if "not configured" in lower or ("missing" in lower and "api key" in lower):
        return GeminiErrorInfo(
            category="missing_api_key",
            message=(
                "Gemini API key is not configured. Add GEMINI_API_KEY to .env.local "
                "and restart the server."
            ),
            http_status=503,
            technical_detail=text,
            model=detected_model,
        )

    return GeminiErrorInfo(
        category="gemini_api_error",
        message="Gemini audit failed due to an unexpected API error. See technical details below.",
        http_status=int(status_code) if status_code else 502,
        technical_detail=text,
        model=detected_model,
        retry_after_seconds=retry_after,
    )
