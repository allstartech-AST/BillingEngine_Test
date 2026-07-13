"""Finalize display billing rule labels."""

from app.engine.realtime.finalize_display import _billing_rule_label, build_finalize_display
from app.engine.realtime.store import create_session, save_session
from app.models.live import LiveClientInfo, LiveCptRow


def test_finalize_line_includes_billing_rule_label(store) -> None:
    state = create_session(LiveClientInfo(client_name="Test", client_id="T-1"), "cms_8_minute")
    state.cpts.append(
        LiveCptRow(
            cpt_code="97110",
            sequence=1,
            lifecycle="completed",
            billing_rule="8_minute_rule",
            duration_minutes_exact=23.0,
            units=2,
        )
    )
    save_session(state)

    display = build_finalize_display(state, store)
    assert display.lines[0].billing_rule == "8_minute_rule"
    assert display.lines[0].billing_rule_label == "8-Minute Rule"


def test_billing_rule_label_uses_ama_session_rule(store) -> None:
    row = LiveCptRow(
        cpt_code="97110",
        sequence=1,
        lifecycle="completed",
        billing_rule="8_minute_rule",
    )
    assert _billing_rule_label(row, store, "ama_rule_of_8") == "AMA Rule of 8"
