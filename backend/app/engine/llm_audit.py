import json
from typing import Any, Literal

from app.config import openai_model, load_env_files
from app.engine.llm_billing_rules import timing_rules_system_instructions
from app.engine.llm_errors import LlmAuditError, LlmErrorInfo
from app.engine.llm_billing_common import (
    build_billing_payload,
    call_openai_json_schema,
    ruleset_label,
)
from app.engine.llm_unit_core import calculator_raw_lines, run_llm_billing_calculation
from app.engine.loader import load_metadata

load_env_files()

SYSTEM_PROMPT = f"""You are a US healthcare billing compliance auditor for outpatient rehabilitation therapy (PT/OT/SLP).

Validate ONLY the billing summary JSON provided by the user.

{timing_rules_system_instructions()}

RULES:
- Use ONLY the billing summary data. Never infer, reconstruct, or reference any therapy transcript. Never mention a transcript.
- Apply the timing rule named in the input JSON "rule" field. Do not choose a different rule.
- Set rule_applied to exactly "Medicare 8-Minute" when the input rule is Medicare 8-Minute Rule, or "AMA Rule of 8" when the input rule is AMA Rule of Eight.
- For each line:
  - Calculate expected_units strictly from billing_rule and the supplied rule-specific metadata.
  - Do not fail an untimed or area-based line solely because duration_minutes is zero.
  - Require positive duration only for 8_minute_rule, full_block_required, and time_band_select.
  - Require area_sq_cm only when the area-based rule needs a threshold or increment.
  - If the CPT code is not recognized under the timing rules provided, mark status = FAILED with reasoning stating the code is unrecognized. Do not assume a rule for it.
  - Compare expected_units to engine_units. status = PASSED only if they match exactly.
  - On FAILED, reasoning must state the relevant input (duration, occurrence count, or area), rule applied, expected_units, and engine_units.
- overall_validation = FAILED if any line is FAILED or has a data issue, otherwise PASSED.
- auditor_notes: 1-2 sentences. Summarize only FAILED lines and systemic issues (e.g., repeated pattern of miscalculation, unrecognized codes). Leave brief if all PASSED.
- Every numeric field (expected_units, engine_units) must be a plain number — no strings, no ranges, no rounding symbols.
- Do not skip, merge, or omit any line from the input. Every input line must produce exactly one output line.
- If uncertain about any calculation, do not guess — mark that line FAILED with reasoning explaining the uncertainty.

Return ONLY valid JSON matching the required schema. No extra text, no commentary outside the JSON."""


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rule_applied": {
            "type": "string",
            "enum": ["Medicare 8-Minute", "AMA Rule of 8"],
        },
        "overall_validation": {
            "type": "string",
            "enum": ["PASSED", "FAILED"],
        },
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cpt": {"type": "string"},
                    "expected_units": {"type": "number"},
                    "engine_units": {"type": "number"},
                    "status": {
                        "type": "string",
                        "enum": ["PASSED", "FAILED"],
                    },
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "cpt",
                    "expected_units",
                    "engine_units",
                    "status",
                    "reasoning",
                ],
            },
        },
        "auditor_notes": {"type": "string"},
    },
    "required": ["rule_applied", "overall_validation", "lines", "auditor_notes"],
}


def _build_user_prompt(
    billing_summary: list[dict[str, Any]],
    billing_rule: str,
    store,
) -> str:
    raw_lines = [
        {
            "cpt": line["cpt"],
            "duration_minutes": line["duration_minutes"],
            "engine_units": line["engine_units"],
            "billing_rule": line.get("billing_rule"),
            "description": line.get("description", ""),
            "modifier": line.get("modifier"),
            "region": line.get("region", ""),
            "sequences": line.get("sequences", []),
            "occurrence_count": line.get("occurrence_count"),
            "area_sq_cm": line.get("area_sq_cm"),
        }
        for line in billing_summary
    ]
    payload = build_billing_payload(raw_lines, billing_rule, store)

    return (
        "Validate the following billing summary. Treat it as the single source of truth.\n"
        "Do not use or reference any therapy transcript.\n"
        "Apply the timing rule in the payload \"rule\" field only.\n"
        "Set rule_applied to \"Medicare 8-Minute\" or \"AMA Rule of 8\" to match that rule.\n"
        "Use timed_pool_minutes for Medicare pooling — untimed minutes must not enter the pool.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "For each line:\n"
        "- Apply its exact billing_rule using the rule-specific metadata in the payload.\n"
        "- Zero duration is valid for untimed and area-based rules.\n"
        "- Require positive duration only for 8_minute_rule, full_block_required, and time_band_select.\n"
        "- If the CPT is unrecognized under the ruleset, mark status FAILED and state that.\n"
        "- Compare expected_units to engine_units; status PASSED only on exact match. "
        "On FAILED, state relevant inputs, rule applied, expected_units, and engine_units.\n"
        "Every input line must produce exactly one output line — do not skip, merge, or omit.\n"
        "Set overall_validation FAILED if any line FAILED. "
        "Return rule_applied, overall_validation, per-line results, and concise auditor_notes."
    )


def _normalize_modifier(value: str | None) -> Literal["59"] | None:
    if value == "59":
        return "59"
    return None


