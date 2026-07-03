import re

from app.config import ICD_ALTERNATIVES_CAP
from app.engine.icd_semantic import (
    best_semantic_icd_match,
    build_icd_review_guidance,
    cpt_semantic_text,
    icd_code_variants,
    icd_semantic_text,
    semantic_cpt_icd_confidence,
)
from app.engine.loader import MetadataStore
from app.models.output import DiagnosisCptResult

ICD10_PATTERN = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?$")
_ICD_KEY_ORDER = re.compile(r"^icd[_-]?\d+$", re.I)
_ICD_KEY_NUM = re.compile(r"^icd[_-]?(\d+)$", re.I)


def _looks_like_icd10(value: str) -> bool:
    return bool(ICD10_PATTERN.match(value.strip()))


def _diagnosis_sort_key(key: str, index: int) -> tuple[int, int]:
    match = _ICD_KEY_NUM.match(key.strip())
    if match:
        return (0, int(match.group(1)))
    return (1, index)


def extract_icd_codes_ranked(diagnoses: dict[str, str]) -> list[str]:
    """Preserve submission order (icd_1 before icd_2, then other keys)."""
    items = list(diagnoses.items())
    ordered = sorted(
        enumerate(items),
        key=lambda pair: _diagnosis_sort_key(pair[1][0], pair[0]),
    )
    seen: set[str] = set()
    codes: list[str] = []
    for _, (key, value) in ordered:
        key = (key or "").strip()
        value = (value or "").strip()
        candidates: list[str] = []
        if _looks_like_icd10(key):
            candidates.append(key)
        if _looks_like_icd10(value):
            candidates.append(value)
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                codes.append(candidate)
                break
    return codes


def extract_icd_codes(diagnoses: dict[str, str]) -> list[str]:
    """Alphabetical list for backward-compatible consumers."""
    return sorted(extract_icd_codes_ranked(diagnoses))


def resolve_ranked_icd(matched_icd: str, ranked_icds: list[str]) -> str | None:
    """Map a matched ICD code to the claim's ranked diagnosis key (handles format variants)."""
    matched = matched_icd.strip()
    if matched in ranked_icds:
        return matched
    matched_variants = set(icd_code_variants(matched))
    for icd in ranked_icds:
        if icd in matched_variants or matched_variants & set(icd_code_variants(icd)):
            return icd
    return None


def resolve_primary_icd(
    ranked_icds: list[str],
    explicit_primary: str | None,
) -> str | None:
    if explicit_primary and explicit_primary.strip():
        primary = explicit_primary.strip()
        if primary in ranked_icds:
            return primary
        for icd in ranked_icds:
            if icd in icd_code_variants(primary) or primary in icd_code_variants(icd):
                return icd
    return ranked_icds[0] if ranked_icds else None


def _icd_in_crosswalk(icd: str, valid_set: set[str]) -> bool:
    if icd in valid_set:
        return True
    return any(variant in valid_set for variant in icd_code_variants(icd))


def _crosswalk_eligible_on_claim(ranked_icds: list[str], valid_set: set[str]) -> list[str]:
    return [icd for icd in ranked_icds if _icd_in_crosswalk(icd, valid_set)]


def _select_crosswalk_icd(
    cpt_code: str,
    eligible: list[str],
    ranked_icds: list[str],
    primary_icd: str | None,
    store: MetadataStore,
    diagnosis_labels: dict[str, str],
) -> tuple[str, str, list[str]]:
    """Pick best crosswalk-eligible ICD on the claim; return (icd, method, alternatives)."""
    if not eligible:
        raise ValueError("eligible must not be empty")

    if primary_icd and primary_icd in eligible:
        alts = [icd for icd in eligible if icd != primary_icd]
        return primary_icd, "primary", alts

    if len(eligible) == 1:
        return eligible[0], "single_crosswalk", []

    cpt_text = cpt_semantic_text(cpt_code, store)
    scored: list[tuple[int, int, str]] = []
    for icd in eligible:
        score = semantic_cpt_icd_confidence(
            cpt_text,
            icd_semantic_text(icd, store, diagnosis_labels),
        )
        rank = ranked_icds.index(icd) if icd in ranked_icds else len(ranked_icds)
        scored.append((score, -rank, icd))

    scored.sort(reverse=True)
    best = scored[0][2]
    alts = [item[2] for item in scored[1:]]
    method = "semantic_ranked" if scored[0][0] > 0 else "ranked_crosswalk"
    return best, method, alts


