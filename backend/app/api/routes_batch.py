from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.engine.llm_errors import LlmAuditError
from app.engine.llm_audit import run_calculator_audit
from app.engine.llm_unit_calculator import UnitCalcRequest, UnitCalcResponse, run_unit_calculation
from app.engine.loader import load_metadata
from app.engine.pipeline import evaluate_session
from app.engine.summary_unit_validation import (
    SummaryValidateRequest,
    SummaryValidateResponse,
    validate_summary_units,
)
from app.models.input import BillingSessionInput
from app.models.output import BillingReport

router = APIRouter(prefix="/billing", tags=["batch"])


class ComplianceAuditRow(BaseModel):
    cpt: str
    duration_minutes: float = Field(gt=0)
    body_region: str = ""


class ComplianceAuditRequest(BaseModel):
    billing_rule: str = "cms_8_minute"
    rows: list[ComplianceAuditRow]


@router.post("/validate-summary-units", response_model=SummaryValidateResponse)
async def billing_validate_summary_units(body: SummaryValidateRequest) -> SummaryValidateResponse:
    try:
        store = load_metadata()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return await validate_summary_units(
            body.lines,
            body.billing_rule,
            store,
            auditor=body.auditor,
        )
    except LlmAuditError as exc:
        raise HTTPException(status_code=exc.info.http_status, detail=exc.info.as_detail()) from exc


@router.post("/llm-calculate-units", response_model=UnitCalcResponse)
async def billing_llm_calculate_units(body: UnitCalcRequest) -> UnitCalcResponse:
    try:
        codes = [
            {
                "cpt": c.cpt.strip(),
                "minutes": c.minutes,
                "region": c.region,
                "occurrence_count": c.occurrence_count,
                "area_sq_cm": c.area_sq_cm,
            }
            for c in body.codes
            if c.cpt.strip()
        ]
        return await run_unit_calculation(codes, body.billing_rule)
    except LlmAuditError as exc:
        raise HTTPException(status_code=exc.info.http_status, detail=exc.info.as_detail()) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "category": "llm_api_error",
                "message": "OpenAI unit calculation failed due to an unexpected server error.",
                "technical_detail": str(exc),
            },
        ) from exc


@router.post("/compliance-audit")
async def billing_compliance_audit(body: ComplianceAuditRequest) -> dict:
    try:
        rows = [row.model_dump() for row in body.rows if row.cpt.strip()]
        return await run_calculator_audit(rows, body.billing_rule)
    except LlmAuditError as exc:
        raise HTTPException(status_code=exc.info.http_status, detail=exc.info.as_detail()) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "category": "llm_api_error",
                "message": "OpenAI compliance audit failed due to an unexpected server error.",
                "technical_detail": str(exc),
            },
        ) from exc


@router.post("/evaluate", response_model=BillingReport)
def billing_evaluate(payload: BillingSessionInput) -> BillingReport:
    try:
        store = load_metadata()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Billing metadata failed to load",
                "error": str(exc),
                "type": type(exc).__name__,
                "hint": "Ensure JSON data files exist in backend/data and loader uses encoding=utf-8-sig",
            },
        ) from exc
    return evaluate_session(payload, store)
