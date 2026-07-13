"""Smoke tests for medexa_cpt_lookup.json v2.0.0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.engine.loader import load_metadata, reset_metadata_cache
from app.engine.llm_kb import build_compact_medexa_reference
from app.engine.transcript_medexa import validate_cpt_transcript_support

BACKEND = Path(__file__).resolve().parents[1]
LOOKUP = BACKEND / "data" / "medexa" / "medexa_cpt_lookup.json"
GENERAL = BACKEND / "data" / "billing" / "cpt_general_info.json"

LEGACY_V1_ONLY = {
    "0362T", "0373T", "97151", "97152", "97153", "97154", "97155", "97156", "97158",
}


@pytest.fixture(autouse=True)
def _fresh_metadata():
    reset_metadata_cache()
    yield
    reset_metadata_cache()


def test_medexa_v2_metadata_and_coverage():
    raw = json.loads(LOOKUP.read_text(encoding="utf-8"))
    assert raw["_meta"]["version"] == "2.0.0"
    codes = {k for k in raw if k != "_meta"}
    general = {e["cpt_code"] for e in json.loads(GENERAL.read_text(encoding="utf-8"))}
    assert codes == general
    assert len(codes) == 98
    assert not (codes & LEGACY_V1_ONLY)


def test_loader_medexa_matches_billing_scope():
    store = load_metadata()
    assert len(store.medexa) == 98
    assert store.medexa["90901"]["label"].startswith("Biofeedback")
    assert "97151" not in store.medexa
    assert store.knows_cpt("90901")
    assert not store.knows_cpt("97151")


def test_phrase_match_new_v2_codes():
    store = load_metadata()
    biofeedback = validate_cpt_transcript_support(
        "90901",
        "We worked on biofeedback training for stress management today.",
        store,
    )
    assert biofeedback.transcript_support == "supported"

    swallow = validate_cpt_transcript_support(
        "92526",
        "Therapist worked on swallowing treatment and oral feeding today.",
        store,
    )
    assert swallow.transcript_support == "supported"


def test_llm_compact_reference_billable_only():
    store = load_metadata()
    ref = build_compact_medexa_reference(store)
    assert "90901:" in ref
    assert "97151:" not in ref
    assert len([line for line in ref.splitlines() if line.startswith("- ")]) == 98
