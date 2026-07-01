import re
from dataclasses import dataclass

from app.engine.loader import MetadataStore

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "on", "with",
    "by", "at", "from", "as", "is", "are", "was", "were", "be", "been",
    "1", "2", "3", "4", "5", "one", "two", "more", "areas", "area",
    "each", "per", "minute", "minutes", "session", "typically", "min",
    "initial", "add", "bill", "engine", "generated", "only",
}

_CLINICAL_SYNONYMS = {
    ("shoulder", "upper", "extremity"),
    ("knee", "lower", "extremity", "leg"),
    ("back", "spine", "lumbar", "lumbosacral"),
    ("neck", "cervical", "cervicothoracic"),
    ("hip", "pelvis", "pelvic"),
    ("hand", "wrist", "finger"),
    ("foot", "ankle", "toe"),
    ("pain", "ache", "discomfort"),
    ("therapy", "therapeutic", "rehabilitation", "rehab"),
    ("cognitive", "cognition", "memory", "executive", "dementia"),
    ("dementia", "vascular", "cerebrovascular"),
    ("stroke", "infarction", "sequelae", "hemiplegia"),
    ("exercise", "exercises", "strengthening", "flexibility"),
    ("manual", "mobilization", "manipulation"),
    ("functional", "activities", "adl"),
    ("stimulation", "electrical", "modality"),
    ("performance", "test", "measurement"),
}


def icd_code_variants(icd: str) -> list[str]:
    """Formatting variants for lookup in medexa/crosswalk (not clinical guessing)."""
    icd = icd.strip()
    variants = [icd]
    if "." in icd:
        base, dec = icd.split(".", 1)
        if dec and dec[-1] == "0" and len(dec) > 1:
            variants.append(f"{base}.{dec.rstrip('0')}")
        if len(dec) < 2:
            variants.append(f"{base}.{dec}0")
        if len(dec) == 1:
            variants.append(f"{base}.{dec}0")
    else:
        variants.append(f"{icd}.0")
    return list(dict.fromkeys(variants))


