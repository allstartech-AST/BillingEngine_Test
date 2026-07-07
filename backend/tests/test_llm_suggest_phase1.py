"""Phase 1 suggest-missing transcript caps and compact KB."""

from __future__ import annotations

from app.config import (
    LLM_SENTENCES_PER_AI_BATCH,
    LLM_SUGGEST_CONTEXT_CHARS,
    LLM_SUGGEST_MAX_DELTA_CHARS,
    LLM_SUGGEST_MIN_DELTA_CHARS,
)
from app.engine.llm_kb import build_compact_medexa_reference
from app.engine.llm_suggest_transcript import (
    compose_suggest_transcript,
    suggest_segment_bounds,
)
from app.engine.realtime.handlers_session import SENTENCES_PER_AI_BATCH


def test_sentences_per_ai_batch_is_forty() -> None:
    assert SENTENCES_PER_AI_BATCH == 40
    assert LLM_SENTENCES_PER_AI_BATCH == 40


def test_context_chars_is_two_hundred() -> None:
    assert LLM_SUGGEST_CONTEXT_CHARS == 200


def test_compact_medexa_smaller_than_trigger_dictionary(store) -> None:
    compact = build_compact_medexa_reference(store)
    lines = []
    for code, entry in store.medexa.items():
        triggers = ", ".join(entry.get("trigger_phrases", []))
        lines.append(f"- {code}: {entry.get('label', '')} (Triggers: {triggers})")
    verbose = "--- ENTIRE MEDEXA CPT DICTIONARY ---\n" + "\n".join(lines)
    assert len(compact) < len(verbose)
    assert "--- ENTIRE MEDEXA CPT DICTIONARY ---" in compact


def test_compose_suggest_transcript_prior_context_capped() -> None:
    whole = ("a" * 250) + "NEW_SEGMENT"
    composed = compose_suggest_transcript(whole, 250, len(whole))
    assert composed.endswith("NEW_SEGMENT")
    assert len(composed.split("\n\n")[0]) <= LLM_SUGGEST_CONTEXT_CHARS


def test_suggest_segment_bounds_one_pass_for_typical_delta() -> None:
    whole = "x" * 2000
    bounds = suggest_segment_bounds(whole, 0)
    assert len(bounds) == 1
    assert bounds[0] == (0, 2000)


def test_suggest_segment_bounds_splits_large_delta() -> None:
    whole = "word " * 2000
    bounds = suggest_segment_bounds(whole, 0)
    assert len(bounds) >= 2
    assert bounds[0][0] == 0
    assert bounds[-1][1] == len(whole)
    for start, end in bounds:
        assert end - start <= LLM_SUGGEST_MAX_DELTA_CHARS + 50


def test_suggest_segment_bounds_waits_for_min_delta() -> None:
    short = "x" * 100
    assert suggest_segment_bounds(short, 0) == []
    enough = "x" * (LLM_SUGGEST_MIN_DELTA_CHARS + 1)
    assert len(suggest_segment_bounds(enough, 0)) == 1
