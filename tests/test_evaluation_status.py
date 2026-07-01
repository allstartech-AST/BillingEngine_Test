from app.engine.evaluation_status import resolve_evaluation_status
from app.models.output import Issue


def test_ready_with_advisories_for_transcript_warning():
    status = resolve_evaluation_status(
        active_cpts={"97110"},
        detected_cpts={"97110"},
        pending_codes=[],
        therapist_actions_count=0,
        issues=[
            Issue(
                severity="warning",
                code="97110",
                message="Transcript does not strongly support billed CPT 97110.",
            )
        ],
    )
    assert status == "ready_with_advisories"


def test_needs_action_when_pending_codes():
    status = resolve_evaluation_status(
        active_cpts={"97110"},
        detected_cpts={"97110"},
        pending_codes=["97110"],
        therapist_actions_count=0,
        issues=[],
    )
    assert status == "needs_therapist_action"
