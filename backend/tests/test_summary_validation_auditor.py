"""Summary validation auditor routing (Phase 3)."""

from __future__ import annotations

import asyncio

import pytest

from app.engine.loader import load_metadata
from app.engine.llm_errors import LlmAuditError
from app.engine.summary_unit_validation import (
    SummaryValidateLine,
    validate_summary_units,
    validate_summary_units_local,
)

_CAPTURE_LINES = [
    SummaryValidateLine(cpt="97110", duration_minutes=8, summary_units=0),
    SummaryValidateLine(cpt="97140", duration_minutes=16, summary_units=1),
    SummaryValidateLine(cpt="97530", duration_minutes=28, summary_units=2),
]


def test_default_auditor_local_no_llm() -> None:
    store = load_metadata()

    async def _run() -> None:
        result = await validate_summary_units(_CAPTURE_LINES, "cms_8_minute", store)
        assert result.auditor == "local"
        assert result.overall_status == "PASSED"

        explicit = await validate_summary_units(
            _CAPTURE_LINES, "cms_8_minute", store, auditor="local"
        )
        assert explicit.model_dump() == result.model_dump()

    asyncio.run(_run())


def test_openai_auditor_raises_without_api_key() -> None:
    store = load_metadata()
    lines = [SummaryValidateLine(cpt="97110", duration_minutes=15, summary_units=1)]

    async def _run() -> None:
        with pytest.raises(LlmAuditError):
            await validate_summary_units(lines, "cms_8_minute", store, auditor="openai")

    asyncio.run(_run())


def test_auto_auditor_falls_back_to_local_without_api_key() -> None:
    store = load_metadata()
    lines = [SummaryValidateLine(cpt="97110", duration_minutes=15, summary_units=1)]

    async def _run() -> None:
        result = await validate_summary_units(lines, "cms_8_minute", store, auditor="auto")
        assert result.auditor == "local"
        assert result.fallback_message

    asyncio.run(_run())


def test_local_matches_engine_for_capture_demo_units() -> None:
    store = load_metadata()
    local = validate_summary_units_local(_CAPTURE_LINES, "cms_8_minute", store)
    assert local.overall_status == "PASSED"
    by_cpt = {row.cpt: row.expected_units for row in local.rows}
    assert by_cpt == {"97110": 0, "97140": 1, "97530": 2}
