from app.config import PENDING_REVIEW_MESSAGE
from app.models.output import DiagnosisCptResult

REVIEW_REASON_LABELS = {
    "crosswalk_miss": "CMS crosswalk miss",
    "no_icd_description": "Missing ICD description",
    "low_semantic_match": "Low clinical relevance",
}

PENDING_REASON_LABELS = {
    "ncci_bundling": "NCCI bundling conflict",
    "icd_medical_necessity": "ICD medical necessity review",
    "temporal_overlap": "Overlapping segment times",
}


def build_pending_review(
    cpt_code: str,
    *,
    icd_pending: bool,
    ncci_pending: bool,
    overlap_pending: bool,
    diagnosis: DiagnosisCptResult | None,
) -> tuple[list[str], str]:
    """Build structured pending_reasons and a single clean status message."""
    reasons: list[str] = []
    lines: list[str] = []

    if overlap_pending:
        reasons.append("temporal_overlap")
        lines.append("Overlapping timestamps — assign distinct service times or remove duplicate window.")

    if ncci_pending:
        reasons.append("ncci_bundling")
        lines.append("NCCI bundling — confirm distinct services or apply modifier to Column 2.")

    if icd_pending:
        reasons.append("icd_medical_necessity")
        if diagnosis and diagnosis.guidance:
            lines.append(diagnosis.guidance)
        elif diagnosis and diagnosis.review_reason:
            label = REVIEW_REASON_LABELS.get(diagnosis.review_reason, diagnosis.review_reason)
            conf = diagnosis.semantic_confidence
            conf_txt = f" (score {conf}/100)" if conf is not None else ""
            lines.append(f"{label}{conf_txt} — therapist must confirm diagnosis supports {cpt_code}.")

    if not lines:
        return reasons, PENDING_REVIEW_MESSAGE

    if len(lines) == 1:
        return reasons, lines[0]

    return reasons, " | ".join(lines)
