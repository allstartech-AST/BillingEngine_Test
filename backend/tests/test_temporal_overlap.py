"""Temporal overlap detection (batch segments with timestamps)."""

from __future__ import annotations

from app.engine.temporal_overlap import check_temporal_overlaps
from app.models.input import DetectedCptCode


def _seg(cpt: str, seq: int, start: str, end: str) -> DetectedCptCode:
    return DetectedCptCode(
        cpt_code=cpt,
        sequence=seq,
        timestamp_start=start,
        timestamp_end=end,
    )


def test_identical_timestamps_produce_overlap_conflict() -> None:
    segments = [
        _seg("97110", 1, "00:10:00", "00:25:00"),
        _seg("97140", 2, "00:10:00", "00:25:00"),
    ]
    issues, conflicts = check_temporal_overlaps(segments)
    assert issues
    assert conflicts
    assert conflicts[0].conflict_type == "overlap"
    assert issues[0].severity == "error"


def test_non_overlapping_segments_produce_no_conflict() -> None:
    segments = [
        _seg("97110", 1, "00:10:00", "00:25:00"),
        _seg("97140", 2, "00:30:00", "00:45:00"),
    ]
    issues, conflicts = check_temporal_overlaps(segments)
    assert not issues
    assert not conflicts
