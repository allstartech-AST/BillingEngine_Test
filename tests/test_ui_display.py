import json
from pathlib import Path

from app.engine.pipeline import evaluate_session
from app.models.input import BillingSessionInput

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "capture_demo_session.json"


def test_ui_display_capture_demo(store):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = evaluate_session(BillingSessionInput(**data), store)
    ui = report.ui_display

    assert ui.session_header.patient_id == "99283"
    assert len(ui.cpt_cards) == 3
    assert ui.summary_cards.session_units_total == sum(c.units_display for c in ui.cpt_cards)

    pending = [c for c in ui.cpt_cards if c.card_style == "review"]
    assert pending
    conflict_card = next(c for c in ui.cpt_cards if c.badge == "Modifier 59 Required")
    assert conflict_card.cpt_code == "97530"
    assert conflict_card.actions.approve_enabled
    assert "97140" in (conflict_card.conflict_message or "")
    assert conflict_card.modifiers_suggested == ["59", "XE", "XP", "XS", "XU"]

    confirmed = [c for c in ui.cpt_cards if c.card_style == "standard"]
    assert any(c.cpt_code == "97110" for c in confirmed)


def test_ui_display_icd_crosswalk_fallback_when_unmatched(store):
    """ICDs with no matched CPTs fall back to crosswalk-eligible count."""
    from app.models.input import BillingSessionInput, ClientInfo, DetectedCptCode, SessionMetadata

    payload = BillingSessionInput(
        client_info=ClientInfo(client_name="Test", client_id="PT-2"),
        session_metadata=SessionMetadata(
            session_start="2026-06-29T10:00:00Z",
            session_end="2026-06-29T13:00:00Z",
        ),
        diagnoses={"icd_1": "G54.2", "icd_2": "M25.511", "icd_3": "M54.50"},
        detected_cpt_codes=[
            DetectedCptCode(cpt_code="97162", sequence=1, timestamp_start="00:00:00", timestamp_end="00:30:00"),
            DetectedCptCode(cpt_code="97110", sequence=2, timestamp_start="00:30:00", timestamp_end="00:45:00"),
            DetectedCptCode(cpt_code="97140", sequence=3, timestamp_start="00:45:00", timestamp_end="01:00:00"),
            DetectedCptCode(cpt_code="97530", sequence=4, timestamp_start="01:00:00", timestamp_end="01:15:00"),
            DetectedCptCode(cpt_code="97112", sequence=5, timestamp_start="01:15:00", timestamp_end="01:30:00"),
            DetectedCptCode(cpt_code="97116", sequence=6, timestamp_start="01:30:00", timestamp_end="01:45:00"),
        ],
        whole_transcript="Evaluation and therapeutic exercises for shoulder and cervical spine.",
    )
    report = evaluate_session(payload, store)
    m25 = next(c for c in report.ui_display.icd_cards if c.icd10_code == "M25.511")
    assert len(m25.linked_cpt_codes) == 5
    assert m25.crosswalk_summary == "On crosswalk for 5 of 6 billed CPT(s)"
    g54 = next(c for c in report.ui_display.icd_cards if c.icd10_code == "G54.2")
    assert len(g54.linked_cpt_codes) == 6
    assert "97162" in g54.linked_cpt_codes


def test_ui_display_icd_crosswalk_count_matches_linked(store):
    """Linked CPT count and crosswalk summary stay in sync (incl. pending_icd_review)."""
    from app.models.input import BillingSessionInput, ClientInfo, DetectedCptCode, SessionMetadata

    payload = BillingSessionInput(
        client_info=ClientInfo(client_name="Test", client_id="PT-1"),
        session_metadata=SessionMetadata(
            session_start="2026-06-29T10:00:00Z",
            session_end="2026-06-29T11:00:00Z",
        ),
        diagnoses={"M25.511": "Pain in right shoulder", "M54.50": "Low back pain"},
        detected_cpt_codes=[
            DetectedCptCode(
                cpt_code="97162",
                sequence=1,
                timestamp_start="00:00:00",
                timestamp_end="00:30:00",
            ),
            DetectedCptCode(
                cpt_code="97110",
                sequence=2,
                timestamp_start="00:30:00",
                timestamp_end="00:56:00",
            ),
        ],
        whole_transcript="Evaluation and therapeutic exercises for the shoulder.",
    )
    report = evaluate_session(payload, store)
    billable_count = len(report.billable_codes)
    for card in report.ui_display.icd_cards:
        expected_hits = len(card.linked_cpt_codes)
        assert card.crosswalk_summary == (
            f"On crosswalk for {expected_hits} of {billable_count} billed CPT(s)"
        )
    icd_card = next(c for c in report.ui_display.icd_cards if c.icd10_code == "M25.511")
    assert "97162" in icd_card.linked_cpt_codes
    assert icd_card.crosswalk_summary.startswith("On crosswalk for ")
    assert icd_card.crosswalk_summary != f"On crosswalk for 0 of {billable_count} billed CPT(s)"


def test_ui_display_has_icd_cards(store):
    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "stress_test_session.json").read_text(
            encoding="utf-8"
        )
    )
    report = evaluate_session(BillingSessionInput(**data), store)
    assert len(report.ui_display.icd_cards) >= 1
    assert len(report.ui_display.removed_section) >= 1
