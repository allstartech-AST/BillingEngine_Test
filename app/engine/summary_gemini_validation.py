"""Independent Gemini audit for summary unit validation."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import gemini_api_key, gemini_audit_model, load_env_files
from app.engine.gemini_errors import GeminiAuditError, GeminiErrorInfo, classify_gemini_error
from app.engine.loader import MetadataStore
from app.engine.summary_unit_validation import (
    SummaryValidateLine,
    SummaryValidateResponse,
    SummaryValidateRow,
    _rule_label,
)

load_env_files()

logger = logging.getLogger(__name__)

GEMINI_TIMEOUT_SECONDS = 60
_MAX_ATTEMPTS = 3
_RESPONSE_ATTEMPTS = 2
_RETRYABLE_STATUS = {429, 503}

SYSTEM_PROMPT = """You are an independent US outpatient rehabilitation therapy billing auditor.

Your task is to verify a billing summary by independently calculating expected billable units.

Rules:
- Use ONLY the billing summary JSON provided. Never reference a therapy transcript or external session data.
- Apply the specified timing rule:
  - Medicare 8-Minute Rule: pool ALL timed treatment minutes, determine total billable units from the pooled total, then allocate units across timed CPT codes using CMS substantial-portion / remainder methodology. The sum of expected units must not exceed the total supported by pooled minutes.
  - AMA Rule of Eight: evaluate each timed CPT code on its own documented minutes (no pooling).
- For untimed codes, apply occurrence-based unit logic where appropriate.
- Compare your independently calculated expected_units against the summary_units supplied for each line.
- Mark each line PASSED when expected_units equals summary_units; otherwise FAILED with concise reasoning.
- Set overall_validation to FAILED if any line fails.

