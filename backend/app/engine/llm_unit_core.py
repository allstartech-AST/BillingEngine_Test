"""Shared OpenAI unit calculation and calculator-audit core."""

from __future__ import annotations

import json
from typing import Any, Literal

from app.engine.llm_billing_common import (
    build_billing_payload,
    call_openai_json_schema,
)
from app.engine.llm_billing_rules import timing_rules_system_instructions
from app.engine.llm_errors import LlmAuditError, LlmErrorInfo
from app.engine.loader import MetadataStore, load_metadata

CALCULATE_SYSTEM_PROMPT = f"""You are an expert in US outpatient rehabilitation therapy (PT/OT/SLP) billing unit calculations.

Given CPT codes and durations in minutes, calculate billable units using ONLY the timing rule specified in the input.

{timing_rules_system_instructions()}

Do not validate against any billing engine, transcript, or patient summary.
Do not compare to pre-assigned units.
Only calculate units from the provided codes and minutes.

Return ONLY valid JSON matching the required schema."""

AUDIT_SYSTEM_PROMPT = f"""You are an expert US Healthcare Billing Compliance Auditor specializing in outpatient rehabilitation therapy (PT/OT/SLP) CPT coding.

Your role is to independently audit a proposed therapy session billing scenario using your regulatory knowledge — NOT any external lookup files or databases supplied by the user.

{timing_rules_system_instructions()}

Also evaluate:
- Medically Unlikely Edit (MUE) unit limits where relevant
- NCCI Procedure-to-Procedure (PTP) bundling edits and when modifier 59 (or X-modifiers) may bypass a bundling conflict
- Anatomical / body region context when codes are region-specific or when distinct procedural regions may justify modifier 59

You MUST return ONLY valid JSON matching the required schema.

If inputs are incomplete or ambiguous, set validation_status to FAILED and explain in auditor_notes."""

CALCULATE_RESPONSE_SCHEMA: dict[str, Any] = {
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

AUDIT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rule_applied": {
            "type": "string",
            "enum": ["Medicare 8-Minute", "AMA Rule of 8"],
        },
        "total_billable_units": {"type": "number"},
        "calculated_codes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cpt": {"type": "string"},
                    "units": {"type": "number"},
                    "explanation": {"type": "string"},
                },
                "required": ["cpt", "units", "explanation"],
            },
        },
        "modifier_required": {"type": ["string", "null"]},
        "validation_status": {
            "type": "string",
            "enum": ["PASSED", "FAILED"],
        },
        "auditor_notes": {"type": "string"},
    },
    "required": [
        "rule_applied",
        "total_billable_units",
        "calculated_codes",
        "modifier_required",
        "validation_status",
        "auditor_notes",
    ],
}


def calculator_raw_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cpt": row["cpt"],
            "minutes": row["duration_minutes"],
            "duration_minutes": row["duration_minutes"],
            "body_region": row.get("body_region") or "",
        }
        for row in rows
    ]


def unit_calc_raw_lines(codes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"cpt": code["cpt"], "minutes": code["minutes"], "duration_minutes": code["minutes"]}
        for code in codes
    ]


def build_calculate_user_prompt(
    raw_lines: list[dict[str, Any]],
    billing_rule: str,
    store: MetadataStore,
) -> str:
    payload = build_billing_payload(raw_lines, billing_rule, store)
    return (
        "Calculate billable units for the following CPT codes and durations. "
        "Use timed_pool_minutes for Medicare pooling (timed lines only).\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Apply the specified timing rule and return units per code plus total_units. "
        "total_units must sum timed-code units plus untimed occurrence units only."
    )


def build_audit_user_prompt(
    raw_lines: list[dict[str, Any]],
    billing_rule: str,
    store: MetadataStore,
) -> str:
    payload = build_billing_payload(raw_lines, billing_rule, store)
    return (
        "Audit the following therapy session billing scenario using your regulatory knowledge.\n\n"
        "Apply the timing rule in the payload \"rule\" field only.\n"
        "Pool minutes ONLY from timed codes for Medicare 8-Minute Rule — never add untimed minutes to the pool.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Calculate billable units per code and total_billable_units.\n"
        "Set validation_status to FAILED if inputs are incomplete, ambiguous, or a line cannot be calculated.\n"
        "Set modifier_required to \"59\" only when NCCI bundling clearly requires it; otherwise null.\n"
        "Put per-code validation and calculation notes in calculated_codes[].explanation.\n"
        "Add brief session-wide notes in auditor_notes."
    )


async def run_llm_billing_calculation(
    raw_lines: list[dict[str, Any]],
    billing_rule: str,
    *,
    mode: Literal["calculate", "audit"],
    store: MetadataStore | None = None,
) -> dict[str, Any]:
    if not raw_lines:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message=(
                    "Add at least one CPT code with a duration greater than 0."
                    if mode == "calculate"
                    else "Add at least one CPT code before running verification."
                ),
                http_status=400,
                technical_detail="rows is empty",
            )
        )

    metadata = store or load_metadata()
    if mode == "calculate":
        system_prompt = CALCULATE_SYSTEM_PROMPT
        user_prompt = build_calculate_user_prompt(raw_lines, billing_rule, metadata)
        json_schema = CALCULATE_RESPONSE_SCHEMA
    else:
        system_prompt = AUDIT_SYSTEM_PROMPT
        user_prompt = build_audit_user_prompt(raw_lines, billing_rule, metadata)
        json_schema = AUDIT_RESPONSE_SCHEMA

    return await call_openai_json_schema(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_schema=json_schema,
        failure_message="OpenAI audit failed after multiple attempts.",
    )
