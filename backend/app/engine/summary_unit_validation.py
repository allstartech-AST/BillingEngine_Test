"""Validate that summary-assigned units match durations documented in the summary."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.engine.billing_dispatcher import calculate_all_units
from app.engine.llm_billing_common import ruleset_label
from app.engine.loader import MetadataStore

FALLBACK_MESSAGE = (
    "Independent validation is temporarily unavailable. "
    "Displaying local validation results."
)

logger = logging.getLogger(__name__)

SummaryAuditor = Literal["local", "openai", "auto"]


class SummaryValidateLine(BaseModel):
    cpt: str
    duration_minutes: float = Field(ge=0)
    summary_units: int = Field(ge=0)
    billing_rule: str | None = None
    occurrence_count: int = Field(default=1, ge=1)
    area_sq_cm: float | None = Field(default=None, ge=0)


class SummaryValidateRequest(BaseModel):
    lines: list[SummaryValidateLine]
    billing_rule: str = "cms_8_minute"
    auditor: SummaryAuditor = "local"


class SummaryValidateRow(BaseModel):
    cpt: str
    duration_minutes: int
    billing_rule: str | None
    expected_units: int
    summary_units: int
    status: str
    message: str


class SummaryValidateResponse(BaseModel):
    billing_rule: str
    rule_label: str
    overall_status: str
    rows: list[SummaryValidateRow]
    auditor: str = "local"
    fallback_message: str | None = None


def _rule_label(billing_rule: str) -> str:
    return ruleset_label(billing_rule)


def _build_segments(lines: list[SummaryValidateLine]) -> dict[str, dict]:
    segments: dict[str, dict] = {}
    for line in lines:
        cpt = line.cpt.strip()
        minutes_billed = max(0, int(round(line.duration_minutes)))
        segments[cpt] = {
            "minutes": float(line.duration_minutes),
            "minutes_exact": float(line.duration_minutes),
            "minutes_billed": minutes_billed,
            "sequences": list(range(1, line.occurrence_count + 1)),
            "area_sq_cm": float(line.area_sq_cm or 0),
        }
    return segments


def _expected_units_by_cpt(
    lines: list[SummaryValidateLine],
    billing_rule: str,
    store: MetadataStore,
) -> dict[str, int]:
    segments = _build_segments(lines)
    if not segments:
        return {}

    unit_results = calculate_all_units(segments, store, billing_rule)

    return {item.cpt_code: item.units for item in unit_results}


def validate_summary_units_local(
    lines: list[SummaryValidateLine],
    billing_rule: str,
    store: MetadataStore,
) -> SummaryValidateResponse:
    if not lines:
        return SummaryValidateResponse(
            billing_rule=billing_rule,
            rule_label=_rule_label(billing_rule),
            overall_status="PASSED",
            rows=[],
            auditor="local",
        )

    expected_map = _expected_units_by_cpt(lines, billing_rule, store)
    result_rows: list[SummaryValidateRow] = []
    all_passed = True

    for line in lines:
        cpt = line.cpt.strip()
        cpt_billing_rule = (
            line.billing_rule
            if line.billing_rule is not None
            else store.billing_rule(cpt)
        )
        duration_minutes = max(0, int(round(line.duration_minutes)))
        expected_units = expected_map.get(cpt, 0)
        summary_units = line.summary_units
        passed = expected_units == summary_units
        if not passed:
            all_passed = False

        if passed:
            message = (
                f"Summary duration of {duration_minutes} minute"
                f"{'s' if duration_minutes != 1 else ''} supports {expected_units} unit"
                f"{'s' if expected_units != 1 else ''} — matches assigned units."
            )
        else:
            message = (
                f"Summary duration supports {expected_units} unit"
                f"{'s' if expected_units != 1 else ''}, but the generated summary assigned "
                f"{summary_units} unit{'s' if summary_units != 1 else ''}."
            )

        result_rows.append(
            SummaryValidateRow(
                cpt=cpt,
                duration_minutes=duration_minutes,
                billing_rule=cpt_billing_rule,
                expected_units=expected_units,
                summary_units=summary_units,
                status="PASSED" if passed else "FAILED",
                message=message,
            )
        )

    return SummaryValidateResponse(
        billing_rule=billing_rule,
        rule_label=_rule_label(billing_rule),
        overall_status="PASSED" if all_passed else "FAILED",
        rows=result_rows,
        auditor="local",
    )


async def validate_summary_units(
    lines: list[SummaryValidateLine],
    billing_rule: str,
    store: MetadataStore,
    *,
    auditor: SummaryAuditor = "local",
) -> SummaryValidateResponse:
    """Validate summary units — local engine by default; OpenAI when requested."""
    if not lines:
        return SummaryValidateResponse(
            billing_rule=billing_rule,
            rule_label=_rule_label(billing_rule),
            overall_status="PASSED",
            rows=[],
            auditor=auditor if auditor != "auto" else "local",
        )

    if auditor == "local":
        return validate_summary_units_local(lines, billing_rule, store)

    from app.engine.llm_errors import LlmAuditError
    from app.engine.summary_llm_validation import validate_summary_units_llm

    try:
        return await validate_summary_units_llm(lines, billing_rule, store)
    except (LlmAuditError, asyncio.TimeoutError, TimeoutError) as exc:
        if auditor == "openai":
            raise
        detail = getattr(exc, "info", None)
        if detail is not None:
            logger.warning(
                "Summary unit validation falling back to local rules (%s): %s",
                detail.category,
                detail.technical_detail,
            )
        else:
            logger.warning("Summary unit validation falling back to local rules: %s", exc)
        local = validate_summary_units_local(lines, billing_rule, store)
        return local.model_copy(
            update={
                "auditor": "local",
                "fallback_message": FALLBACK_MESSAGE,
            }
        )
    except Exception:
        if auditor == "openai":
            raise
        logger.exception("Unexpected OpenAI summary validation error")
        local = validate_summary_units_local(lines, billing_rule, store)
        return local.model_copy(
            update={
                "auditor": "local",
                "fallback_message": FALLBACK_MESSAGE,
            }
        )
