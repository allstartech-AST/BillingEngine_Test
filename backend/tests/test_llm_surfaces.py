"""LLM surface separation — distinct auditors, not duplicate code paths."""

from __future__ import annotations

import inspect

from app.engine import llm_audit, summary_llm_validation
from app.engine.llm_billing_rules import (
    build_llm_billing_payload,
    timing_rules_system_instructions,
)
from app.engine.loader import load_metadata


def test_compliance_audit_prompt_compares_engine_units() -> None:
    prompt_source = inspect.getsource(llm_audit._build_user_prompt)
    assert "engine_units" in prompt_source
    audit_source = inspect.getsource(llm_audit.run_compliance_audit)
    assert "run_llm_billing_calculation" not in audit_source


def test_summary_validation_compares_summary_units() -> None:
    source = inspect.getsource(summary_llm_validation.validate_summary_units_llm)
    assert "summary_units" in source


def test_calculator_audit_uses_shared_unit_core() -> None:
    source = inspect.getsource(llm_audit.run_calculator_audit)
    assert "run_llm_billing_calculation" in source


def test_shared_prompt_covers_every_billing_rule() -> None:
    instructions = timing_rules_system_instructions()
    for rule in (
        "8_minute_rule",
        "full_block_required",
        "untimed_per_session",
        "untimed_per_encounter",
        "untimed_per_procedure",
        "untimed_per_day",
        "untimed_per_episode",
        "area_based",
        "time_band_select",
    ):
        assert rule in instructions
    assert "Zero duration is valid for untimed and area-based rules" in instructions


def test_llm_payload_includes_rule_specific_metadata() -> None:
    store = load_metadata()
    payload = build_llm_billing_payload(
        [
            {"cpt": "92607", "duration_minutes": 60},
            {"cpt": "97597", "duration_minutes": 0, "area_sq_cm": 20},
            {"cpt": "97598", "duration_minutes": 0, "area_sq_cm": 40},
        ],
        "cms_8_minute",
        "Medicare 8-Minute Rule",
        store,
    )
    by_cpt = {line["cpt"]: line for line in payload["billing_summary"]}
    assert by_cpt["92607"]["block_minutes"] == 60
    assert by_cpt["97597"]["area_threshold_sq_cm"] == 20
    assert by_cpt["97598"]["is_addon"] is True
    assert by_cpt["97598"]["increment_sq_cm"] == 20
