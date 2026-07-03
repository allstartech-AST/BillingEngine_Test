
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

def on_icd_detected(session_id: str, icd10_code: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)
    before = len(state.icds)
    added: list[str] = []
    for code in _parse_icd_input(icd10_code):
        prev_len = len(state.icds)
        state.icds = _append_icd(state.icds, code)
        if len(state.icds) > prev_len:
            added.append(code)
    _revalidate_all_cpts_icd(state, store)
    for row in state.cpts:
        _sync_row_messages(row)
    _refresh_conflicts(state, store)
    _apply_conflict_pending(state)
    _recalculate_units(state, store)
    save_session(state)
    if added:
        msg = f"ICD added: {', '.join(added)}."
    elif before == len(state.icds):
        msg = "No new ICD codes (duplicate or empty input)."
    else:
        msg = "ICD list updated."
    return _live_response(state, store, msg)

