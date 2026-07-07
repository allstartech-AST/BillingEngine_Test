"""Standalone OpenAI unit calculator from manually entered CPT codes and durations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.config import load_env_files
from app.engine.llm_billing_common import ruleset_label
from app.engine.llm_errors import LlmAuditError, LlmErrorInfo
from app.engine.llm_unit_core import run_llm_billing_calculation, unit_calc_raw_lines
from app.engine.loader import load_metadata

load_env_files()


class UnitCalcCode(BaseModel):
    cpt: str
    minutes: float = Field(gt=0)
    region: str = ""


class UnitCalcRequest(BaseModel):
    billing_rule: str = "cms_8_minute"
    codes: list[UnitCalcCode]


class UnitCalcCodeResult(BaseModel):
    cpt: str
    minutes: float
    units: int
    explanation: str


class UnitCalcResponse(BaseModel):
    rule_applied: str
    rule_label: str
    total_units: int
    codes: list[UnitCalcCodeResult]
    notes: str


async def run_unit_calculation(
    codes: list[dict[str, Any]],
    billing_rule: str,
) -> UnitCalcResponse:
    if not codes:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message="Add at least one CPT code with a duration greater than 0.",
                http_status=400,
                technical_detail="codes list is empty",
            )
        )

    store = load_metadata()
    parsed = await run_llm_billing_calculation(
        unit_calc_raw_lines(codes),
        billing_rule,
        mode="calculate",
        store=store,
    )

    code_results = [
        UnitCalcCodeResult(
            cpt=str(item["cpt"]),
            minutes=float(item.get("minutes", 0)),
            units=int(item.get("units", 0)),
            explanation=str(item.get("explanation", "")),
        )
        for item in parsed.get("codes", [])
    ]
    total_units = int(parsed.get("total_units", sum(c.units for c in code_results)))

    return UnitCalcResponse(
        rule_applied=str(parsed.get("rule_applied", "Medicare 8-Minute")),
        rule_label=ruleset_label(billing_rule),
        total_units=total_units,
        codes=code_results,
        notes=str(parsed.get("notes", "")),
    )
