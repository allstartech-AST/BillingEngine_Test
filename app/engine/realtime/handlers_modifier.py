
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

def on_modifier_action(
    session_id: str,
    conflict_id: str,
    action: str,
    modifier: str | None,
    store: MetadataStore,
) -> LiveSessionResponse:
    state = get_session(session_id)
    conflict = next((c for c in state.conflicts if c.conflict_id == conflict_id), None)
    if not conflict:
        return _live_response(state, store, f"Conflict {conflict_id} not found.")

    if action == "approve":
        if conflict_id not in state.resolved_conflicts:
            state.resolved_conflicts.append(conflict_id)
        for row in state.cpts:
            if row.cpt_code in conflict.codes:
                row.pending_reasons = [r for r in row.pending_reasons if r != "ncci_bundling"]
                if not row.pending_reasons:
                    row.billing_status = "confirmed"
                if modifier and modifier not in row.applied_modifiers:
                    row.applied_modifiers.append(modifier)
        _apply_conflict_pending(state)
        _recalculate_units(state, store)
        msg = f"Modifier approved for {conflict_id}."
    else:
        newer = max(conflict.codes, key=lambda c: next(
            (r.sequence for r in state.cpts if r.cpt_code == c), 0
        ))
        target = _find_row(state.cpts, newer)
        if target:
            target.lifecycle = "removed"
            target.billing_status = "removed"
            target.units = 0
            target.message = f"Rejected — removed due to conflict {conflict_id}."
        _refresh_conflicts(state, store)
        _recalculate_units(state, store)
        msg = f"Conflict {conflict_id} rejected — {newer} removed."

    save_session(state)
    return _live_response(state, store, msg)

