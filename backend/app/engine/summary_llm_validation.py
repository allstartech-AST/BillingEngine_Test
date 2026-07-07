"""Independent OpenAI audit for summary unit validation."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import load_env_files
from app.engine.llm_billing_common import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    build_billing_payload,
    call_openai_json_schema,
    ruleset_label,
)
from app.engine.llm_billing_rules import timing_rules_system_instructions
from app.engine.llm_errors import LlmAuditError, LlmErrorInfo
from app.engine.loader import MetadataStore
from app.engine.summary_unit_validation import (
    SummaryValidateLine,
    SummaryValidateResponse,
    SummaryValidateRow,
)

load_env_files()

logger = logging.getLogger(__name__)

_RESPONSE_ATTEMPTS = 2

SYSTEM_PROMPT = f"""You are an independent US outpatient rehabilitation therapy billing auditor.

Your task is to verify a billing summary by independently calculating expected billable units.

{timing_rules_system_instructions()}

Additional rules:
- Use ONLY the billing summary JSON provided. Never reference a therapy transcript or external session data.
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
    store: MetadataStore,
) -> str:
    raw_lines = [
        {
            "cpt": line.cpt.strip(),
            "duration_minutes": line.duration_minutes,
            "summary_units": line.summary_units,
            "is_timed": line.is_timed,
        }
        for line in lines
    ]
    payload = build_billing_payload(raw_lines, billing_rule, store)
    return (
        "Independently audit the following billing summary. "
        "Calculate expected billable units and compare them to summary_units. "
        "Use timed_pool_minutes (timed lines only) for Medicare pooling — "
        "never include untimed line minutes in the pool.\n\n"
        f"{json.dumps(payload, indent=2)}"
    )


def _normalize_cpt(value: str) -> str:
    return str(value).strip()


def _status_passed(status: str) -> bool:
    normalized = str(status or "").strip().upper()
    return normalized in {"PASSED", "PASS", "OK", "SUCCESS"}


def _map_llm_lines(
    llm_lines: list[dict[str, Any]],
    lines: list[SummaryValidateLine],
) -> dict[str, dict[str, Any]]:
    line_map = {_normalize_cpt(line.cpt): line for line in lines}
    llm_by_cpt = {_normalize_cpt(item["cpt"]): item for item in llm_lines}

    if set(llm_by_cpt.keys()) == set(line_map.keys()):
        return llm_by_cpt

    if len(llm_lines) == len(lines):
        logger.warning(
            "OpenAI CPT codes %s did not match summary %s; using positional mapping.",
            sorted(llm_by_cpt.keys()),
            sorted(line_map.keys()),
        )
        return {
            _normalize_cpt(line.cpt): llm_lines[index]
            for index, line in enumerate(lines)
        }

    raise LlmAuditError(
        LlmErrorInfo(
            category="llm_api_error",
            message="OpenAI returned an incomplete validation response.",
            http_status=502,
            technical_detail=(
                f"Expected CPTs {sorted(line_map.keys())}, "
                f"got {sorted(llm_by_cpt.keys())}"
            ),
        )
    )


def _build_rows_from_llm(
    parsed: dict[str, Any],
    lines: list[SummaryValidateLine],
    store: MetadataStore,
) -> list[SummaryValidateRow]:
    llm_lines = parsed.get("lines") or []
    if not llm_lines:
        raise LlmAuditError(
            LlmErrorInfo(
                category="llm_api_error",
                message="OpenAI returned no validation rows.",
                http_status=502,
                technical_detail=str(parsed)[:500],
            )
        )

    llm_by_cpt = _map_llm_lines(llm_lines, lines)

    result_rows: list[SummaryValidateRow] = []
    for line in lines:
        cpt = _normalize_cpt(line.cpt)
        gem = llm_by_cpt[cpt]
        is_timed = line.is_timed if line.is_timed is not None else store.is_timed(cpt)
        duration_minutes = max(0, int(round(line.duration_minutes)))
        expected_units = int(round(float(gem.get("expected_units", 0))))
        summary_units = line.summary_units
        passed = _status_passed(gem.get("status", "")) and expected_units == summary_units

        if passed:
            message = (
                f"OpenAI: summary duration of {duration_minutes} minute"
                f"{'s' if duration_minutes != 1 else ''} supports {expected_units} unit"
                f"{'s' if expected_units != 1 else ''} — matches assigned units."
            )
        else:
            reasoning = str(gem.get("reasoning", "")).strip()
            message = (
                f"OpenAI: summary duration supports {expected_units} unit"
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


async def _call_openai(prompt: str) -> dict[str, Any]:
    return await call_openai_json_schema(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        json_schema=RESPONSE_SCHEMA,
        timeout=DEFAULT_LLM_TIMEOUT_SECONDS,
        missing_key_message="OpenAI API key is not configured.",
        failure_message="OpenAI validation failed after multiple attempts.",
        timeout_message="OpenAI validation timed out.",
    )


async def validate_summary_units_llm(
    lines: list[SummaryValidateLine],
    billing_rule: str,
    store: MetadataStore,
) -> SummaryValidateResponse:
    prompt = _build_user_prompt(lines, billing_rule, store)
    last_error: LlmAuditError | None = None

    for attempt in range(_RESPONSE_ATTEMPTS):
        try:
            parsed = await _call_openai(prompt)
            result_rows = _build_rows_from_llm(parsed, lines, store)
            overall = str(parsed.get("overall_validation", "FAILED")).upper()
            all_passed = overall in {"PASSED", "PASS"} and all(
                row.status == "PASSED" for row in result_rows
            )

            return SummaryValidateResponse(
                billing_rule=billing_rule,
                rule_label=ruleset_label(billing_rule),
                overall_status="PASSED" if all_passed else "FAILED",
                rows=result_rows,
                auditor="openai",
                fallback_message=None,
            )
        except LlmAuditError as exc:
            last_error = exc
            logger.warning(
                "OpenAI summary validation attempt %s failed (%s): %s",
                attempt + 1,
                exc.info.category,
                exc.info.technical_detail,
            )
            if attempt < _RESPONSE_ATTEMPTS - 1:
                await asyncio.sleep(1)
                continue
            raise

    raise last_error or LlmAuditError(
        LlmErrorInfo(
            category="llm_api_error",
            message="OpenAI validation failed.",
            http_status=502,
            technical_detail="No validation response after retries.",
        )
    )
