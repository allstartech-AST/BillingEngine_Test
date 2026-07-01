from app.engine.temporal_overlap import check_temporal_overlaps
from app.models.input import DetectedCptCode


def test_identical_window_is_error():
    segments = [
        DetectedCptCode(
            cpt_code="97014",
            sequence=15,
            timestamp_start="03:45:00",
            timestamp_end="04:00:00",
        ),
        DetectedCptCode(
            cpt_code="97032",
            sequence=14,
            timestamp_start="03:45:00",
            timestamp_end="04:00:00",
        ),
    ]
    issues, conflicts = check_temporal_overlaps(segments)
    assert any(i.severity == "error" for i in issues)
    assert any("Impossible billing window" in i.message for i in issues)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "overlap"
    assert set(conflicts[0].codes) == {"97014", "97032"}


def test_non_timed_cpt_still_checked():
    """97014 is not eight-minute-rule but must still be overlap-checked."""
    segments = [
        DetectedCptCode(
            cpt_code="97014",
            sequence=1,
            timestamp_start="00:10:00",
            timestamp_end="00:25:00",
        ),
        DetectedCptCode(
            cpt_code="97110",
            sequence=2,
            timestamp_start="00:15:00",
            timestamp_end="00:30:00",
        ),
    ]
    issues, conflicts = check_temporal_overlaps(segments)
    assert issues
    assert conflicts
