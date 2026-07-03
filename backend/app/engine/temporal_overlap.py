from app.engine.duration import segments_overlap
from app.models.input import DetectedCptCode
from app.models.output import BillingConflict, ConflictRecommendation, Issue


def _timestamps_identical(a: DetectedCptCode, b: DetectedCptCode) -> bool:
    return (
        a.timestamp_start.strip() == b.timestamp_start.strip()
        and a.timestamp_end.strip() == b.timestamp_end.strip()
    )


def check_temporal_overlaps(
    segments: list[DetectedCptCode],
) -> tuple[list[Issue], list[BillingConflict]]:
    """Detect overlapping segment timestamps across all CPT codes."""
    issues: list[Issue] = []
    conflicts: list[BillingConflict] = []
    seen: set[tuple[str, str, int, int]] = set()

    for i, a in enumerate(segments):
        for b in segments[i + 1 :]:
            key = (a.cpt_code, b.cpt_code, a.sequence, b.sequence)
            rev = (b.cpt_code, a.cpt_code, b.sequence, a.sequence)
            if key in seen or rev in seen:
                continue
            seen.add(key)

            try:
                overlaps = segments_overlap(
                    a.timestamp_start,
                    a.timestamp_end,
                    b.timestamp_start,
                    b.timestamp_end,
                )
            except ValueError:
                continue

            if not overlaps:
                continue

            identical = _timestamps_identical(a, b)
            severity = "error" if identical else "warning"
            window = f"{a.timestamp_start} - {a.timestamp_end}"
            if identical:
                detail = (
                    f"Impossible billing window: {a.cpt_code} (seq {a.sequence}) and "
                    f"{b.cpt_code} (seq {b.sequence}) share identical timestamps "
                    f"({window}). Two distinct services cannot occupy the same time block."
                )
            else:
                detail = (
                    f"Segment time overlap between {a.cpt_code} (seq {a.sequence}, "
                    f"{a.timestamp_start}-{a.timestamp_end}) and {b.cpt_code} "
                    f"(seq {b.sequence}, {b.timestamp_start}-{b.timestamp_end})."
                )

            issues.append(
                Issue(
                    severity=severity,  # type: ignore[arg-type]
                    code=a.cpt_code,
                    message=detail,
                )
            )

            conflict_id = f"overlap_{a.cpt_code}_{a.sequence}_{b.cpt_code}_{b.sequence}"
            recommendations = [
                ConflictRecommendation(
                    action="fix_timestamps",
                    summary=(
                        "Assign non-overlapping start/stop times that reflect when each "
                        "service was actually performed, or remove the code that was not "
                        "delivered in that window."
                    ),
                ),
            ]
            if identical:
                recommendations.append(
                    ConflictRecommendation(
                        action="remove_duplicate_window",
                        summary=(
                            f"Only one of {a.cpt_code} or {b.cpt_code} can be billed for "
                            f"{window}; verify which service occurred and remove the other."
                        ),
                    )
                )

            conflicts.append(
                BillingConflict(
                    conflict_id=conflict_id,
                    conflict_type="overlap",
                    codes=sorted({a.cpt_code, b.cpt_code}),
                    issue=detail,
                    recommendations=recommendations,
                )
            )

    return issues, conflicts
