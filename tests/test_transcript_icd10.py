import json
from pathlib import Path

import pytest

from app.engine.loader import MetadataStore, reset_metadata_cache
from app.engine.transcript_medexa import (
    compute_transcript_confidence,
    validate_all_icd_transcript_support,
    validate_icd10_transcript_support,
)


@pytest.fixture
def icd_store(tmp_path):
    fixture = {
        "_meta": {"file": "test"},
        "M25.511": {
            "code": "M25.511",
            "label": "Pain in right shoulder",
            "trigger_phrases": ["pain in right shoulder", "right shoulder pain"],
            "required_context": ["pain", "complains of", "reported"],
            "exclude_if_present": ["plan to", "rule out"],
        },
    }
    path = tmp_path / "medexa_icd10_lookup.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    reset_metadata_cache()
    store = MetadataStore()
    store.medexa_icd10 = {k: v for k, v in fixture.items() if k != "_meta"}
    return store


def test_confidence_supported():
    score = compute_transcript_confidence(
        "supported", 1, ["pain in right shoulder"], ["pain"]
    )
    assert score == 83


def test_icd_supported(icd_store):
    transcript = "Patient reported pain in right shoulder during evaluation."
    result = validate_icd10_transcript_support("M25.511", transcript, icd_store)
    assert result.transcript_support == "supported"
    assert result.confidence_score is not None
    assert result.confidence_score >= 70


def test_icd_no_lookup(icd_store):
    result = validate_icd10_transcript_support("M54.50", "any", icd_store)
    assert result.transcript_support == "no_lookup"
    assert result.confidence_score is None


def test_icd_weak(icd_store):
    result = validate_icd10_transcript_support("M25.511", "We talked about the weather.", icd_store)
    assert result.transcript_support == "weak"
    assert result.confidence_score == 20
