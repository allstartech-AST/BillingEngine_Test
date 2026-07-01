from app.engine.pipeline import evaluate_session
from app.models.input import BillingSessionInput, ClientInfo, DetectedCptCode, SessionMetadata


def _base_payload(**overrides):
    data = {
        "client_info": ClientInfo(client_name="John Doe", client_id="PT-99482"),
        "session_metadata": SessionMetadata(
            session_start="2026-06-29T10:00:00Z",
            session_end="2026-06-29T10:45:00Z",
        ),
        "diagnoses": {"icd_1": "M54.50"},
        "detected_cpt_codes": [],
        "whole_transcript": "",
    }
    data.update(overrides)
    return BillingSessionInput(**data)


def test_spec_example_icd_failure(store):
    payload = _base_payload(
        detected_cpt_codes=[
            DetectedCptCode(
                cpt_code="97168",
                sequence=1,
                timestamp_start="00:02:15",
                timestamp_end="00:15:30",
            ),
            DetectedCptCode(
                cpt_code="97110",
                sequence=2,
                timestamp_start="00:16:00",
                timestamp_end="00:42:15",
            ),
        ]
    )
    report = evaluate_session(payload, store)
    assert report.diagnosis_validation.status in ("issues_found", "blocked")
    pending_icd = {
        r.cpt_code
        for r in report.diagnosis_validation.per_cpt
        if r.medical_necessity == "pending_icd_review"
    }
    assert "97168" in pending_icd
    assert any(
        r.cpt_code == "97168" and r.medical_necessity == "pending_icd_review"
        for r in report.diagnosis_validation.per_cpt
    )
    assert any(c.cpt_code == "97110" for c in report.billable_codes)


def test_unknown_cpt(store):
    payload = _base_payload(
        diagnoses={"icd_1": "M50.01"},
        detected_cpt_codes=[
            DetectedCptCode(
                cpt_code="XXXXX",
                sequence=1,
                timestamp_start="00:00:00",
                timestamp_end="00:10:00",
            )
        ],
    )
    report = evaluate_session(payload, store)
    assert any(r.reason == "unknown_code" for r in report.removed_codes)


def test_weak_transcript_does_not_remove(store):
    payload = _base_payload(
        diagnoses={"icd_1": "S23.121S"},
        detected_cpt_codes=[
            DetectedCptCode(
                cpt_code="97110",
                sequence=1,
                timestamp_start="00:00:00",
                timestamp_end="00:26:00",
            )
        ],
        whole_transcript="We talked about the weather.",
    )
    report = evaluate_session(payload, store)
    assert any(c.cpt_code == "97110" for c in report.billable_codes)
    assert any(
        s.cpt_code == "97110" and s.transcript_support == "weak"
        for s in report.transcript_validation.cpt_support
    )




def test_human_summary_present(store):
    payload = _base_payload(
        diagnoses={"icd_1": "S23.121S"},
        detected_cpt_codes=[
            DetectedCptCode(
                cpt_code="97110",
                sequence=1,
                timestamp_start="00:00:00",
                timestamp_end="00:26:00",
            )
        ],
        whole_transcript="We did therapeutic exercises today.",
    )
    report = evaluate_session(payload, store)
    assert report.human_summary.patient_name == "John Doe"
    assert report.transcript_validation.icd_validation.status in ("complete", "partial", "skipped")
    assert "BILLING EVALUATION SUMMARY" in report.human_summary.narrative
