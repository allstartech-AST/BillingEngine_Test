
from app.engine.loader import MetadataStore
from app.models.live import LiveSessionResponse, LiveClientInfo
from app.engine.realtime.store import get_session, save_session, create_session
from app.engine.realtime.helpers import (
    _append_icd, _parse_icd_input, _reactivate_session, _apply_icd_validation,
    _revalidate_all_cpts_icd, _sync_row_messages, _next_sequence, _find_row,
    _open_cpt_row, _live_response, _apply_conflict_pending,
    _refresh_completed_rule_messages, _recalculate_units, _refresh_conflicts
)
from app.models.live import LiveCptRow
from app.engine.realtime.rules import (
    active_cpt_codes,
    conflict_codes,
    icd_pending_for_cpt,
    incremental_conflicts,
    unresolved_bypassable,
    _issue_removal_reason,
)
from app.engine.mue import apply_mue_cap
from app.engine.eight_minute import calculate_units as calculate_units_cms
from app.engine import ama_rule
from app.engine.icd10 import icd_code_variants


from app.engine.transcript_medexa import validate_cpt_transcript_support, validate_icd10_transcript_support

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


def on_sentence_fed(session_id: str, sentence: str, store: MetadataStore) -> LiveSessionResponse:
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
        if cpt not in store.medexa:
            continue
        support = validate_cpt_transcript_support(cpt, sentence, store)
        if support.confidence_score and support.confidence_score >= 80:
            if not any(r.cpt_code == cpt for r in state.cpts):
                is_timed = store.is_timed(cpt)
                row = LiveCptRow(
                    cpt_code=cpt,
                    sequence=_next_sequence(state.cpts),
                    lifecycle="pending_start",
                    is_timed=is_timed,
                    billing_status="confirmed",
                    rule_message=(
                        f"{'AMA Rule of 8' if state.billing_rule == 'ama_rule_of_8' else '8-minute rule'} applies — click start when ready." 
                        if is_timed else "Occurrence/modality code — units are calculated manually."
                    ),
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
        _apply_conflict_pending(state)
        _recalculate_units(state, store)
        save_session(state)
        return _live_response(state, store, f"Detected: {', '.join(added_cpts + added_icds)}")
    
    return _live_response(state, store, "No high-confidence codes detected.")