Return ONLY valid JSON matching the required schema."""


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
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
                    "status": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["cpt", "expected_units", "status", "reasoning"],
            },
        },
        "auditor_notes": {"type": "string"},
    },
    "required": ["overall_validation", "lines", "auditor_notes"],
}


def _build_user_prompt(
    lines: list[SummaryValidateLine],
    billing_rule: str,
) -> str:
    payload = {
        "rule": _rule_label(billing_rule),
        "billing_summary": [
            {
                "cpt": line.cpt.strip(),
                "duration_minutes": line.duration_minutes,
                "summary_units": line.summary_units,
            }
            for line in lines
        ],
    }
    return (
        "Independently audit the following billing summary. "
        "Calculate expected billable units and compare them to summary_units.\n\n"
        f"{json.dumps(payload, indent=2)}"
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
            message="Gemini returned an empty response.",
            http_status=502,
            technical_detail="No text content in Gemini response.",
            model=gemini_audit_model(),
        )
    )


def _normalize_cpt(value: str) -> str:
    return str(value).strip()


def _status_passed(status: str) -> bool:
    normalized = str(status or "").strip().upper()
    return normalized in {"PASSED", "PASS", "OK", "SUCCESS"}


def _map_gemini_lines(
    gemini_lines: list[dict[str, Any]],
    lines: list[SummaryValidateLine],
) -> dict[str, dict[str, Any]]:
    line_map = {_normalize_cpt(line.cpt): line for line in lines}
    gemini_by_cpt = {_normalize_cpt(item["cpt"]): item for item in gemini_lines}

    if set(gemini_by_cpt.keys()) == set(line_map.keys()):
        return gemini_by_cpt

    if len(gemini_lines) == len(lines):
        logger.warning(
            "Gemini CPT codes %s did not match summary %s; using positional mapping.",
            sorted(gemini_by_cpt.keys()),
            sorted(line_map.keys()),
        )
        return {
            _normalize_cpt(line.cpt): gemini_lines[index]
            for index, line in enumerate(lines)
        }

    raise GeminiAuditError(
        GeminiErrorInfo(
            category="gemini_api_error",
            message="Gemini returned an incomplete validation response.",
            http_status=502,
            technical_detail=(
                f"Expected CPTs {sorted(line_map.keys())}, "
                f"got {sorted(gemini_by_cpt.keys())}"
            ),
        )
    )


def _build_rows_from_gemini(
    parsed: dict[str, Any],
    lines: list[SummaryValidateLine],
    store: MetadataStore,
) -> list[SummaryValidateRow]:
    line_map = {_normalize_cpt(line.cpt): line for line in lines}
    gemini_lines = parsed.get("lines") or []
    if not gemini_lines:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="gemini_api_error",
                message="Gemini returned no validation rows.",
                http_status=502,
                technical_detail=str(parsed)[:500],
            )
        )

    gemini_by_cpt = _map_gemini_lines(gemini_lines, lines)

    result_rows: list[SummaryValidateRow] = []
    for line in lines:
        cpt = _normalize_cpt(line.cpt)
        gem = gemini_by_cpt[cpt]
        is_timed = line.is_timed if line.is_timed is not None else store.is_timed(cpt)
        duration_minutes = max(0, int(round(line.duration_minutes)))
        expected_units = int(round(float(gem.get("expected_units", 0))))
        summary_units = line.summary_units
        passed = _status_passed(gem.get("status", "")) and expected_units == summary_units

        if passed:
            message = (
                f"Gemini: summary duration of {duration_minutes} minute"
                f"{'s' if duration_minutes != 1 else ''} supports {expected_units} unit"
                f"{'s' if expected_units != 1 else ''} — matches assigned units."
            )
        else:
            reasoning = str(gem.get("reasoning", "")).strip()
            message = (
                f"Gemini: summary duration supports {expected_units} unit"
                f"{'s' if expected_units != 1 else ''}, but the generated summary assigned "
                f"{summary_units} unit{'s' if summary_units != 1 else ''}."
            )
            if reasoning:
                message += f" {reasoning}"

        result_rows.append(
            SummaryValidateRow(
                cpt=cpt,
                duration_minutes=duration_minutes,
                is_timed=is_timed,
                expected_units=expected_units,
                summary_units=summary_units,
                status="PASSED" if passed else "FAILED",
                message=message,
            )
        )

    return result_rows


async def _call_gemini(prompt: str) -> dict[str, Any]:
    api_key = gemini_api_key()
    if not api_key:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="missing_api_key",
                message="Gemini API key is not configured.",
                http_status=503,
                technical_detail="GEMINI_API_KEY is unset.",
            )
        )

    from google import genai
    from google.genai import types

    model_name = gemini_audit_model()
    client = genai.Client(api_key=api_key)
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
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                ),
                timeout=GEMINI_TIMEOUT_SECONDS,
            )
            last_error = None
            break
        except TimeoutError as exc:
            raise GeminiAuditError(
                GeminiErrorInfo(
                    category="timeout",
                    message="Gemini validation timed out.",
                    http_status=504,
                    technical_detail=f"Exceeded {GEMINI_TIMEOUT_SECONDS}s",
                    model=model_name,
                )
            ) from exc
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
                message="Gemini validation failed after multiple attempts.",
                http_status=502,
                technical_detail="No response received.",
                model=model_name,
            )
        )

    try:
        return json.loads(_response_text(response))
    except json.JSONDecodeError as exc:
        raise GeminiAuditError(
            GeminiErrorInfo(
                category="gemini_api_error",
                message="Gemini returned malformed JSON.",
                http_status=502,
                technical_detail=_response_text(response)[:500],
                model=model_name,
            )
        ) from exc


async def validate_summary_units_gemini(
    lines: list[SummaryValidateLine],
    billing_rule: str,
    store: MetadataStore,
) -> SummaryValidateResponse:
    prompt = _build_user_prompt(lines, billing_rule)
    last_error: GeminiAuditError | None = None

    for attempt in range(_RESPONSE_ATTEMPTS):
        try:
            parsed = await _call_gemini(prompt)
            result_rows = _build_rows_from_gemini(parsed, lines, store)
            overall = str(parsed.get("overall_validation", "FAILED")).upper()
            all_passed = overall in {"PASSED", "PASS"} and all(
                row.status == "PASSED" for row in result_rows
            )

            return SummaryValidateResponse(
                billing_rule=billing_rule,
                rule_label=_rule_label(billing_rule),
                overall_status="PASSED" if all_passed else "FAILED",
                rows=result_rows,
                auditor="gemini",
                fallback_message=None,
            )
        except GeminiAuditError as exc:
            last_error = exc
            logger.warning(
                "Gemini summary validation attempt %s failed (%s): %s",
                attempt + 1,
                exc.info.category,
                exc.info.technical_detail,
            )
            if attempt < _RESPONSE_ATTEMPTS - 1:
                await asyncio.sleep(1)
                continue
            raise

    raise last_error or GeminiAuditError(
        GeminiErrorInfo(
            category="gemini_api_error",
            message="Gemini validation failed.",
            http_status=502,
            technical_detail="No validation response after retries.",
        )
    )