@dataclass
class SemanticMatchResult:
    icd_code: str | None
    icd_label: str | None
    cpt_semantic_text: str | None
    confidence: int
    review_reason: str | None  # no_icd_description | low_semantic_match


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def _expand_synonyms(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for group in _CLINICAL_SYNONYMS:
        group_set = set(group)
        if tokens & group_set:
            expanded |= group_set
    return expanded


def semantic_cpt_icd_confidence(cpt_description: str, icd_label: str) -> int:
    """Score clinical relevance between medexa CPT text and medexa ICD text (0–99)."""
    if not cpt_description.strip() or not icd_label.strip():
        return 0

    cpt_tokens = _expand_synonyms(_tokenize(cpt_description))
    icd_tokens = _expand_synonyms(_tokenize(icd_label))
    if not cpt_tokens or not icd_tokens:
        return 0

    overlap = cpt_tokens & icd_tokens
    if not overlap:
        return 0

    precision = len(overlap) / len(icd_tokens)
    recall = len(overlap) / len(cpt_tokens)
    score = int(round((0.6 * precision + 0.4 * recall) * 100))
    return min(99, max(1, score))


def cpt_semantic_text(cpt_code: str, store: MetadataStore) -> str:
    """Primary: medexa_cpt_lookup label/notes/triggers; fallback: cpt_general_info."""
    return store.medexa_cpt_semantic_text(cpt_code)


def icd_semantic_text(
    icd_code: str,
    store: MetadataStore,
    diagnosis_labels: dict[str, str] | None = None,
) -> str:
    """Primary: medexa_icd10_lookup label/body_parts; optional payload label override."""
    labels = diagnosis_labels or {}
    if icd_code in labels and labels[icd_code].strip():
        return labels[icd_code].strip()
    return store.medexa_icd_semantic_text(icd_code)


def best_semantic_icd_match(
    cpt_code: str,
    submitted_icds: list[str],
    store: MetadataStore,
    diagnosis_labels: dict[str, str] | None = None,
) -> SemanticMatchResult:
    cpt_text = cpt_semantic_text(cpt_code, store)
    if not submitted_icds:
        return SemanticMatchResult(None, None, cpt_text, 0, None)

    best_icd: str | None = None
    best_label: str | None = None
    best_score = -1
    best_rank = len(submitted_icds)
    any_icd_text = False

    for icd in submitted_icds:
        icd_text = icd_semantic_text(icd, store, diagnosis_labels)
        if not icd_text:
            continue
        any_icd_text = True
        score = semantic_cpt_icd_confidence(cpt_text, icd_text)
        rank = submitted_icds.index(icd)
        if score > best_score or (score == best_score and rank < best_rank):
            best_score = score
            best_rank = rank
            best_icd = icd
            best_label = icd_text

    if not any_icd_text:
        return SemanticMatchResult(
            icd_code=submitted_icds[0] if submitted_icds else None,
            icd_label=None,
            cpt_semantic_text=cpt_text,
            confidence=0,
            review_reason="no_icd_description",
        )

    if best_score == 0:
        display = (
            store.medexa_icd_display_label(best_icd or submitted_icds[0])
            if best_icd or submitted_icds
            else None
        )
        return SemanticMatchResult(
            icd_code=best_icd or submitted_icds[0],
            icd_label=display or best_label,
            cpt_semantic_text=cpt_text,
            confidence=0,
            review_reason="low_semantic_match",
        )

    display = store.medexa_icd_display_label(best_icd) if best_icd else None
    return SemanticMatchResult(
        icd_code=best_icd,
        icd_label=display or best_label,
        cpt_semantic_text=cpt_text,
        confidence=best_score,
        review_reason="low_semantic_match" if best_score < 100 else None,
    )


def build_icd_review_guidance(
    cpt_code: str,
    cpt_description: str,
    match: SemanticMatchResult,
    *,
    crosswalk_miss: bool,
    alternatives: list[str],
) -> tuple[str, str]:
    """Return (review_reason, guidance) for pending_icd_review."""
    if match.review_reason == "no_icd_description":
        icd_list = ", ".join(alternatives[:5]) if alternatives else "see crosswalk"
        desc_snip = cpt_description[:80] + ("…" if len(cpt_description) > 80 else "")
        return (
            "no_icd_description",
            (
                f"No medexa_icd10_lookup entry for submitted ICD(s) linked to {cpt_code} "
                f"({desc_snip}). Semantic scoring requires ICD labels in medexa_icd10_lookup.json. "
                f"Crosswalk-approved codes for this CPT include: {icd_list}."
            ),
        )

    icd_part = ""
    if match.icd_code and match.icd_label:
        icd_part = (
            f" Medexa semantic match: {match.icd_code} ↔ {cpt_code} "
            f"({match.confidence}/100)."
        )
    elif match.icd_code:
        icd_part = f" Best candidate ICD: {match.icd_code} — {match.confidence}/100."

    if crosswalk_miss:
        alt_preview = ", ".join(alternatives[:5])
        suffix = f" Crosswalk-approved examples: {alt_preview}." if alt_preview else ""
        if match.confidence == 0:
            return (
                "crosswalk_miss",
                (
                    f"Submitted ICD(s) are not on the CMS crosswalk for {cpt_code}. "
                    f"Medexa CPT/ICD semantic relevance could not be established.{icd_part}{suffix}"
                ),
            )
        return (
            "crosswalk_miss",
            (
                f"Submitted ICD(s) are not on the CMS crosswalk for {cpt_code}.{icd_part} "
                f"Therapist must confirm diagnosis supports this service.{suffix}"
            ),
        )

    return (
        "low_semantic_match",
        (
            f"Medexa semantic relevance between {cpt_code} and submitted ICD is uncertain "
            f"({match.confidence}/100).{icd_part} Therapist review required."
        ),
    )
