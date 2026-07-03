from app.engine.lookup_matcher import LookupMatch, MedexaLookupMatcher
from app.engine.loader import MetadataStore
from app.models.output import TranscriptCptSupport, TranscriptIcdSupport

_MATCHER = MedexaLookupMatcher()


def compute_transcript_confidence(
    support: str,
    supporting_sentence_count: int,
    matched_phrases: list[str],
    matched_context: list[str],
) -> int | None:
    if support == "supported":
        base = 75 + 5 * len(matched_phrases) + 3 * len(matched_context)
        extra = max(0, supporting_sentence_count - 1) * 5
        return min(100, base + extra)
    if support == "weak":
        return 20
    if support == "suppressed":
        return 0
    return None


def _aggregate_entry_matches(matches: list[LookupMatch]) -> tuple[str, list[str], list[str], str | None, str]:
    if not matches:
        return (
            "weak",
            [],
            [],
            None,
            "No supporting clinical phrases found in transcript.",
        )

    supporting = [m for m in matches if not m.excluded]
    excluded = [m for m in matches if m.excluded]

    if supporting:
        phrases = list(dict.fromkeys(m.trigger_phrase for m in supporting))
        contexts = list(
            dict.fromkeys(
                m.context_word for m in supporting if m.context_word
            )
        )
        sentence_count = len({m.sentence_index for m in supporting})
        return (
            "supported",
            phrases,
            contexts,
            None,
            f"Transcript language supports this code ({sentence_count} sentence(s)).",
        )

    if excluded:
        ex = excluded[0]
        return (
            "suppressed",
            [ex.trigger_phrase],
            [],
            ex.exclusion_phrase,
            f"Phrase matched but suppressed by exclusion '{ex.exclusion_phrase}'.",
        )

    return (
        "weak",
        [],
        [],
        None,
        "No supporting clinical phrases found in transcript.",
    )


def _evaluate_medexa_entry(entry: dict, transcript: str) -> tuple[str, list[str], list[str], str | None, str, int]:
    triggers = entry.get("trigger_phrases") or []
    if not triggers:
        return (
            "not_applicable",
            [],
            [],
            None,
            "No trigger phrases configured for this lookup entry.",
            0,
        )

    matches = _MATCHER.match_entry(entry, transcript)
    support, phrases, contexts, suppressed_by, guidance = _aggregate_entry_matches(matches)
    sentence_count = len({m.sentence_index for m in matches if not m.excluded}) if matches else 0
    return support, phrases, contexts, suppressed_by, guidance, sentence_count


def validate_cpt_transcript_support(
    cpt_code: str,
    transcript: str,
    store: MetadataStore,
) -> TranscriptCptSupport:
    if not transcript.strip():
        return TranscriptCptSupport(
            cpt_code=cpt_code,
            transcript_support="weak",
            confidence_score=20,
            guidance="No transcript provided for documentation support check.",
        )

    entry = store.medexa.get(cpt_code)
    if not entry:
        return TranscriptCptSupport(
            cpt_code=cpt_code,
            transcript_support="no_lookup",
            guidance=f"No medexa lookup entry for {cpt_code}.",
        )

    support, phrases, contexts, suppressed_by, guidance, sentence_count = _evaluate_medexa_entry(
        entry, transcript
    )
    if support == "not_applicable":
        return TranscriptCptSupport(
            cpt_code=cpt_code,
            transcript_support="not_applicable",
            guidance="Code is not matched from speech per lookup metadata.",
        )

    return TranscriptCptSupport(
        cpt_code=cpt_code,
        transcript_support=support,  # type: ignore[arg-type]
        confidence_score=compute_transcript_confidence(
            support, sentence_count, phrases, contexts
        ),
        matched_phrases=phrases,
        matched_context=contexts,
        suppressed_by=suppressed_by,
        guidance=guidance,
    )


def validate_icd10_transcript_support(
    icd_code: str,
    transcript: str,
    store: MetadataStore,
    label: str | None = None,
) -> TranscriptIcdSupport:
    if not transcript.strip():
        return TranscriptIcdSupport(
            icd10_code=icd_code,
            label=label,
            transcript_support="weak",
            confidence_score=20,
            guidance="No transcript provided for diagnosis documentation check.",
        )

    entry = store.medexa_icd10.get(icd_code)
    if not entry:
        return TranscriptIcdSupport(
            icd10_code=icd_code,
            label=label,
            transcript_support="no_lookup",
            guidance=f"No medexa ICD lookup entry for {icd_code}.",
        )

    support, phrases, contexts, suppressed_by, guidance, sentence_count = _evaluate_medexa_entry(
        entry, transcript
    )
    return TranscriptIcdSupport(
        icd10_code=icd_code,
        label=label or entry.get("label"),
        transcript_support=support,  # type: ignore[arg-type]
        confidence_score=compute_transcript_confidence(
            support, sentence_count, phrases, contexts
        ),
        matched_phrases=phrases,
        matched_context=contexts,
        suppressed_by=suppressed_by,
        guidance=guidance,
    )


def validate_all_transcript_support(
    cpt_codes: list[str],
    transcript: str,
    store: MetadataStore,
) -> list[TranscriptCptSupport]:
    seen: set[str] = set()
    results: list[TranscriptCptSupport] = []
    for cpt in cpt_codes:
        if cpt in seen:
            continue
        seen.add(cpt)
        results.append(validate_cpt_transcript_support(cpt, transcript, store))
    return results


def validate_all_icd_transcript_support(
    icd_codes: list[str],
    transcript: str,
    store: MetadataStore,
    diagnosis_labels: dict[str, str] | None = None,
) -> list[TranscriptIcdSupport]:
    labels = diagnosis_labels or {}
    seen: set[str] = set()
    results: list[TranscriptIcdSupport] = []
    for icd in icd_codes:
        if icd in seen:
            continue
        seen.add(icd)
        results.append(
            validate_icd10_transcript_support(
                icd, transcript, store, label=labels.get(icd)
            )
        )
    return results


def icd_validation_status(
    icd_results: list[TranscriptIcdSupport], transcript: str
) -> str:
    if not transcript.strip():
        return "skipped"
    if not icd_results:
        return "skipped"
    if all(r.transcript_support == "no_lookup" for r in icd_results):
        return "partial"
    if any(r.transcript_support == "no_lookup" for r in icd_results):
        return "partial"
    return "complete"
