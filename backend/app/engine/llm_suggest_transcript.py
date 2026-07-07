"""Transcript window helpers for live suggest-missing LLM calls."""

from __future__ import annotations

import re

from app.config import (
    LLM_SUGGEST_CONTEXT_CHARS,
    LLM_SUGGEST_MAX_DELTA_CHARS,
    LLM_SUGGEST_MIN_DELTA_CHARS,
)
from app.engine.loader import MetadataStore


def compose_suggest_transcript(whole_transcript: str, seg_start: int, seg_end: int) -> str:
    """Prior context (capped) plus new segment for the Transcript block."""
    prior_start = max(0, seg_start - LLM_SUGGEST_CONTEXT_CHARS)
    prior = whole_transcript[prior_start:seg_start].strip()
    delta = whole_transcript[seg_start:seg_end]
    if prior:
        return f"{prior}\n\n{delta}"
    return delta


def suggest_segment_bounds(
    whole_transcript: str,
    current_pointer: int,
) -> list[tuple[int, int]]:
    """Chunk unprocessed transcript into delta windows (max LLM_SUGGEST_MAX_DELTA_CHARS each)."""
    if len(whole_transcript) <= current_pointer + LLM_SUGGEST_MIN_DELTA_CHARS:
        return []

    bounds: list[tuple[int, int]] = []
    seg_start = current_pointer
    transcript_len = len(whole_transcript)

    while seg_start < transcript_len:
        if transcript_len - seg_start <= LLM_SUGGEST_MIN_DELTA_CHARS and bounds:
            break

        seg_end = min(seg_start + LLM_SUGGEST_MAX_DELTA_CHARS, transcript_len)
        if seg_end < transcript_len:
            space_index = whole_transcript.find(" ", seg_end)
            if space_index != -1 and space_index < seg_end + 50:
                seg_end = space_index + 1

        if seg_end <= seg_start:
            seg_end = transcript_len

        bounds.append((seg_start, seg_end))
        seg_start = seg_end

        if transcript_len - seg_start < LLM_SUGGEST_MIN_DELTA_CHARS:
            break

    return bounds


def lexical_hints_for_segment(
    segment: str,
    store: MetadataStore,
    existing_cpts: set[str],
) -> list[str]:
    """Non-exhaustive lexical hints for the segment (supplement only; LLM still analyzes text)."""
    if not segment.strip():
        return []

    from app.engine.transcript_medexa import validate_cpt_transcript_support

    words = set(re.findall(r"\b[a-z0-9]+\b", segment.lower()))
    candidates: set[str] = set()
    for word in words:
        candidates.update(store.cpt_keyword_index.get(word, set()))

    hints: list[str] = []
    seen: set[str] = set()
    for cpt in sorted(candidates):
        if cpt in existing_cpts or cpt not in store.medexa or cpt in seen:
            continue
        seen.add(cpt)
        support = validate_cpt_transcript_support(cpt, segment, store)
        if support.transcript_support == "supported" and support.matched_phrases:
            phrase = support.matched_phrases[0]
            hints.append(f"- {cpt}: matched \"{phrase}\"")
        elif support.confidence_score and support.confidence_score >= 50:
            hints.append(f"- {cpt}: {support.guidance}")

    return hints
