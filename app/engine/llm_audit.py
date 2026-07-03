import json
import asyncio
from typing import Any, Literal

from app.config import gemini_api_key, gemini_audit_model, load_env_files
from app.engine.gemini_errors import GeminiAuditError, GeminiErrorInfo, classify_gemini_error

load_env_files()

SYSTEM_PROMPT = """You are a US healthcare billing compliance auditor for outpatient rehabilitation therapy (PT/OT/SLP).

Your task is to validate ONLY the billing summary JSON provided by the user.

Rules:
- Use ONLY the billing summary data. Never infer, reconstruct, or reference any therapy transcript.
- Never mention a transcript in your response.
- Recalculate expected billable units from each line's documented duration_minutes.
- Apply the selected timing rule from the input: Medicare 8-Minute Rule (CMS pooled timed minutes) OR AMA Rule of Eight (per-code thresholds).
- For untimed codes, apply occurrence-based unit logic where appropriate.
- Compare your recalculated expected_units against the engine_units provided in each summary line.
- Mark each line PASSED when expected_units equals engine_units; otherwise FAILED with concise reasoning.
- Set overall_validation to FAILED if any line fails.

You MUST return ONLY valid JSON matching the required schema."""


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


def _ruleset_label(billing_rule: str) -> str:
    if billing_rule == "ama_rule_of_8":
        return "AMA Rule of Eight"
    return "Medicare 8-Minute Rule"


def _build_user_prompt(
    billing_summary: list[dict[str, Any]],
    billing_rule: str,
) -> str:
    payload = {
        "rule": _ruleset_label(billing_rule),
        "billing_summary": [
            {
                "cpt": line["cpt"],
                "description": line.get("description", ""),
                "duration_minutes": line["duration_minutes"],
                "engine_units": line["engine_units"],
                "modifier": line.get("modifier"),
                "region": line.get("region", ""),
            }
            for line in billing_summary
        ],
    }

    return (
        "Validate the following billing summary. Treat it as the single source of truth.\n"
        "Do not use or reference any therapy transcript.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Recalculate expected_units from each line's duration_minutes using the specified rule. "
        "Compare expected_units to engine_units for each CPT. "
        "Return per-line status, overall_validation, and concise auditor_notes."
    )


def _normalize_modifier(value: str | None) -> Literal["59"] | None:
    if value == "59":
        return "59"
    return None


def _normalize_audit_response(parsed: dict[str, Any]) -> dict[str, Any]:
    """Map Gemini schema to the shape expected by the prototype comparison UI."""
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
            message="Gemini returned an empty response. Try verification again.",
            http_status=502,
            technical_detail="No text content in Gemini response.",
            model=gemini_audit_model(),
        )
    )


_RETRYABLE_STATUS = {429, 503}
_MAX_ATTEMPTS = 3


async def run_compliance_audit(
    billing_summary: list[dict[str, Any]],
    billing_rule: str,
) -> dict[str, Any]:
    if not billing_summary:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="gemini_api_error",
                message="No billing summary lines to audit.",
                http_status=400,
                technical_detail="billing_summary is empty",
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
    prompt = _build_user_prompt(billing_summary, billing_rule)
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
                message="Gemini audit failed after multiple attempts.",
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

    normalized = _normalize_audit_response(parsed)
    normalized["modifier_required"] = _normalize_modifier(normalized.get("modifier_required"))
    return normalized


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
        "rule_label": _ruleset_label(billing_rule),
        "total_units": sum(code["units"] for code in codes),
        "modifier_suggested": None,
        "codes": codes,
    }


def build_engine_snapshot(
    cpt_lines: list[dict[str, Any]],
    total_units: int,
    billing_rule: str,
    modifier_suggested: str | None = None,
) -> dict[str, Any]:
    return {
        "billing_rule": billing_rule,
        "rule_label": _ruleset_label(billing_rule),
        "total_units": total_units,
        "modifier_suggested": modifier_suggested,
        "codes": cpt_lines,
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
        gem = llm_codes.get(cpt)
        engine_units = eng["units"] if eng else None
        llm_units = gem["units"] if gem else None
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
                "llm_explanation": (gem or {}).get("explanation"),
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
