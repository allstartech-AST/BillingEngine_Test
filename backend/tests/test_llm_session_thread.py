"""Session-scoped LLM thread — reference once, task-only follow-ups."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.engine.llm_cpt_tasks import (
    CptVerificationResponse,
    _suggest_missing_prompt_threaded,
    _verify_prompt_threaded,
)
from app.engine.llm_kb import build_compact_ptp_pair_context
from app.engine.llm_session_thread import LiveEnrichmentThread, _bootstrap_turns
from app.models.live import LiveClientInfo, LiveSessionState


def _session(store) -> LiveSessionState:
    return LiveSessionState(
        session_id="test-session",
        client_info=LiveClientInfo(client_name="Test", client_id="1"),
    )


def test_bootstrap_turns_include_medexa_reference(store) -> None:
    turns = _bootstrap_turns(store)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert "--- ENTIRE MEDEXA CPT DICTIONARY ---" in turns[0]["content"]
    assert turns[1]["role"] == "assistant"


def test_threaded_verify_prompt_omits_kb_block() -> None:
    prompt = _verify_prompt_threaded("97110", "Therapeutic exercises", "patient did exercises")
    assert "KNOWLEDGE BASE" not in prompt
    assert "97110" in prompt
    assert "patient did exercises" in prompt


def test_threaded_suggest_prompt_omits_medexa_dump() -> None:
    prompt = _suggest_missing_prompt_threaded("new transcript", ["97110"], "")
    assert "--- ENTIRE MEDEXA CPT DICTIONARY ---" not in prompt
    assert "Existing CPTs already detected" in prompt


def test_messages_for_call_bootstrap_before_ready(store) -> None:
    state = _session(store)
    thread = LiveEnrichmentThread(state, store)
    messages = thread._messages_for_call("verify task")
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "--- ENTIRE MEDEXA CPT DICTIONARY ---" in messages[1]["content"]
    assert messages[-1] == {"role": "user", "content": "verify task"}


def test_messages_for_call_reuses_stored_turns(store) -> None:
    state = _session(store)
    state.llm_context_ready = True
    state.llm_turns = [
        {"role": "user", "content": "bootstrap"},
        {"role": "assistant", "content": "ok"},
    ]
    thread = LiveEnrichmentThread(state, store)
    messages = thread._messages_for_call("next task")
    assert "--- ENTIRE MEDEXA CPT DICTIONARY ---" not in "".join(m["content"] for m in messages)
    assert messages[-1]["content"] == "next task"


def test_complete_json_records_turns(store) -> None:
    state = _session(store)
    thread = LiveEnrichmentThread(state, store)
    fake = {"is_supported": True, "reasoning": "ok", "region": "", "region_confidence": 0}

    with patch(
        "app.engine.llm_session_thread.is_configured",
        return_value=True,
    ), patch(
        "app.engine.llm_session_thread.generate_json_pydantic_messages",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        result = asyncio.run(
            thread.complete_json("verify 97110", CptVerificationResponse, temperature=0.2)
        )

    assert result == fake
    assert state.llm_context_ready is True
    assert len(state.llm_turns) == 4
    assert state.llm_turns[0]["role"] == "user"
    assert "--- ENTIRE MEDEXA CPT DICTIONARY ---" in state.llm_turns[0]["content"]
    assert state.llm_turns[2]["content"] == "verify 97110"


def test_compact_ptp_pair_smaller_than_full_kb(store) -> None:
    codes = list(store.ptp.keys())[:2]
    if len(codes) < 2:
        return
    pair_ctx = build_compact_ptp_pair_context(store, codes[0], codes[1])
    from app.engine.llm_kb import build_kb_context

    full = build_kb_context(store, codes[0], codes[1])
    if pair_ctx:
        assert len(pair_ctx) <= len(full)
