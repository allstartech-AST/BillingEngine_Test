"""Standalone Gemini unit calculator from manually entered CPT codes and durations."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field

from app.config import gemini_api_key, gemini_audit_model, load_env_files
from app.engine.gemini_errors import GeminiAuditError, GeminiErrorInfo, classify_gemini_error

load_env_files()

SYSTEM_PROMPT = """You are an expert in US outpatient rehabilitation therapy (PT/OT/SLP) billing unit calculations.

Given CPT codes and durations in minutes, calculate billable units using ONLY the timing rule specified in the input:
- Medicare 8-Minute Rule: CMS pooled timed-minute rule across timed CPT codes in the list
- AMA Rule of Eight: per-code rule-of-eighths thresholds

Do not validate against any billing engine, transcript, or patient summary.
Do not compare to pre-assigned units.
Only calculate units from the provided codes and minutes.

Return ONLY valid JSON matching the required schema."""


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rule_applied": {
            "type": "string",
            "enum": ["Medicare 8-Minute", "AMA Rule of 8"],
        },
        "total_units": {"type": "number"},
        "codes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cpt": {"type": "string"},
                    "minutes": {"type": "number"},
                    "units": {"type": "number"},
                    "explanation": {"type": "string"},
                },
                "required": ["cpt", "minutes", "units", "explanation"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["rule_applied", "total_units", "codes", "notes"],
}


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


def _ruleset_label(billing_rule: str) -> str:
    if billing_rule == "ama_rule_of_8":
        return "AMA Rule of Eight"
    return "Medicare 8-Minute Rule"


def _build_user_prompt(codes: list[dict[str, Any]], billing_rule: str) -> str:
    payload = {
        "rule": _ruleset_label(billing_rule),
        "codes": [
            {"cpt": code["cpt"], "minutes": code["minutes"]}
            for code in codes
        ],
    }
    return (
        "Calculate billable units for the following CPT codes and durations.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Apply the specified timing rule and return units per code plus total_units."
    )


def _response_text(response) -> str:
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                return part_text
    raise GeminiAuditError(
        GeminiErrorInfo(
            category="gemini_api_error",
            message="Gemini returned an empty response. Try again.",
            http_status=502,
            technical_detail="No text content in Gemini response.",
            model=gemini_audit_model(),
        )
    )


_RETRYABLE_STATUS = {429, 503}
_MAX_ATTEMPTS = 3


async def run_unit_calculation(
    codes: list[dict[str, Any]],
    billing_rule: str,
) -> UnitCalcResponse:
    if not codes:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="gemini_api_error",
                message="Add at least one CPT code with a duration greater than 0.",
                http_status=400,
                technical_detail="codes list is empty",
            )
        )

    api_key = gemini_api_key()
    if not api_key:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="missing_api_key",
                message=(
                    "Gemini API key is not configured. Add GEMINI_API_KEY to .env.local "
                    "and restart the server."
                ),
                http_status=503,
                technical_detail="GEMINI_API_KEY and VITE_GEMINI_API_KEY are both unset.",
            )
        )

    from google import genai
    from google.genai import types

    model_name = gemini_audit_model()
    client = genai.Client(api_key=api_key)
    prompt = _build_user_prompt(codes, billing_rule)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        temperature=0.1,
    )

    response = None
    last_error: GeminiAuditError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            last_error = None
            break
        except Exception as exc:
            info = classify_gemini_error(exc, model=model_name)
            last_error = GeminiAuditError(info)
            if info.http_status in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise last_error from exc

    if response is None:
        raise last_error or GeminiAuditError(
            GeminiErrorInfo(
                category="gemini_api_error",
                message="Gemini calculation failed after multiple attempts.",
                http_status=502,
                technical_detail="No response received.",
                model=model_name,
            )
        )

    try:
        parsed = json.loads(_response_text(response))
    except json.JSONDecodeError as exc:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="gemini_api_error",
                message="Gemini returned a response that could not be parsed as JSON. Try again.",
                http_status=502,
                technical_detail=_response_text(response)[:500] if response else "",
                model=model_name,
            )
        ) from exc

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
        rule_label=_ruleset_label(billing_rule),
        total_units=total_units,
        codes=code_results,
        notes=str(parsed.get("notes", "")),
    )
