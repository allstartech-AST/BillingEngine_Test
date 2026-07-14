
import re
from app.engine.billing_rule_catalog import live_rule_meta, rule_detect_message
from app.engine.loader import MetadataStore
from app.models.live import LiveSessionResponse, LiveClientInfo, LiveCptRow
from app.engine.realtime.store import get_session, save_session
from app.engine.realtime.helpers import (
    _append_icd, _reactivate_session, _apply_icd_validation,
    _revalidate_all_cpts_icd, _sync_row_messages, _next_sequence,
    _open_cpt_row, _live_response, _pending_and_recalculate_billing,
    _refresh_conflicts, _recalculate_units, _find_row,
)
from app.engine.realtime.rules import unresolved_bypassable
from app.config import LLM_SENTENCES_PER_AI_BATCH
from app.engine.transcript_medexa import validate_cpt_transcript_support, validate_icd10_transcript_support

SENTENCES_PER_AI_BATCH = LLM_SENTENCES_PER_AI_BATCH


def _maybe_launch_ai_enrichment(
    state,
    session_id: str,
    store: MetadataStore,
    sentence_count: int,
) -> None:
    prev_count = state.sentences_fed_count
    state.sentences_fed_count += sentence_count
    if prev_count // SENTENCES_PER_AI_BATCH < state.sentences_fed_count // SENTENCES_PER_AI_BATCH:
        from app.engine.llm_enrichment import launch_ai_enrichment_task

        launch_ai_enrichment_task(session_id, store)


def create_live_session(client: LiveClientInfo, billing_rule: str, store: MetadataStore) -> LiveSessionResponse:
    from app.engine.realtime.store import create_session

    state = create_session(client, billing_rule)
    save_session(state)
    return _live_response(state, store, "Session started.")


def get_live_session(session_id: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    return _live_response(state, store, "Current session state.")

def on_session_end(session_id: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    open_row = _open_cpt_row(state.cpts)
    if open_row:
        save_session(state)
        return _live_response(
            state,
            store,
            f"End CPT {open_row.cpt_code} with duration before ending the session.",
        )
    open_conflicts = unresolved_bypassable(state.conflicts, set(state.resolved_conflicts))
    if open_conflicts:
        state.status = "blocked"
        state.session_message = (
            f"Cannot finalize — {len(open_conflicts)} unresolved modifier conflict(s)."
        )
        save_session(state)
        return _live_response(state, store, state.session_message)

    _recalculate_units(state, store)
    state.status = "ended"
    state.session_message = "Session finalized — all modifier issues cleared."
    save_session(state)
    return _live_response(state, store, state.session_message)


def on_sentence_fed(
    session_id: str,
    sentence: str,
    store: MetadataStore,
    *,
    sentence_count: int = 1,
) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)
    if not sentence.strip():
        return _live_response(state, store, "Empty sentence provided.")
    
    if not state.whole_transcript:
        state.whole_transcript = sentence
    else:
        state.whole_transcript += " " + sentence
    
    sentence_words = set(re.findall(r'\b[a-z0-9]+\b', sentence.lower()))
    
    possible_icds = set()
    for w in sentence_words:
        possible_icds.update(store.icd_keyword_index.get(w, set()))
        
    possible_cpts = set()
    for w in sentence_words:
        possible_cpts.update(store.cpt_keyword_index.get(w, set()))

    if not possible_icds and not possible_cpts:
        _maybe_launch_ai_enrichment(state, session_id, store, sentence_count)
        save_session(state)
        return _live_response(state, store, "No relevant keywords detected (fast path).")

    added_icds = []
    for icd in possible_icds:
        if icd not in store.medexa_icd10:
            continue
        support = validate_icd10_transcript_support(icd, sentence, store)
        if support.confidence_score and support.confidence_score >= 80:
            prev_len = len(state.icds)
            state.icds = _append_icd(state.icds, icd)
            if len(state.icds) > prev_len:
                added_icds.append(icd)
                
    added_cpts = []
    for cpt in possible_cpts:
        if cpt not in store.medexa or not store.knows_cpt(cpt):
            continue
        support = validate_cpt_transcript_support(cpt, sentence, store)
        if support.confidence_score and support.confidence_score >= 80:
            if _find_row(state.cpts, cpt) is None:
                meta = live_rule_meta(cpt, store)
                row = LiveCptRow(
                    cpt_code=cpt,
                    sequence=_next_sequence(state.cpts),
                    lifecycle="pending_start",
                    billing_rule=meta.billing_rule,
                    billing_status="confirmed",
                    rule_message=rule_detect_message(meta, state.billing_rule),
                    occurrence_count=1,
                )
                _apply_icd_validation(row, state.icds, store)
                _sync_row_messages(row)
                
                state.cpts.append(row)
                added_cpts.append(cpt)

    if added_icds or added_cpts:
        _revalidate_all_cpts_icd(state, store)
        for row in state.cpts:
            _sync_row_messages(row)
        _refresh_conflicts(state, store)
        message = f"Detected: {', '.join(added_cpts + added_icds)}"
    else:
        message = "No high-confidence codes detected."

    _maybe_launch_ai_enrichment(state, session_id, store, sentence_count)

    _pending_and_recalculate_billing(state, store)
    save_session(state)
    return _live_response(state, store, message)

