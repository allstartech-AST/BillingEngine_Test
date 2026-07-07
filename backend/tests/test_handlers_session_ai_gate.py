"""Live session sentence-count AI enrichment gate."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.live import LiveClientInfo, LiveSessionState
from app.engine.realtime.handlers_session import (
    SENTENCES_PER_AI_BATCH,
    _maybe_launch_ai_enrichment,
)


def _state(count: int = 0) -> LiveSessionState:
    return LiveSessionState(
        session_id="sess-gate",
        client_info=LiveClientInfo(client_name="Test", client_id="1"),
        sentences_fed_count=count,
    )


def test_ai_batch_threshold_is_forty() -> None:
    assert SENTENCES_PER_AI_BATCH == 40


@patch("app.engine.llm_enrichment.launch_ai_enrichment_task")
def test_enrichment_triggers_when_crossing_forty(mock_launch: MagicMock) -> None:
    state = _state(35)
    store = MagicMock()
    _maybe_launch_ai_enrichment(state, "sess-gate", store, 5)
    mock_launch.assert_called_once_with("sess-gate", store)
    assert state.sentences_fed_count == 40


@patch("app.engine.llm_enrichment.launch_ai_enrichment_task")
def test_enrichment_not_triggered_below_forty(mock_launch: MagicMock) -> None:
    state = _state(30)
    store = MagicMock()
    _maybe_launch_ai_enrichment(state, "sess-gate", store, 5)
    mock_launch.assert_not_called()
    assert state.sentences_fed_count == 35


@patch("app.engine.llm_enrichment.launch_ai_enrichment_task")
def test_enrichment_not_triggered_within_same_bucket(mock_launch: MagicMock) -> None:
    state = _state(40)
    store = MagicMock()
    _maybe_launch_ai_enrichment(state, "sess-gate", store, 5)
    mock_launch.assert_not_called()
    assert state.sentences_fed_count == 45


@patch("app.engine.llm_enrichment.launch_ai_enrichment_task")
def test_enrichment_triggers_at_eighty(mock_launch: MagicMock) -> None:
    state = _state(75)
    store = MagicMock()
    _maybe_launch_ai_enrichment(state, "sess-gate", store, 5)
    mock_launch.assert_called_once_with("sess-gate", store)
    assert state.sentences_fed_count == 80


@patch("app.engine.llm_enrichment.launch_ai_enrichment_task")
def test_feed_batch_five_crosses_on_eighth_click(mock_launch: MagicMock) -> None:
    """Prototype feeds 5 sentences per click; 8th click reaches 40."""
    state = _state(0)
    store = MagicMock()
    for click in range(7):
        _maybe_launch_ai_enrichment(state, "sess-gate", store, 5)
        mock_launch.assert_not_called()
    _maybe_launch_ai_enrichment(state, "sess-gate", store, 5)
    mock_launch.assert_called_once()
    assert state.sentences_fed_count == 40
