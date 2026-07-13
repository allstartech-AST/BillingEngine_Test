import re

from pydantic import BaseModel, Field

from app.engine.llm_audit import (
    build_comparison,
    build_summary_engine_snapshot,
    run_compliance_audit,
)
from app.engine.llm_errors import LlmAuditError
from app.engine.loader import load_metadata
from app.engine.realtime.finalize_display import build_finalize_display
from app.engine.realtime.store import get_session
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/live/session", tags=["audit"])


class BillingSummaryLine(BaseModel):
    cpt: str
    description: str = ""
    duration_minutes: float = Field(ge=0)
    engine_units: int = Field(ge=0)
    modifier: str | None = None
    region: str = ""
    billing_rule: str | None = None


class LlmAuditRequest(BaseModel):
    billing_summary: list[BillingSummaryLine] | None = None
    billing_rule: str | None = None


class LlmAuditResponse(BaseModel):
    engine: dict
    llm: dict
    comparison: dict


def _parse_duration_from_display(display: str) -> float:
    if not display or display in ("—", "flat", "Manual"):
        return 0.0
    minute_match = re.match(r"^(\d+(?:\.\d+)?)\s*min", display.strip().lower())
    if minute_match:
        return float(minute_match.group(1))
    parts = display.split(":")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        hours, minutes, seconds = (int(part) for part in parts)
        return hours * 60 + minutes + seconds / 60
    return 0.0


def _primary_modifier(modifiers: list[str] | None) -> str | None:
    if not modifiers:
        return None
    for mod in modifiers:
        if mod and not mod.startswith("MUE"):
            return mod
    return modifiers[0]


def _billing_summary_from_finalize(state, store) -> list[dict]:
    finalize = build_finalize_display(state, store)
    summary: list[dict] = []
    for line in finalize.lines:
        summary.append(
            {
                "cpt": line.cpt_code,
                "description": line.description,
                "duration_minutes": _parse_duration_from_display(line.duration_display),
                "engine_units": line.units,
                "modifier": _primary_modifier(line.applied_modifiers),
                "region": line.region if line.region and line.region != "--" else "",
                "billing_rule": line.billing_rule,
            }
        )
    return summary


@router.post("/{session_id}/llm-audit", response_model=LlmAuditResponse)
async def live_session_llm_audit(
    session_id: str,
    body: LlmAuditRequest | None = None,
) -> LlmAuditResponse:
    try:
        store = load_metadata()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        state = get_session(session_id)
    except HTTPException as exc:
        raise exc

    body = body or LlmAuditRequest()
    billing_rule = body.billing_rule or state.billing_rule

    if body.billing_summary:
        billing_summary = [line.model_dump() for line in body.billing_summary]
    else:
        billing_summary = _billing_summary_from_finalize(state, store)

    if not billing_summary:
        raise HTTPException(
            status_code=400,
            detail="No billing summary lines to audit. Finalize the session first.",
        )

    try:
        llm = await run_compliance_audit(billing_summary, billing_rule)
    except LlmAuditError as exc:
        raise HTTPException(status_code=exc.info.http_status, detail=exc.info.as_detail()) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "category": "llm_api_error",
                "message": "OpenAI audit failed due to an unexpected server error.",
                "technical_detail": str(exc),
            },
        ) from exc

    engine = build_summary_engine_snapshot(billing_summary, billing_rule)
    comparison = build_comparison(engine, llm)

    return LlmAuditResponse(engine=engine, llm=llm, comparison=comparison)
