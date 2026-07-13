"""Live session CPT removal via modifier actions."""

from app.engine.loader import load_metadata, reset_metadata_cache
from app.engine.realtime.handlers_cpt import on_cpt_detected
from app.engine.realtime.handlers_modifier import on_modifier_action
from app.engine.realtime.handlers_session import create_live_session
from app.models.live import LiveClientInfo


def _setup_session():
    reset_metadata_cache()
    store = load_metadata()
    client = LiveClientInfo(client_name="Test", client_id="T-1")
    response = create_live_session(client, "cms_8_minute", store)
    session_id = response.session.session_id
    on_cpt_detected(session_id, "97110", store)
    return session_id, store


def test_transcript_weak_remove_conflict_id_removes_cpt():
    session_id, store = _setup_session()
    response = on_modifier_action(
        session_id,
        "ai_reject_97110",
        "reject",
        None,
        store,
    )
    assert response.ui_display is not None
    assert all(card.cpt_code != "97110" for card in response.ui_display.cpt_cards)
    assert any(item.cpt_code == "97110" for item in response.ui_display.removed_section)


def test_therapist_remove_conflict_id_removes_cpt():
    session_id, store = _setup_session()
    response = on_modifier_action(
        session_id,
        "therapist_remove_97110",
        "reject",
        None,
        store,
    )
    assert response.ui_display is not None
    assert all(card.cpt_code != "97110" for card in response.ui_display.cpt_cards)
    assert any(item.cpt_code == "97110" for item in response.ui_display.removed_section)
