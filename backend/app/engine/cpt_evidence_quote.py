"""Build CPT-specific transcript evidence quotes for detection logging."""

from __future__ import annotations

import re

from app.engine.loader import MetadataStore
from app.engine.lookup_matcher import MedexaLookupMatcher, build_index, find_phrase_span, tokenize

_MIN_QUOTE_WORDS = 5
_MAX_QUOTE_WORDS = 12
_MIN_SPECIFICITY_SCORE = 12

_GENERIC_QUOTE_PATTERNS = (
    r"\btake this object\b",
    r"\bplace it\b",
    r"\bthink about control\b",
    r"\brather than speed\b",
    r"\brepeat that reaching\b",
    r"\bsimulate a few daily\b",
    r"\bwalk you through how\b",
    r"\bquick look internally\b",
    r"\blook at the clip\b",
    r"\buse a scope briefly\b",
    r"\bwork directly on the joint\b",
)


def _normalize_for_search(text: str) -> str:
    text = text.lower().replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text.strip())
    return text


def _quote_in_transcript(quote: str, transcript: str) -> bool:
    quote_norm = _normalize_for_search(quote)
    transcript_norm = _normalize_for_search(transcript)
    if not quote_norm or not transcript_norm:
        return False
    if quote_norm in transcript_norm:
        return True

    quote_tokens = tokenize(quote_norm)
    if len(quote_tokens) < 3:
        return False

    for sentence in re.split(r"(?<=[.!?])\s+", transcript_norm):
        idx = build_index(sentence)
        span = find_phrase_span(idx, quote_norm, max_gap=2)
        if span is not None:
            return True
    return False


def _looks_generic(quote: str) -> bool:
    quote_norm = _normalize_for_search(quote)
    if not quote_norm:
        return True
    for pattern in _GENERIC_QUOTE_PATTERNS:
        if re.search(pattern, quote_norm):
            return True
    return False


def _trigger_overlap_score(cpt_code: str, quote: str, store: MetadataStore) -> int:
    entry = store.medexa.get(cpt_code) or {}
    triggers = entry.get("trigger_phrases") or []
    quote_norm = _normalize_for_search(quote)
    if not quote_norm:
        return 0

    score = 0
    for trigger in triggers:
        trigger_norm = _normalize_for_search(str(trigger))
        if not trigger_norm:
            continue
        if trigger_norm in quote_norm or quote_norm in trigger_norm:
            score += 10 + len(trigger_norm.split()) * 4 + len(trigger_norm)
        else:
            trigger_tokens = set(tokenize(trigger_norm))
            quote_tokens = set(tokenize(quote_norm))
            overlap = trigger_tokens & quote_tokens
            if len(overlap) >= 2:
                score += len(overlap) * 3

    label = _normalize_for_search(str(entry.get("label") or ""))
    for token in tokenize(quote_norm):
        if len(token) > 4 and token in label:
            score += 2

    return score


def _cross_code_ambiguity_penalty(quote: str, cpt_code: str, store: MetadataStore) -> int:
    quote_norm = _normalize_for_search(quote)
    penalty = 0
    for code, entry in store.medexa.items():
        if code == cpt_code or not store.knows_cpt(code):
            continue
        for trigger in entry.get("trigger_phrases") or []:
            trigger_norm = _normalize_for_search(str(trigger))
            if trigger_norm and (trigger_norm in quote_norm or quote_norm in trigger_norm):
                penalty += 6 + len(trigger_norm.split()) * 2
    return penalty


def _specificity_score(cpt_code: str, quote: str, store: MetadataStore) -> int:
    if not quote or _looks_generic(quote):
        return 0
    base = _trigger_overlap_score(cpt_code, quote, store)
    return max(0, base - _cross_code_ambiguity_penalty(quote, cpt_code, store))


def _expand_quote_window(sentence: str, matched_text: str) -> str:
    tokens = sentence.split()
    match_tokens = matched_text.split()
    if not tokens:
        return matched_text
    if not match_tokens:
        return matched_text

    start = None
    for index in range(len(tokens) - len(match_tokens) + 1):
        if tokens[index : index + len(match_tokens)] == match_tokens:
            start = index
            break
    if start is None:
        return matched_text

    end = start + len(match_tokens) - 1
    while (end - start + 1) < _MIN_QUOTE_WORDS:
        expanded = False
        if start > 0:
            start -= 1
            expanded = True
        if (end - start + 1) >= _MIN_QUOTE_WORDS:
            break
        if end < len(tokens) - 1:
            end += 1
            expanded = True
        if not expanded:
            break

    while (end - start + 1) > _MAX_QUOTE_WORDS and start < end:
        start += 1

    return " ".join(tokens[start : end + 1])


def _best_medexa_quote_window(cpt_code: str, transcript: str, store: MetadataStore) -> str:
    entry = store.medexa.get(cpt_code)
    if not entry or not transcript.strip():
        return ""

    matcher = MedexaLookupMatcher()
    matches = [match for match in matcher.match_entry(entry, transcript) if not match.excluded]
    if not matches:
        return ""

    best = max(
        matches,
        key=lambda match: (
            len(match.trigger_phrase.split()),
            len(match.matched_text.split()),
            len(match.trigger_phrase),
        ),
    )
    return _expand_quote_window(best.sentence, best.matched_text).strip()


def refine_cpt_evidence_quote(
    cpt_code: str,
    transcript: str,
    llm_quote: str,
    store: MetadataStore,
) -> str:
    """
    Prefer a transcript substring that contains Medexa trigger language for this CPT.

    Falls back to the LLM quote only when it is verbatim, non-generic, and CPT-specific.
    """
    llm_quote = str(llm_quote or "").strip()
    medexa_quote = _best_medexa_quote_window(cpt_code, transcript, store)

    llm_ok = bool(llm_quote) and _quote_in_transcript(llm_quote, transcript)
    llm_score = _specificity_score(cpt_code, llm_quote, store) if llm_ok else 0
    medexa_score = _specificity_score(cpt_code, medexa_quote, store) if medexa_quote else 0

    if medexa_quote and medexa_score >= max(llm_score, _MIN_SPECIFICITY_SCORE):
        return medexa_quote
    if llm_ok and llm_score >= _MIN_SPECIFICITY_SCORE:
        return llm_quote
    if medexa_quote:
        return medexa_quote
    if llm_ok and not _looks_generic(llm_quote):
        return llm_quote
    return medexa_quote or llm_quote


def refine_suggested_cpt_quotes(
    suggested: list[dict],
    transcript: str,
    store: MetadataStore,
) -> list[dict]:
    """Refine exact_quote on each suggested CPT using transcript + Medexa triggers."""
    refined: list[dict] = []
    for item in suggested:
        code = str(item.get("cpt_code") or "").strip()
        if not code:
            continue
        updated = dict(item)
        updated["exact_quote"] = refine_cpt_evidence_quote(
            code,
            transcript,
            str(item.get("exact_quote") or ""),
            store,
        )
        refined.append(updated)
    return refined
