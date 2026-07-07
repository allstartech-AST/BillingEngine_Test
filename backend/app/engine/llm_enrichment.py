"""Background AI enrichment worker for live billing sessions."""

from __future__ import annotations

import asyncio
import logging
import traceback

from app.config import (
    LLM_ENRICHMENT_DEBOUNCE_SECONDS,
    load_env_files,
    openai_api_key,
)
from app.engine.llm_cpt_tasks import suggest_missing_cpts_async, verify_cpt_async
from app.engine.llm_modifier_tasks import suggest_modifiers_async
from app.engine.llm_quota import quota_on_cooldown
from app.engine.llm_session_thread import LiveEnrichmentThread
from app.engine.llm_suggest_transcript import (
    compose_suggest_transcript,
    lexical_hints_for_segment,
    suggest_segment_bounds,
)
from app.engine.loader import MetadataStore

load_env_files()

logger = logging.getLogger(__name__)

_session_locks: dict[str, asyncio.Lock] = {}
_main_loop: asyncio.AbstractEventLoop | None = None
_debounce_handles: dict[str, asyncio.TimerHandle] = {}
_active_sessions: set[str] = set()
_pending_after_busy: set[str] = set()


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


def _resolve_event_loop() -> asyncio.AbstractEventLoop | None:
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            return loop
    except RuntimeError:
        pass
    if _main_loop is not None and _main_loop.is_running():
        return _main_loop
    return None


def _reset_debounce_timer(session_id: str, store: MetadataStore) -> None:
    loop = _resolve_event_loop()
    if loop is None:
        logger.warning("No running event loop found; AI enrichment will not run for %s", session_id)
        return

    existing = _debounce_handles.pop(session_id, None)
    if existing is not None:
        existing.cancel()

    def _on_debounce_fire() -> None:
        _debounce_handles.pop(session_id, None)
        _start_enrichment_if_idle(session_id, store)

    handle = loop.call_later(LLM_ENRICHMENT_DEBOUNCE_SECONDS, _on_debounce_fire)
    _debounce_handles[session_id] = handle
    logger.debug(
        "AI enrichment for %s scheduled in %.1fs",
        session_id,
        LLM_ENRICHMENT_DEBOUNCE_SECONDS,
    )


def _start_enrichment_if_idle(session_id: str, store: MetadataStore) -> None:
    if session_id in _active_sessions:
        _pending_after_busy.add(session_id)
        logger.info(
            "AI enrichment for %s deferred — worker already running",
            session_id,
        )
        return

    loop = _resolve_event_loop()
    if loop is None:
        logger.warning("No running event loop found; AI enrichment will not run for %s", session_id)
        return

    loop.create_task(_ai_enrichment_worker(session_id, store))