def _append_pending_result(
    results: list[DiagnosisCptResult],
    pending_cpts: set[str],
    *,
    cpt_code: str,
    match,
    crosswalk_miss: bool,
    alternatives: list[str],
    store: MetadataStore,
) -> None:
    reason, guidance = build_icd_review_guidance(
        cpt_code,
        cpt_semantic_text(cpt_code, store),
        match,
        crosswalk_miss=crosswalk_miss,
        alternatives=alternatives,
    )
    results.append(
        DiagnosisCptResult(
            cpt_code=cpt_code,
            medical_necessity="pending_icd_review",
            matched_icd=match.icd_code,
            matched_icd_label=match.icd_label,
            valid_icd10_alternatives=alternatives,
            semantic_confidence=match.confidence if match.confidence else None,
            review_reason=reason,  # type: ignore[arg-type]
            guidance=guidance,
            auto_removed=False,
        )
    )
    pending_cpts.add(cpt_code)


def validate_medical_necessity(
    cpt_codes: set[str],
    ranked_icds: list[str],
    store: MetadataStore,
    diagnosis_labels: dict[str, str] | None = None,
    primary_icd: str | None = None,
) -> tuple[list[DiagnosisCptResult], set[str]]:
    """Validate CPT↔ICD medical necessity with ranked and primary ICD selection."""
    results: list[DiagnosisCptResult] = []
    pending_cpts: set[str] = set()
    labels = diagnosis_labels or {}
    resolved_primary = resolve_primary_icd(ranked_icds, primary_icd)

    for cpt in sorted(cpt_codes):
        valid_set = store.icd10.get(cpt)

        if valid_set is None:
            results.append(
                DiagnosisCptResult(
                    cpt_code=cpt,
                    medical_necessity="valid_no_crosswalk",
                    guidance="No CMS ICD-10 crosswalk entry for this CPT; medical necessity not auto-checked.",
                    auto_removed=False,
                )
            )
            continue

        if not valid_set:
            match = best_semantic_icd_match(cpt, ranked_icds, store, labels)
            if match.confidence >= 100:
                results.append(
                    DiagnosisCptResult(
                        cpt_code=cpt,
                        medical_necessity="valid",
                        matched_icd=match.icd_code,
                        matched_icd_label=match.icd_label,
                        semantic_confidence=match.confidence,
                        icd_selection_method="semantic_ranked",
                        auto_removed=False,
                    )
                )
            else:
                _append_pending_result(
                    results,
                    pending_cpts,
                    cpt_code=cpt,
                    match=match,
                    crosswalk_miss=False,
                    alternatives=[],
                    store=store,
                )
            continue

        eligible = _crosswalk_eligible_on_claim(ranked_icds, valid_set)
        if eligible:
            matched, method, alts_on_claim = _select_crosswalk_icd(
                cpt,
                eligible,
                ranked_icds,
                resolved_primary if resolved_primary in eligible else None,
                store,
                labels,
            )
            label = store.medexa_icd_display_label(matched) or None
            cpt_text = cpt_semantic_text(cpt, store)
            semantic = semantic_cpt_icd_confidence(
                cpt_text,
                icd_semantic_text(matched, store, labels),
            )
            guidance = f"Detected ICD {matched} is on the CMS crosswalk for {cpt}."
            if alts_on_claim:
                alt_labels = ", ".join(alts_on_claim[:3])
                guidance += (
                    f" Selected by {method.replace('_', ' ')}"
                    f" (other crosswalk-eligible on claim: {alt_labels})."
                )
            if (
                resolved_primary
                and resolved_primary not in eligible
                and resolved_primary in ranked_icds
            ):
                guidance += (
                    f" Primary diagnosis {resolved_primary} is not on the crosswalk for {cpt}."
                )
            results.append(
                DiagnosisCptResult(
                    cpt_code=cpt,
                    medical_necessity="valid",
                    matched_icd=matched,
                    matched_icd_label=label,
                    alternative_icds_on_claim=alts_on_claim,
                    icd_selection_method=method,  # type: ignore[arg-type]
                    semantic_confidence=semantic if semantic else 100,
                    guidance=guidance,
                    auto_removed=False,
                )
            )
            continue

        match = best_semantic_icd_match(cpt, ranked_icds, store, labels)
        alternatives = sorted(valid_set)[:ICD_ALTERNATIVES_CAP]
        if match.confidence >= 100:
            results.append(
                DiagnosisCptResult(
                    cpt_code=cpt,
                    medical_necessity="valid",
                    matched_icd=match.icd_code,
                    matched_icd_label=match.icd_label,
                    valid_icd10_alternatives=alternatives,
                    semantic_confidence=match.confidence,
                    icd_selection_method="semantic_ranked",
                    auto_removed=False,
                )
            )
        else:
            _append_pending_result(
                results,
                pending_cpts,
                cpt_code=cpt,
                match=match,
                crosswalk_miss=True,
                alternatives=alternatives,
                store=store,
            )

    return results, pending_cpts
