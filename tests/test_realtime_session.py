import pytest
from fastapi.testclient import TestClient

from app.engine.realtime import (
    create_live_session,
    on_cpt_detected,
    on_cpt_end,
    on_icd_detected,
    on_modifier_action,
    on_session_end,
)
from app.engine.realtime.store import reset_sessions
from app.main import app
from app.models.live import LiveClientInfo


@pytest.fixture(autouse=True)
def clean_sessions():
    reset_sessions()
    yield
    reset_sessions()


def _start(store):
    return create_live_session(
        LiveClientInfo(client_name="Test Patient", client_id="T-1"),
        "cms_8_minute",
        store,
    )


def test_icd_added_and_shown(store):
    session = _start(store)
    sid = session.session.session_id
    resp = on_icd_detected(sid, "M25.511, M54.50", store)
    assert "M25.511" in resp.session.icds
    assert "M54.50" in resp.session.icds
    assert len(resp.ui_display.icd_cards) == 1
    assert resp.ui_display.icd_cards[0].detected_icd10_codes == ["M25.511", "M54.50"]


def test_icd_add_after_session_end(store):
    session = _start(store)
    sid = session.session.session_id
    on_session_end(sid, store)
    resp = on_icd_detected(sid, "M25.511", store)
    assert resp.session.status == "active"
    assert "M25.511" in resp.session.icds


def test_cpt_detect_before_icd_then_icd_clears_pending(store):
    session = _start(store)
    sid = session.session.session_id
    detect = on_cpt_detected(sid, "97110", store)
    row = next(r for r in detect.session.cpts if r.cpt_code == "97110")
    assert "icd_medical_necessity" in row.pending_reasons
    after_icd = on_icd_detected(sid, "M25.511", store)
    row = next(r for r in after_icd.session.cpts if r.cpt_code == "97110")
    assert "icd_medical_necessity" not in row.pending_reasons


