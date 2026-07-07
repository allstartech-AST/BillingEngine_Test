"""LLM surface separation — distinct auditors, not duplicate code paths."""

from __future__ import annotations

import inspect

from app.engine import llm_audit, summary_llm_validation


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
