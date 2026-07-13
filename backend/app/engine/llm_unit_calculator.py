"""LLM unit calculator from manually entered CPT codes and durations."""

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
    minutes: float = Field(ge=0, default=0)
    region: str = ""
    occurrence_count: int = Field(default=1, ge=1)
    area_sq_cm: float | None = Field(default=None, ge=0)


class UnitCalcRequest(BaseModel):
    billing_rule: str = "cms_8_minute"
    codes: list[UnitCalcCode]


class UnitCalcCodeResult(BaseModel):
    cpt: str
    minutes: float
    units: int
    explanation: str
    billing_rule: str | None = None


class UnitCalcResponse(BaseModel):
    rule_applied: str
    rule_label: str
    total_units: int
    codes: list[UnitCalcCodeResult]
    notes: str


def _normalize_cpt(value: str) -> str:
    return str(value).strip()


def _map_llm_code_rows(
    parsed: dict[str, Any],
    codes: list[dict[str, Any]],
    store,
) -> list[UnitCalcCodeResult]:
    llm_rows = parsed.get("codes") or []
    llm_by_cpt = {_normalize_cpt(row.get("cpt", "")): row for row in llm_rows if row.get("cpt")}

    if set(llm_by_cpt.keys()) != {_normalize_cpt(c["cpt"]) for c in codes}:
        if len(llm_rows) == len(codes):
            llm_by_cpt = {
                _normalize_cpt(codes[index]["cpt"]): llm_rows[index]
                for index in range(len(codes))
            }

    results: list[UnitCalcCodeResult] = []
    for row in codes:
        cpt = _normalize_cpt(row["cpt"])
        gem = llm_by_cpt.get(cpt, {})
        minutes = float(row.get("minutes", 0) or 0)
        results.append(
            UnitCalcCodeResult(
                cpt=cpt,
                minutes=float(gem.get("minutes", minutes)),
                units=int(round(float(gem.get("units", 0)))),
                explanation=str(gem.get("explanation", "")).strip(),
                billing_rule=store.billing_rule(cpt) if store.knows_cpt(cpt) else None,
            )
        )
    return results


async def run_unit_calculation(
    codes: list[dict[str, Any]],
    billing_rule: str,
) -> UnitCalcResponse:
    if not codes:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message="Add at least one CPT code.",
                http_status=400,
                technical_detail="codes list is empty",
            )
        )

    store = load_metadata()
    raw_lines = unit_calc_raw_lines(codes)
    parsed = await run_llm_billing_calculation(
        raw_lines,
        billing_rule,
        mode="calculate",
        store=store,
    )

    code_results = _map_llm_code_rows(parsed, codes, store)
    total_units = int(parsed.get("total_units", sum(item.units for item in code_results)))

    return UnitCalcResponse(
        rule_applied=str(parsed.get("rule_applied", ruleset_label(billing_rule))),
        rule_label=ruleset_label(billing_rule),
        total_units=total_units,
        codes=code_results,
        notes=str(parsed.get("notes", "")),
    )
