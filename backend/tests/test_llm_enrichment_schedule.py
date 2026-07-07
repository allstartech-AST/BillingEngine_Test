"""Phase 5 enrichment scheduling — debounce and skip-if-busy."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.config import LLM_ENRICHMENT_DEBOUNCE_SECONDS, LLM_SENTENCES_PER_AI_BATCH
from app.engine.llm_enrichment import (
    _active_sessions,
    _debounce_handles,
    _pending_after_busy,
    launch_ai_enrichment_task,
)


def setup_function() -> None:
    _debounce_handles.clear()
    _active_sessions.clear()
    _pending_after_busy.clear()


def test_ai_batch_threshold_is_forty() -> None:
    assert LLM_SENTENCES_PER_AI_BATCH == 40


def test_launch_resets_debounce_timer() -> None:
    loop = asyncio.new_event_loop()
    store = MagicMock()

    with patch("app.engine.llm_enrichment._resolve_event_loop", return_value=loop):
        launch_ai_enrichment_task("sess-1", store)
        assert "sess-1" in _debounce_handles

        first_handle = _debounce_handles["sess-1"]
        launch_ai_enrichment_task("sess-1", store)
        assert first_handle.cancelled()
        assert "sess-1" in _debounce_handles
        assert _debounce_handles["sess-1"] is not first_handle

    loop.close()


def test_debounce_delay_config() -> None:
    assert LLM_ENRICHMENT_DEBOUNCE_SECONDS == 3.0
