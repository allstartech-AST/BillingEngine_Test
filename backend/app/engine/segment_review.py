from app.engine.duration import segment_duration_details, segments_overlap
from app.models.input import DetectedCptCode
from app.models.output import BillingConflict, SegmentOverlap, SegmentReview


def _parse_overlap_conflict_sequences(conflict_id: str) -> tuple[int, int] | None:
    if not conflict_id.startswith("overlap_"):
        return None
    parts = conflict_id[len("overlap_") :].split("_")
    if len(parts) < 4:
        return None
    try:
        return int(parts[1]), int(parts[3])
    except ValueError:
        return None


def _segment_conflict_ids(
    segment: DetectedCptCode,
    billing_conflicts: list[BillingConflict],
) -> list[str]:
    ids: list[str] = []
    for conflict in billing_conflicts:
        if conflict.conflict_type == "overlap":
            sequences = _parse_overlap_conflict_sequences(conflict.conflict_id)
            if sequences and segment.sequence in sequences:
                ids.append(conflict.conflict_id)
        elif segment.cpt_code in conflict.codes:
            ids.append(conflict.conflict_id)
    return ids


def _segment_overlaps(
    segment: DetectedCptCode,
    all_segments: list[DetectedCptCode],
) -> list[SegmentOverlap]:
    overlaps: list[SegmentOverlap] = []
    for other in all_segments:
        if other.sequence == segment.sequence:
            continue
        try:
            if not segments_overlap(
                segment.timestamp_start,
                segment.timestamp_end,
                other.timestamp_start,
                other.timestamp_end,
            ):
                continue
        except ValueError:
            continue

        identical = (
            segment.timestamp_start.strip() == other.timestamp_start.strip()
            and segment.timestamp_end.strip() == other.timestamp_end.strip()
        )
        overlaps.append(
            SegmentOverlap(
                sequence=other.sequence,
                cpt_code=other.cpt_code,
                overlap_type="identical" if identical else "partial",
            )
        )
    return overlaps


def build_segment_review(
    segments: list[DetectedCptCode],
    billing_conflicts: list[BillingConflict],
    *,
    active_cpts: set[str],
    removed_cpts: set[str],
    overlap_sequences: set[int],
    ncci_pending_cpts: set[str],
    icd_pending_cpts: set[str],
) -> list[SegmentReview]:
    """Per-segment review with overlap detail and linked conflict IDs."""
    reviews: list[SegmentReview] = []
    sorted_segments = sorted(segments, key=lambda item: item.sequence)

    for segment in sorted_segments:
        try:
            exact, billed = segment_duration_details(
                segment.timestamp_start,
                segment.timestamp_end,
            )
        except ValueError:
            exact, billed = 0.0, 0

        if segment.cpt_code in removed_cpts:
            status = "removed"
            pending_reasons: list[str] = []
        elif segment.cpt_code not in active_cpts:
            status = "removed"
            pending_reasons = []
        else:
            pending_reasons = []
            if segment.sequence in overlap_sequences:
                pending_reasons.append("temporal_overlap")
            if segment.cpt_code in ncci_pending_cpts:
                pending_reasons.append("ncci_bundling")
            if segment.cpt_code in icd_pending_cpts:
                pending_reasons.append("icd_medical_necessity")
            status = "pending_therapist_review" if pending_reasons else "confirmed"

        reviews.append(
            SegmentReview(
                sequence=segment.sequence,
                cpt_code=segment.cpt_code,
                timestamp_start=segment.timestamp_start,
                timestamp_end=segment.timestamp_end,
                duration_minutes_exact=round(exact, 2),
                duration_minutes_billed=billed,
                overlaps_with=_segment_overlaps(segment, sorted_segments),
                conflict_ids=_segment_conflict_ids(segment, billing_conflicts),
                billing_status=status,  # type: ignore[arg-type]
                pending_reasons=pending_reasons,
            )
        )

    return reviews


def overlap_pending_sequences(billing_conflicts: list[BillingConflict], active_cpts: set[str]) -> set[int]:
    """Sequences on active CPTs involved in overlap conflicts."""
    sequences: set[int] = set()
    for conflict in billing_conflicts:
        if conflict.conflict_type != "overlap":
            continue
        if not any(code in active_cpts for code in conflict.codes):
            continue
        parsed = _parse_overlap_conflict_sequences(conflict.conflict_id)
        if parsed:
            sequences.update(parsed)
    return sequences
