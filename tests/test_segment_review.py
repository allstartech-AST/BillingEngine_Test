from app.engine.segment_review import build_segment_review, overlap_pending_sequences
from app.models.input import DetectedCptCode
from app.models.output import BillingConflict, ConflictRecommendation


def test_segment_review_flags_overlap_sequence():
    segments = [
        DetectedCptCode(cpt_code="97012", sequence=7, timestamp_start="02:30:00", timestamp_end="03:00:00"),
        DetectedCptCode(cpt_code="97110", sequence=9, timestamp_start="02:30:00", timestamp_end="03:30:00"),
    ]
    conflicts = [
        BillingConflict(
            conflict_id="overlap_97012_7_97110_9",
            conflict_type="overlap",
            codes=["97012", "97110"],
            issue="overlap",
            recommendations=[ConflictRecommendation(action="fix_timestamps", summary="fix")],
        )
    ]
    active = {"97012", "97110"}
    overlap_seqs = overlap_pending_sequences(conflicts, active)
    assert overlap_seqs == {7, 9}

    review = build_segment_review(
        segments,
        conflicts,
        active_cpts=active,
        removed_cpts=set(),
        overlap_sequences=overlap_seqs,
        ncci_pending_cpts=set(),
        icd_pending_cpts=set(),
    )
    by_seq = {item.sequence: item for item in review}
    assert by_seq[9].billing_status == "pending_therapist_review"
    assert "temporal_overlap" in by_seq[9].pending_reasons
    assert len(by_seq[9].overlaps_with) == 1
    assert by_seq[9].overlaps_with[0].cpt_code == "97012"