def _normalize_audit_response(parsed: dict[str, Any]) -> dict[str, Any]:
    """Map LLM schema to the shape expected by the prototype comparison UI."""
    lines = parsed.get("lines") or []
    calculated_codes = [
        {
            "cpt": line["cpt"],
            "units": int(line.get("expected_units", 0)),
            "explanation": line.get("reasoning", ""),
        }
        for line in lines
    ]
    overall = parsed.get("overall_validation", "FAILED")

    return {
        "rule_applied": parsed.get("rule_applied", "Medicare 8-Minute"),
        "overall_validation": overall,
        "validation_status": overall,
        "total_billable_units": sum(code["units"] for code in calculated_codes),
        "calculated_codes": calculated_codes,
        "modifier_required": None,
        "auditor_notes": parsed.get("auditor_notes", ""),
        "summary_lines": lines,
    }


async def run_compliance_audit(
    billing_summary: list[dict[str, Any]],
    billing_rule: str,
) -> dict[str, Any]:
    if not billing_summary:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message="No billing summary lines to audit.",
                http_status=400,
                technical_detail="billing_summary is empty",
            )
        )

    store = load_metadata()
    model_name = openai_model()
    prompt = _build_user_prompt(billing_summary, billing_rule, store)

    try:
        parsed = await call_openai_json_schema(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            json_schema=RESPONSE_SCHEMA,
            failure_message="OpenAI audit failed after multiple attempts.",
        )
    except LlmAuditError:
        raise
    except json.JSONDecodeError as exc:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message="OpenAI returned a response that could not be parsed as JSON. Try again.",
                http_status=502,
                technical_detail=str(exc),
                model=model_name,
            )
        ) from exc

    normalized = _normalize_audit_response(parsed)
    normalized["modifier_required"] = _normalize_modifier(normalized.get("modifier_required"))
    return normalized


async def run_calculator_audit(
    rows: list[dict[str, Any]],
    billing_rule: str,
) -> dict[str, Any]:
    if not rows:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message="Add at least one CPT code before running verification.",
                http_status=400,
                technical_detail="rows is empty",
            )
        )

    store = load_metadata()
    parsed = await run_llm_billing_calculation(
        calculator_raw_lines(rows),
        billing_rule,
        mode="audit",
        store=store,
    )

    modifier = parsed.get("modifier_required")
    if modifier not in ("59", None):
        modifier = None

    return {
        **parsed,
        "modifier_required": modifier,
        "calculated_codes": [
            {**code, "cpt": str(code.get("cpt", "")).strip()}
            for code in parsed.get("calculated_codes", [])
        ],
    }


def build_summary_engine_snapshot(
    billing_summary: list[dict[str, Any]],
    billing_rule: str,
) -> dict[str, Any]:
    """Engine snapshot derived from billing summary assigned units (not transcript)."""
    codes = []
    for line in billing_summary:
        modifiers = [line["modifier"]] if line.get("modifier") else []
        codes.append(
            {
                "cpt": line["cpt"],
                "units": int(line["engine_units"]),
                "duration_minutes": line["duration_minutes"],
                "region": line.get("region", ""),
                "modifiers": modifiers,
            }
        )

    return {
        "billing_rule": billing_rule,
        "rule_label": ruleset_label(billing_rule),
        "total_units": sum(code["units"] for code in codes),
        "modifier_suggested": None,
        "codes": codes,
    }


def build_comparison(
    engine: dict[str, Any],
    llm: dict[str, Any],
) -> dict[str, Any]:
    engine_codes = {c["cpt"]: c for c in engine["codes"]}
    llm_codes = {c["cpt"]: c for c in llm.get("calculated_codes", [])}
    all_cpts = set(engine_codes) | set(llm_codes)

    engine_has_59 = engine.get("modifier_suggested") == "59" or any(
        "59" in (c.get("modifiers") or []) for c in engine["codes"]
    )
    llm_has_59 = llm.get("modifier_required") == "59"
    session_modifier_mismatch = engine_has_59 != llm_has_59

    rows = []
    for cpt in sorted(all_cpts):
        eng = engine_codes.get(cpt)
        llm_row = llm_codes.get(cpt)
        engine_units = eng["units"] if eng else None
        llm_units = llm_row["units"] if llm_row else None
        has_unit_mismatch = (
            engine_units is not None
            and llm_units is not None
            and engine_units != llm_units
        )
        rows.append(
            {
                "cpt": cpt,
                "engine_units": engine_units,
                "llm_units": llm_units,
                "engine_modifiers": (eng or {}).get("modifiers") or [],
                "region": (eng or {}).get("region") or "",
                "has_unit_mismatch": has_unit_mismatch,
                "has_modifier_mismatch": session_modifier_mismatch,
                "llm_explanation": (llm_row or {}).get("explanation"),
            }
        )

    total_mismatch = engine["total_units"] != llm.get("total_billable_units")

    return {
        "rows": rows,
        "total_mismatch": total_mismatch,
        "session_modifier_mismatch": session_modifier_mismatch,
        "matched": not total_mismatch and not session_modifier_mismatch
        and all(not r["has_unit_mismatch"] for r in rows),
    }
