"""Live rule-aware timer metadata and unit recalculation tests."""

from app.engine.billing_rule_catalog import (
    live_rule_meta,
    rule_badge_label,
    uses_duration_for_units,
)
from app.engine.loader import load_metadata, reset_metadata_cache
from app.engine.realtime.handlers_cpt import on_cpt_detected, on_cpt_end
from app.engine.realtime.handlers_modifier import on_modifier_action
from app.engine.realtime.handlers_session import create_live_session
from app.engine.realtime.helpers import _build_live_segments, _recalculate_units
from app.models.live import LiveClientInfo


def _setup():
    reset_metadata_cache()
    store = load_metadata()
    client = LiveClientInfo(client_name="Test", client_id="T-1")
    response = create_live_session(client, "cms_8_minute", store)
    return response.session.session_id, store


def test_eight_minute_meta():
    _, store = _setup()
    meta = live_rule_meta("97110", store)
    assert meta.billing_rule == "8_minute_rule"
    assert meta.timer_mode == "duration_units"
    assert uses_duration_for_units(meta.timer_mode)


def test_full_block_meta():
    _, store = _setup()
    meta = live_rule_meta("98979", store)
    assert meta.billing_rule == "full_block_required"
    assert meta.block_minutes == 10
    assert meta.timer_mode == "duration_units"
    assert "Full Block" in rule_badge_label(meta)


def test_time_band_meta():
    _, store = _setup()
    meta = live_rule_meta("98966", store)
    assert meta.billing_rule == "time_band_select"
    assert meta.time_band_min == 5
    assert meta.time_band_max == 10


def test_untimed_per_session_meta():
    _, store = _setup()
    meta = live_rule_meta("92507", store)
    assert meta.billing_rule == "untimed_per_session"
    assert meta.timer_mode == "occurrence"


def test_area_based_meta():
    _, store = _setup()
    meta = live_rule_meta("97605", store)
    assert meta.billing_rule == "area_based"
    assert meta.timer_mode == "area"


def test_ui_card_includes_timer_meta():
    session_id, store = _setup()
    response = on_cpt_detected(session_id, "98979", store)
    card = next(c for c in response.ui_display.cpt_cards if c.cpt_code == "98979")
    assert card.timer_meta is not None
    assert card.timer_meta.timer_mode == "duration_units"
    assert card.timer_meta.block_minutes == 10


def test_recalculate_full_block_units():
    session_id, store = _setup()
    on_cpt_detected(session_id, "98979", store)
    on_cpt_end(session_id, "98979", 10, store)
    from app.engine.realtime.store import get_session

    state = get_session(session_id)
    row = next(r for r in state.cpts if r.cpt_code == "98979")
    assert row.units == 1


def test_recalculate_untimed_per_session_units():
    session_id, store = _setup()
    on_cpt_detected(session_id, "92507", store)
    on_cpt_end(session_id, "92507", 0, store)
    from app.engine.realtime.store import get_session

    state = get_session(session_id)
    row = next(r for r in state.cpts if r.cpt_code == "92507")
    assert row.units == 1


def test_build_live_segments_aggregates():
    session_id, store = _setup()
    on_cpt_detected(session_id, "97110", store)
    on_cpt_end(session_id, "97110", 16, store)
    from app.engine.realtime.store import get_session

    state = get_session(session_id)
    segments = _build_live_segments(state)
    assert "97110" in segments
    assert segments["97110"]["minutes"] == 16


def test_therapist_remove_still_works():
    session_id, store = _setup()
    on_cpt_detected(session_id, "97110", store)
    response = on_modifier_action(session_id, "therapist_remove_97110", "reject", None, store)
    assert all(card.cpt_code != "97110" for card in response.ui_display.cpt_cards)
