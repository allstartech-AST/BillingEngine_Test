import json
from pathlib import Path

from app.engine.pipeline import evaluate_session
from app.models.input import BillingSessionInput

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stress_test_session.json"


def test_stress_session_segment_review_and_groups(store):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = evaluate_session(BillingSessionInput(**data), store)

    assert report.session_summary.evaluation_status == "needs_therapist_action"
    assert report.session_summary.total_timeline_minutes > 0
    assert report.session_summary.total_timed_minutes > 0
    assert report.session_summary.total_timeline_minutes <= 210
    assert len(report.segment_review) == 9
    assert len(report.conflict_groups) >= 2
    assert report.diagnosis_validation.ranked_icd10_codes[0] == "A18.01"
    assert report.diagnosis_validation.primary_icd10 == "A18.01"

    removed = {item.cpt_code for item in report.removed_codes}
    assert removed == {"97546", "97150", "97014"}

    overlap_segments = [
        item for item in report.segment_review if "temporal_overlap" in item.pending_reasons
    ]
    assert overlap_segments


def test_stress_session_primary_icd_override(store):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["primary_icd10"] = "G54.2"
    report = evaluate_session(BillingSessionInput(**data), store)

    assert report.diagnosis_validation.primary_icd10 == "G54.2"
    therapy = next(
        r for r in report.diagnosis_validation.per_cpt if r.cpt_code == "97110"
    )
    assert therapy.matched_icd == "G54.2"
    assert therapy.icd_selection_method == "primary"
