
from app.engine.loader import MetadataStore
from app.models.live import LiveSessionResponse
from app.engine.realtime.store import get_session, save_session
from app.engine.realtime.helpers import (
    _reactivate_session, _apply_icd_validation, _sync_row_messages,
    _next_sequence, _find_row, _open_cpt_row, _live_response,
    _reconcile_billing_state, _reconcile_billing_state_and_save,
    _pending_and_recalculate_billing, _refresh_conflicts, _sync_all_row_messages,
)
from app.engine.realtime.rules import unresolved_bypassable
from app.models.live import LiveCptRow

def on_cpt_detected(session_id: str, cpt_code: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)

    code = cpt_code.strip()
    open_row = _open_cpt_row(state.cpts)
    if open_row:
        if open_row.cpt_code == code:
            return _live_response(
                state,
                store,
                f"CPT {code} is already open — end it with duration first.",
            )
        save_session(state)
        return _live_response(
            state,
            store,
            f"End CPT {open_row.cpt_code} with duration before detecting {code}.",
        )

    if not store.knows_cpt(code):
        save_session(state)
        return _live_response(
            state,
            store,
            f"CPT {code} is not in billing metadata — not added to session.",
        )

    is_timed = store.is_timed(code)
    if is_timed:
        row = LiveCptRow(
            cpt_code=code,
            sequence=_next_sequence(state.cpts),
            lifecycle="detected",
            is_timed=True,
            billing_status="confirmed",
            rule_message=(
                f"{'AMA Rule of 8' if state.billing_rule == 'ama_rule_of_8' else '8-minute rule'} applies — provide duration when this CPT ends." 
                if is_timed else "Occurrence/modality code — units are calculated manually."
            ),
        )
    else:
        row = LiveCptRow(
            cpt_code=code,
            sequence=_next_sequence(state.cpts),
            lifecycle="manual_billing",
            is_timed=False,
            billing_status="manual",
            rule_message="Occurrence/modality code — units are calculated manually by the therapist.",
        )

    _apply_icd_validation(row, state.icds, store)
    _sync_row_messages(row)

    state.cpts.append(row)
    _refresh_conflicts(state, store)

    from app.engine.llm_enrichment import launch_ai_enrichment_task
    launch_ai_enrichment_task(session_id, store)

    _pending_and_recalculate_billing(state, store)
    _sync_all_row_messages(state)
    save_session(state)

    rule_note = f"Timed CPT ({'AMA Rule of 8' if state.billing_rule == 'ama_rule_of_8' else '8-minute rule'})." if is_timed else "Manual/occurrence billing."
    icd_note = f" {row.icd_guidance}" if row.icd_guidance else ""
    return _live_response(
        state,
        store,
        f"CPT {code} detected. {rule_note}{icd_note}",
    )


def on_cpt_start(session_id: str, cpt_code: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)

    row = _find_row(state.cpts, cpt_code.strip())
    if not row:
        return _live_response(state, store, f"CPT {cpt_code} not found.")

    if row.is_timed:
        for r in state.cpts:
            if r.cpt_code != row.cpt_code and r.is_timed and r.lifecycle == "running":
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot start multiple timed codes. Please pause {r.cpt_code} first."
                )

    row.lifecycle = "running"
    _sync_row_messages(row)
    save_session(state)
    return _live_response(state, store, f"CPT {cpt_code} started.")


def on_cpt_pause(
    session_id: str,
    cpt_code: str,
    duration_minutes: float,
    store: MetadataStore,
) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)
    
    row = _find_row(state.cpts, cpt_code.strip())
    if not row:
        return _live_response(state, store, f"CPT {cpt_code} not found.")
        
    if row.lifecycle != "running":
        return _live_response(state, store, f"CPT {cpt_code} is not currently running.")
        
    row.lifecycle = "paused"
    row.duration_minutes_exact = round(float(duration_minutes), 2)
    _sync_row_messages(row)
    save_session(state)
    return _live_response(state, store, f"CPT {cpt_code} paused.")


def on_cpt_resume(session_id: str, cpt_code: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)
    
    row = _find_row(state.cpts, cpt_code.strip())
    if not row:
        return _live_response(state, store, f"CPT {cpt_code} not found.")
        
    if row.lifecycle != "paused":
        return _live_response(state, store, f"CPT {cpt_code} is not currently paused.")
        
    if row.is_timed:
        for r in state.cpts:
            if r.cpt_code != row.cpt_code and r.is_timed and r.lifecycle == "running":
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot resume timed code. Please pause {r.cpt_code} first."
                )
                
    row.lifecycle = "running"
    _sync_row_messages(row)
    save_session(state)
    return _live_response(state, store, f"CPT {cpt_code} resumed.")


def on_cpt_end(
    session_id: str,
    cpt_code: str,
    duration_minutes: float,
    store: MetadataStore,
) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)

    row = _find_row(state.cpts, cpt_code.strip())
    if not row:
        return _live_response(
            state,
            store,
            f"CPT {cpt_code} not found — detect it first.",
        )

    if row.lifecycle == "completed":
        return _live_response(
            state,
            store,
            f"CPT {row.cpt_code} is already ended.",
        )

    if row.lifecycle not in ("detected", "manual_billing", "billing", "running", "pending_start", "paused"):
        return _live_response(state, store, row.message or f"CPT {row.cpt_code} cannot be ended.")

    if row.lifecycle in ("manual_billing", "pending_start", "running", "paused") and not row.is_timed:
        row.lifecycle = "completed"
        row.duration_minutes_exact = round(float(duration_minutes), 2)
        row.minutes_billed = int(round(duration_minutes))
        row.units = 0
        row.rule_message = (
            f"Duration recorded ({row.duration_minutes_exact} min). "
            "Units are calculated manually by the therapist (not under timed rule)."
        )
        _sync_row_messages(row)
        _reconcile_billing_state_and_save(state, store)
        return _live_response(
            state,
            store,
            (
                f"CPT {row.cpt_code} ended — duration {row.duration_minutes_exact} min. "
                "Manual billing — units not auto-calculated."
            ),
        )

    if row.lifecycle == "error":
        return _live_response(state, store, row.message)

    row.lifecycle = "completed"
    row.duration_minutes_exact = round(float(duration_minutes), 2)
    row.minutes_billed = int(round(duration_minutes))

    _reconcile_billing_state(state, store)
    open_conflicts = unresolved_bypassable(state.conflicts, set(state.resolved_conflicts))
    if open_conflicts:
        msg = (
            f"CPT {row.cpt_code} ended — duration {row.duration_minutes_exact} min; "
            f"units pending modifier resolution ({len(open_conflicts)} open conflict(s))."
        )
    else:
        msg = (
            f"CPT {row.cpt_code} ended — duration {row.duration_minutes_exact} min, "
            f"{row.units} unit(s) after pooled 8-minute rule."
        )

    save_session(state)
    return _live_response(state, store, msg)

