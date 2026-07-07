"""OpenAI rate-limit / quota cooldown helpers for live enrichment."""

from __future__ import annotations

import logging
import time

from app.engine.llm_errors import extract_retry_after

logger = logging.getLogger(__name__)

_quota_cooldown_until = 0.0


def quota_on_cooldown() -> bool:
    return time.monotonic() < _quota_cooldown_until


def mark_quota_exhausted(exc: Exception) -> None:
    global _quota_cooldown_until
    retry_after = extract_retry_after(str(exc)) or 60.0
    _quota_cooldown_until = time.monotonic() + retry_after
    logger.warning(
        "OpenAI quota/rate limit hit; pausing AI enrichment for %.0fs: %s",
        retry_after,
        exc,
    )


def is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "rate_limit" in text
        or "quota" in text
        or "insufficient_quota" in text
    )
