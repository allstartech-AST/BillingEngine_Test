from app.engine.loader import MetadataStore
from app.engine.lookup_matcher import CPTMatcher
from app.models.output import Issue


def extract_summary_cpt_codes(summary: dict | None) -> tuple[set[str], int | None]:
    """Return CPT codes from billing_detection_summary and optional total count."""
    if not summary:
        return set(), None

    if "total_cpt_detected" in summary:
        total = summary.get("total_cpt_detected")
        try:
            count = int(total) if total is not None else None
        except (TypeError, ValueError):
            count = None
        return set(), count

    codes: set[str] = set()
    for key in summary:
        if key.startswith("_"):
            continue
        if isinstance(key, str) and key.isdigit() and len(key) == 5:
            codes.add(key)
    return codes, None


def reconcile_detection_summary(
    summary: dict | None,
    detected_cpts: set[str],
    transcript: str,
    store: MetadataStore,
) -> list[Issue]:
    """Compare upstream detection summary against authoritative segment CPTs."""
    if not summary:
        return []

    issues: list[Issue] = []
    summary_cpts, total_count = extract_summary_cpt_codes(summary)

    if summary_cpts:
        only_in_summary = summary_cpts - detected_cpts
        only_in_segments = detected_cpts - summary_cpts
        if only_in_summary:
            issues.append(
                Issue(
                    severity="warning",
                    message=(
                        "billing_detection_summary lists CPT(s) not present in "
                        f"detected_cpt_codes: {', '.join(sorted(only_in_summary))}. "
                        "Segments are authoritative; summary entries were not billed."
                    ),
                )
            )
        if only_in_segments:
            issues.append(
                Issue(
                    severity="warning",
                    message=(
                        "detected_cpt_codes includes CPT(s) missing from "
                        f"billing_detection_summary: {', '.join(sorted(only_in_segments))}."
                    ),
                )
            )

    if total_count is not None and total_count != len(detected_cpts):
        issues.append(
            Issue(
                severity="warning",
                message=(
                    f"billing_detection_summary total_cpt_detected={total_count} "
                    f"does not match {len(detected_cpts)} segment CPT(s)."
                ),
            )
        )

    if transcript.strip() and summary_cpts:
        try:
            matcher = CPTMatcher(lookup_dict=store.medexa)
            transcript_cpts = matcher.summarize(transcript)
            summary_not_in_transcript = summary_cpts - transcript_cpts
            if summary_not_in_transcript:
                issues.append(
                    Issue(
                        severity="info",
                        message=(
                            "Detection summary CPT(s) not strongly supported in "
                            f"transcript re-match: {', '.join(sorted(summary_not_in_transcript))}."
                        ),
                    )
                )
        except OSError:
            pass

    return issues