def test_cpt_detect_shows_rule_without_duration(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    resp = on_cpt_detected(sid, "97110", store)
    card = next(c for c in resp.ui_display.cpt_cards if c.cpt_code == "97110")
    assert card.units_display == 0
    assert card.duration_display == "—"
    assert card.badge == "8-Minute Rule"


def test_second_cpt_triggers_incremental_conflict_after_first_ended(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97140", store)
    on_cpt_end(sid, "97140", 16, store)
    resp = on_cpt_detected(sid, "97530", store)
    assert resp.session.conflicts
    row_97140 = next(r for r in resp.session.cpts if r.cpt_code == "97140")
    assert row_97140.billing_status == "pending_therapist_review"


def test_cannot_detect_second_cpt_until_first_ended(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97110", store)
    blocked = on_cpt_detected(sid, "97140", store)
    assert blocked.open_cpt_code == "97110"
    assert "End CPT 97110" in blocked.event_message
    assert not any(r.cpt_code == "97140" for r in blocked.session.cpts)


def test_timed_cpt_end_calculates_units(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97110", store)
    resp = on_cpt_end(sid, "97110", 16, store)
    row = next(r for r in resp.session.cpts if r.cpt_code == "97110")
    assert row.lifecycle == "completed"
    assert row.units == 1
    card = next(c for c in resp.ui_display.cpt_cards if c.cpt_code == "97110")
    assert card.units_display == 1


def test_untimed_cpt_manual_billing(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    detect = on_cpt_detected(sid, "97012", store)
    row = next(r for r in detect.session.cpts if r.cpt_code == "97012")
    assert row.lifecycle == "manual_billing"
    assert row.is_timed is False
    assert "manual" in row.rule_message.lower()
    ended = on_cpt_end(sid, "97012", 10, store)
    card = next(c for c in ended.ui_display.cpt_cards if c.cpt_code == "97012")
    assert card.duration_display != "—"
    assert card.badge == "Manual Units"


def test_unknown_cpt_not_shown_as_card(store):
    session = _start(store)
    sid = session.session.session_id
    resp = on_cpt_detected(sid, "99999", store)
    assert not resp.session.cpts
    assert "not in billing metadata" in resp.event_message.lower()
    assert not resp.ui_display.cpt_cards


def test_97010_removed_for_mue_zero_not_ncci(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.561 M54.50", store)
    resp = on_cpt_detected(sid, "97010", store)
    row = next(r for r in resp.session.cpts if r.cpt_code == "97010")
    assert row.lifecycle == "removed"
    assert row.removal_reason == "mue_zero"
    assert "MUE limit is 0" in row.message
    assert len(resp.ui_display.removed_section) == 1
    assert "MUE limit zero" in resp.ui_display.removed_section[0].reason


def test_completed_cpt_clears_awaiting_duration_message(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97110", store)
    resp = on_cpt_end(sid, "97110", 15, store)
    card = next(c for c in resp.ui_display.cpt_cards if c.cpt_code == "97110")
    assert card.duration_display == "15:00"
    assert card.units_display == 1
    assert not any(s.type == "awaiting_end" for s in card.suggestions)
    assert not any(s.type == "rule_applicability" for s in card.suggestions)
    assert any(s.type == "units_calculated" for s in card.suggestions)
    assert "provide duration" not in " ".join(s.summary for s in card.suggestions).lower()
    # Adding another ICD must not restore the detect-phase message on the ended CPT
    after_icd = on_icd_detected(sid, "M54.50", store)
    card2 = next(c for c in after_icd.ui_display.cpt_cards if c.cpt_code == "97110")
    assert not any(s.type == "rule_applicability" for s in card2.suggestions)


def test_pooled_two_cpts_can_exceed_one_total_unit(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97110", store)
    on_cpt_end(sid, "97110", 16, store)
    on_cpt_detected(sid, "97140", store)
    resp = on_cpt_end(sid, "97140", 16, store)
    assert resp.ui_display.summary_cards.session_units_total == 2


def test_ncci_conflict_zeros_units_and_pending(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97140", store)
    on_cpt_end(sid, "97140", 16, store)
    resp = on_cpt_detected(sid, "97530", store)
    assert resp.session.conflicts
    row_97140 = next(r for r in resp.session.cpts if r.cpt_code == "97140")
    assert row_97140.billing_status == "pending_therapist_review"
    assert row_97140.units == 0


def test_modifier_approve_recalculates_units(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97140", store)
    on_cpt_end(sid, "97140", 16, store)
    resp = on_cpt_detected(sid, "97530", store)
    on_cpt_end(sid, "97530", 28, store)
    conflict_id = resp.session.conflicts[0].conflict_id
    approved = on_modifier_action(sid, conflict_id, "approve", None, store)
    row_97140 = next(r for r in approved.session.cpts if r.cpt_code == "97140")
    row_97530 = next(r for r in approved.session.cpts if r.cpt_code == "97530")
    assert row_97140.billing_status == "confirmed"
    assert row_97140.units + row_97530.units >= 1


def test_session_end_blocked_with_unresolved_conflict(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97140", store)
    on_cpt_end(sid, "97140", 16, store)
    on_cpt_detected(sid, "97530", store)
    on_cpt_end(sid, "97530", 28, store)
    resp = on_session_end(sid, store)
    assert resp.session.status == "blocked"
    assert "unresolved" in resp.event_message.lower()
    assert resp.finalize_display is None


def test_finalize_display_on_session_end(store):
    session = _start(store)
    sid = session.session.session_id
    on_icd_detected(sid, "M25.511", store)
    on_cpt_detected(sid, "97110", store)
    on_cpt_end(sid, "97110", 16, store)
    on_cpt_detected(sid, "97012", store)
    on_cpt_end(sid, "97012", 2, store)
    resp = on_session_end(sid, store)
    assert resp.session.status == "ended"
    assert resp.finalize_display is not None
    assert resp.finalize_display.cpt_code_count == 2
    assert resp.finalize_display.billable_units_total == 2
    codes = {line.cpt_code: line for line in resp.finalize_display.lines}
    assert codes["97110"].units == 1
    assert codes["97012"].units == 1
    assert codes["97012"].duration_display == "02:00"


def test_live_api_routes(store):
    client = TestClient(app)
    create = client.post(
        "/live/session",
        json={"client_name": "API Patient", "client_id": "API-1"},
    )
    assert create.status_code == 200
    sid = create.json()["session"]["session_id"]

    icd = client.post(f"/live/session/{sid}/icd", json={"icd10_code": "M25.511"})
    assert icd.status_code == 200

    detect = client.post(f"/live/session/{sid}/cpt/detect", json={"cpt_code": "97110"})
    assert detect.status_code == 200

    end = client.post(
        f"/live/session/{sid}/cpt/end",
        json={"cpt_code": "97110", "duration_minutes": 16},
    )
    assert end.status_code == 200
    assert end.json()["session"]["cpts"][0]["units"] == 1

    get_resp = client.get(f"/live/session/{sid}")
    assert get_resp.status_code == 200