async def _ai_enrichment_worker(session_id: str, store: MetadataStore) -> None:
    if not openai_api_key():
        logger.warning("Skipping AI enrichment for %s — OPENAI_API_KEY is unset.", session_id)
        return
    if quota_on_cooldown():
        logger.warning("Skipping AI enrichment for %s — OpenAI quota cooldown active.", session_id)
        return

    _active_sessions.add(session_id)
    lock = _get_session_lock(session_id)
    try:
        async with lock:
            try:
                from app.engine.realtime.helpers import (
                    _apply_conflict_pending,
                    _apply_icd_validation,
                    _next_sequence,
                    _recalculate_units,
                    _refresh_conflicts,
                    _sync_row_messages,
                )
                from app.engine.realtime.store import get_session, save_session
                from app.models.live import LiveCptRow

                state = get_session(session_id)
                llm_thread = LiveEnrichmentThread(state, store)

                while True:
                    state = get_session(session_id)
                    made_progress = False
                    _refresh_conflicts(state, store)

                    for row in list(state.cpts):
                        if getattr(row, "ai_supported", None) is None:
                            try:
                                res = await verify_cpt_async(
                                    row.cpt_code,
                                    store.description(row.cpt_code)
                                    if store.knows_cpt(row.cpt_code)
                                    else row.cpt_code,
                                    state.whole_transcript,
                                    store,
                                    thread=llm_thread,
                                )
                                row.ai_supported = res.get("is_supported")
                                row.ai_reasoning = res.get("reasoning", "")
                                if res.get("region_confidence", 0) >= 80 and res.get("region"):
                                    row.region = res.get("region")
                            except Exception:
                                row.ai_supported = False
                                row.ai_reasoning = "Failed to parse AI response"
                            made_progress = True

                    for conflict in list(state.conflicts):
                        if conflict.conflict_type == "bypassable_bundle" and not conflict.ai_enriched:
                            try:
                                res = await suggest_modifiers_async(
                                    conflict.column_one_code,
                                    conflict.column_two_code,
                                    state.whole_transcript,
                                    store,
                                    thread=llm_thread,
                                )
                                mods = res.get("suggested_modifiers", [])
                                for rec in conflict.recommendations:
                                    if rec.action == "apply_modifier":
                                        rec.modifiers = mods
                                        if mods:
                                            mod_str = "/".join(mods)
                                            rec.summary = (
                                                f"AI Suggestion: {conflict.column_two_code} has a bundle "
                                                f"conflict with {conflict.column_one_code}. Apply modifier "
                                                f"{mod_str} because {res.get('reasoning', '').lower()}"
                                            )
                                        else:
                                            rec.summary = (
                                                f"AI Suggestion: {conflict.column_two_code} has a bundle "
                                                f"conflict with {conflict.column_one_code}, but no modifier "
                                                f"applies because {res.get('reasoning', '').lower()}"
                                            )
                                conflict.ai_enriched = True
                            except Exception:
                                conflict.ai_enriched = True
                            made_progress = True

                    current_pointer = getattr(state, "last_cpt_suggestion_length", 0)
                    for seg_start, seg_end in suggest_segment_bounds(
                        state.whole_transcript,
                        current_pointer,
                    ):
                        segment = state.whole_transcript[seg_start:seg_end]
                        transcript_for_prompt = compose_suggest_transcript(
                            state.whole_transcript,
                            seg_start,
                            seg_end,
                        )
                        existing_cpts = [r.cpt_code for r in state.cpts]
                        hints = lexical_hints_for_segment(
                            segment,
                            store,
                            set(existing_cpts),
                        )
                        try:
                            res = await suggest_missing_cpts_async(
                                transcript_for_prompt,
                                existing_cpts,
                                store,
                                lexical_hints=hints or None,
                                thread=llm_thread,
                            )
                            suggested = res.get("suggested_cpts", [])
                            if suggested:
                                for item in suggested:
                                    code = item.get("cpt_code")
                                    if code and store.knows_cpt(code) and code not in existing_cpts:
                                        row = LiveCptRow(
                                            cpt_code=code,
                                            sequence=_next_sequence(state.cpts),
                                            lifecycle="ai_suggested",
                                            is_timed=store.is_timed(code),
                                            billing_status="pending_therapist_review",
                                            rule_message="AI suggested code based on transcript.",
                                            ai_supported=True,
                                            ai_reasoning=item.get("reasoning", ""),
                                        )
                                        _apply_icd_validation(row, state.icds, store)
                                        _sync_row_messages(row)
                                        state.cpts.append(row)
                                        existing_cpts.append(code)
                                        made_progress = True
                        except Exception:
                            pass
                        current_pointer = seg_end
                        state.last_cpt_suggestion_length = current_pointer

                    if not made_progress:
                        break

                _refresh_conflicts(state, store)
                _apply_conflict_pending(state)
                _recalculate_units(state, store)
                save_session(state)

            except Exception:
                traceback.print_exc()
    finally:
        _active_sessions.discard(session_id)
        if session_id in _pending_after_busy:
            _pending_after_busy.discard(session_id)
            logger.info(
                "AI enrichment for %s rescheduling after deferred request",
                session_id,
            )
            _reset_debounce_timer(session_id, store)


def register_enrichment_event_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Capture uvicorn's main loop so sync handlers can schedule async AI work."""
    global _main_loop
    if loop is not None:
        _main_loop = loop
        return
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def launch_ai_enrichment_task(session_id: str, store: MetadataStore) -> None:
    """Debounce then schedule AI enrichment (skip if a worker is already active)."""
    loop = _resolve_event_loop()
    if loop is None:
        logger.warning("No running event loop found; AI enrichment will not run for %s", session_id)
        return

    if loop.is_running():
        loop.call_soon_threadsafe(_reset_debounce_timer, session_id, store)
    else:
        _reset_debounce_timer(session_id, store)
