
from app.engine.billing_rule_catalog import (
    live_rule_meta,
    rule_detect_message,
    uses_duration_for_units,
)
from app.engine.eight_minute import EIGHT_MINUTE_RULE
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


def _running_duration_unit_row(state, store: MetadataStore, exclude_cpt: str) -> LiveCptRow | None:
    for row in state.cpts:
        if row.cpt_code == exclude_cpt or row.lifecycle != "running":
            continue
        if uses_duration_for_units(live_rule_meta(row.cpt_code, store).timer_mode):
            return row
    return None


def _new_cpt_row(code: str, state, store: MetadataStore) -> LiveCptRow:
    meta = live_rule_meta(code, store)
    return LiveCptRow(
        cpt_code=code,
        sequence=_next_sequence(state.cpts),
        lifecycle="detected",
        billing_rule=meta.billing_rule,
        billing_status="confirmed",
        rule_message=rule_detect_message(meta, state.billing_rule),
        occurrence_count=1,
    )


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

    row = _new_cpt_row(code, state, store)
    _apply_icd_validation(row, state.icds, store)
    _sync_row_messages(row)

    state.cpts.append(row)
    _refresh_conflicts(state, store)

    from app.engine.llm_enrichment import launch_ai_enrichment_task
    launch_ai_enrichment_task(session_id, store)

    _pending_and_recalculate_billing(state, store)
    _sync_all_row_messages(state)
    save_session(state)

    meta = live_rule_meta(code, store)
    rule_note = rule_detect_message(meta, state.billing_rule)
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

    meta = live_rule_meta(row.cpt_code, store)
    if uses_duration_for_units(meta.timer_mode):
        running = _running_duration_unit_row(state, store, row.cpt_code)
        if running:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Cannot start multiple duration-based codes. Please pause {running.cpt_code} first.",
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

    meta = live_rule_meta(row.cpt_code, store)
    if uses_duration_for_units(meta.timer_mode):
        running = _running_duration_unit_row(state, store, row.cpt_code)
        if running:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume duration-based code. Please pause {running.cpt_code} first.",
            )

    row.lifecycle = "running"
    _sync_row_messages(row)
    save_session(state)
    return _live_response(state, store, f"CPT {cpt_code} resumed.")


def on_cpt_area(
    session_id: str,
    cpt_code: str,
    area_sq_cm: float,
    store: MetadataStore,
) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)

    row = _find_row(state.cpts, cpt_code.strip())
    if not row:
        return _live_response(state, store, f"CPT {cpt_code} not found.")

    row.area_sq_cm = round(float(area_sq_cm), 2)
    if row.lifecycle == "completed":
        _reconcile_billing_state_and_save(state, store)
    else:
        save_session(state)
    return _live_response(state, store, f"CPT {cpt_code} area set to {row.area_sq_cm:g} sq cm.")


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

    if row.lifecycle == "error":
        return _live_response(state, store, row.message)

    row.lifecycle = "completed"
    row.duration_minutes_exact = round(float(duration_minutes), 2)
    row.minutes_billed = int(round(duration_minutes))
    row.occurrence_count = 1

    _reconcile_billing_state(state, store)
    open_conflicts = unresolved_bypassable(state.conflicts, set(state.resolved_conflicts))
    meta = live_rule_meta(row.cpt_code, store)
    if open_conflicts:
        msg = (
            f"CPT {row.cpt_code} ended — duration {row.duration_minutes_exact:g} min; "
            f"units pending modifier resolution ({len(open_conflicts)} open conflict(s))."
        )
    elif row.billing_rule == EIGHT_MINUTE_RULE:
        msg = (
            f"CPT {row.cpt_code} ended — duration {row.duration_minutes_exact:g} min, "
            f"{row.units} unit(s) after timed rule."
        )
    elif meta.timer_mode == "occurrence":
        msg = f"CPT {row.cpt_code} completed — {row.units} unit(s) under {meta.billing_rule}."
    elif meta.timer_mode == "area":
        msg = (
            f"CPT {row.cpt_code} ended — {row.units} unit(s) "
            f"({row.area_sq_cm:g} sq cm recorded)."
        )
    else:
        msg = (
            f"CPT {row.cpt_code} ended — duration {row.duration_minutes_exact:g} min, "
            f"{row.units} unit(s) calculated."
        )

    save_session(state)
    return _live_response(state, store, msg)
