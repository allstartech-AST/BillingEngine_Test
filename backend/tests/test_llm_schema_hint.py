"""Tests for compact LLM JSON shape hints."""

from app.engine.llm_cpt_tasks import CptVerificationResponse, SuggestedCptsResponse
from app.engine.llm_provider import _build_schema_instruction, _example_payload_for_model


def test_example_payload_for_suggested_cpts() -> None:
    example = _example_payload_for_model(SuggestedCptsResponse)
    assert "suggested_cpts" in example
    assert example["suggested_cpts"][0]["cpt_code"] == "string"
    assert "$defs" not in example


def test_schema_instruction_uses_example_not_defs() -> None:
    instruction = _build_schema_instruction(CptVerificationResponse)
    assert '"$defs"' not in instruction
    assert "is_supported" in instruction
    assert "Do not return a JSON schema" in instruction
