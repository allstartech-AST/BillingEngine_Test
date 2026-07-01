from app.engine.pipeline import evaluate_session
from app.models.input import BillingSessionInput, ClientInfo, DetectedCptCode, SessionMetadata


def test_bypassable_marks_pending(store):
    payload = BillingSessionInput(
        client_info=ClientInfo(client_name="Alice Williams", client_id="PT-33012"),
        session_metadata=SessionMetadata(
            session_start="2026-06-29T10:00:00Z",
            session_end="2026-06-29T11:30:00Z",
        ),
        diagnoses={
            "M25.511": "Pain in right shoulder",
            "M25.561": "Pain in right knee",
            "M54.50": "Low back pain",
        },
        detected_cpt_codes=[
            DetectedCptCode(cpt_code="97110", sequence=1, timestamp_start="2026-06-29T10:05:00Z", timestamp_end="2026-06-29T10:20:00Z"),
            DetectedCptCode(cpt_code="97116", sequence=2, timestamp_start="2026-06-29T10:20:00Z", timestamp_end="2026-06-29T10:35:00Z"),
            DetectedCptCode(cpt_code="97112", sequence=3, timestamp_start="2026-06-29T10:35:00Z", timestamp_end="2026-06-29T10:50:00Z"),
            DetectedCptCode(cpt_code="97530", sequence=4, timestamp_start="2026-06-29T10:50:00Z", timestamp_end="2026-06-29T11:05:00Z"),
            DetectedCptCode(cpt_code="97140", sequence=5, timestamp_start="2026-06-29T11:05:00Z", timestamp_end="2026-06-29T11:20:00Z"),
        ],
        whole_transcript="We did therapeutic exercises working on shoulder strengthening today.",
    )
    report = evaluate_session(payload, store)
    pending = {c.cpt_code for c in report.billable_codes if c.billing_status == "pending_therapist_review"}
    confirmed = {c.cpt_code for c in report.billable_codes if c.billing_status == "confirmed"}
    assert "97530" in pending
    assert "97140" in pending
    assert "97116" in pending
    assert "97110" in confirmed
    assert "97112" in confirmed
    assert report.pending_authorization_codes
    assert report.human_summary.narrative
    for c in report.billable_codes:
        if c.billing_status == "pending_therapist_review":
            assert c.units_status_message
