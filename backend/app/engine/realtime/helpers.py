import re

from app.engine.billing_dispatcher import calculate_all_units
from app.engine.billing_rule_catalog import live_rule_meta, rule_badge_label
from app.engine.eight_minute import EIGHT_MINUTE_RULE
from app.engine.icd10 import icd_code_variants
from app.engine.loader import MetadataStore
from app.engine.mue import apply_mue_cap
from app.engine.realtime.rules import (
    active_cpt_codes,
    conflict_codes,
    icd_pending_for_cpt,
    incremental_conflicts,
    unresolved_bypassable,
    _issue_removal_reason,
)
from app.engine.realtime.store import get_session, save_session
from app.engine.realtime.finalize_display import build_finalize_display
from app.engine.realtime.ui_display import build_live_ui_display
from app.models.live import (
    LiveClientInfo,
    LiveCptRow,
    LiveSessionResponse,
    LiveSessionState,
)
from app.engine.transcript_medexa import (
    validate_cpt_transcript_support,
    validate_icd10_transcript_support,
)


def _append_icd(icds: list[str], icd10_code: str) -> list[str]:
    code = icd10_code.strip()
    if not code:
        return icds
    for existing in icds:
        if code == existing:
            return icds
        if code in icd_code_variants(existing) or existing in icd_code_variants(code):
            return icds
    return icds + [code]


def _parse_icd_input(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\s]+", raw.strip()) if part.strip()]


def _reactivate_session(state: LiveSessionState) -> None:
    if state.status in ("ended", "blocked"):
        state.status = "active"
        state.session_message = ""


def _apply_icd_validation(row: LiveCptRow, icds: list[str], store: MetadataStore) -> None:
    if row.lifecycle in ("removed", "error"):
        return
    icd_pending, icd_msg = icd_pending_for_cpt(row.cpt_code, icds, store)
    row.icd_guidance = icd_msg
    if icd_pending:
        if "icd_medical_necessity" not in row.pending_reasons:
            row.pending_reasons.append("icd_medical_necessity")
        if row.billing_status not in ("removed", "error", "manual"):
            row.billing_status = "pending_therapist_review"
    else:
        row.pending_reasons = [r for r in row.pending_reasons if r != "icd_medical_necessity"]
        if not row.pending_reasons and row.billing_status == "pending_therapist_review":
            row.billing_status = "confirmed"


def _revalidate_all_cpts_icd(state: LiveSessionState, store: MetadataStore) -> None:
    for row in state.cpts:
        _apply_icd_validation(row, state.icds, store)


def _sync_row_messages(row: LiveCptRow) -> None:
    if row.lifecycle in ("removed", "error"):
        return
    parts = [p for p in (row.rule_message, row.icd_guidance) if p]
    row.message = " ".join(parts)


def _merge_ai_suggestion_metadata(row: LiveCptRow, item: dict) -> None:
    """Attach LLM suggest-missing evidence to an existing session CPT row."""
    row.ai_supported = True
    reasoning = str(item.get("reasoning") or "").strip()
    if reasoning:
        row.ai_reasoning = reasoning
    quote = str(item.get("exact_quote") or "").strip()
    if quote:
        row.ai_exact_quote = quote


def _next_sequence(cpts: list[LiveCptRow]) -> int:
    if not cpts:
        return 1
    return max(c.sequence for c in cpts) + 1


def _find_row(cpts: list[LiveCptRow], cpt_code: str) -> LiveCptRow | None:
    for row in reversed(cpts):
        if row.cpt_code == cpt_code and row.lifecycle != "removed":
            return row
    return None


def _open_cpt_row(cpts: list[LiveCptRow]) -> LiveCptRow | None:
    for row in reversed(cpts):
        if row.lifecycle in ("detected", "billing", "manual_billing", "pending_start", "running", "paused"):
            return row
    return None


def _live_response(
    state: LiveSessionState,
    store: MetadataStore,
    event_message: str,
) -> LiveSessionResponse:
    open_row = _open_cpt_row(state.cpts)
    finalize = (
        build_finalize_display(state, store) if state.status == "ended" else None
    )
    return LiveSessionResponse(
        session=state,
        ui_display=build_live_ui_display(state, store),
        event_message=event_message,
        open_cpt_code=open_row.cpt_code if open_row else None,
        finalize_display=finalize,
    )


def _apply_conflict_pending(state: LiveSessionState) -> None:
    resolved = set(state.resolved_conflicts)
    open_conflicts = unresolved_bypassable(state.conflicts, resolved)
    pending_ids = {c.conflict_id for c in open_conflicts}
    affected: set[str] = set()
    for conflict in open_conflicts:
        affected |= conflict_codes(conflict)

    for row in state.cpts:
        if row.lifecycle in ("removed", "error"):
            continue
        row.conflict_ids = [
            c.conflict_id
            for c in open_conflicts
            if row.cpt_code in conflict_codes(c)
        ]
        in_conflict = row.cpt_code in affected and any(
            c.conflict_id in pending_ids for c in open_conflicts if row.cpt_code in c.codes
        )
        if in_conflict:
            row.billing_status = "pending_therapist_review"
            if "ncci_bundling" not in row.pending_reasons:
                row.pending_reasons.append("ncci_bundling")
        elif row.billing_status == "pending_therapist_review" and "ncci_bundling" in row.pending_reasons:
            if not any(row.cpt_code in conflict_codes(c) for c in open_conflicts):
                row.pending_reasons = [r for r in row.pending_reasons if r != "ncci_bundling"]
                if not row.pending_reasons:
                    row.billing_status = "confirmed"


def _build_live_segments(state: LiveSessionState) -> dict[str, dict]:
    segments: dict[str, dict] = {}
    for row in state.cpts:
        if row.lifecycle != "completed":
            continue
        cpt = row.cpt_code
        if cpt not in segments:
            segments[cpt] = {
                "minutes_exact": 0.0,
                "minutes_billed": 0,
                "minutes": 0.0,
                "sequences": [],
                "area_sq_cm": 0.0,
                "occurrence_count": 0,
            }
        seg = segments[cpt]
        seg["minutes_exact"] += row.duration_minutes_exact
        seg["minutes_billed"] += row.minutes_billed
        seg["minutes"] += row.duration_minutes_exact
        seg["sequences"].append(row.sequence)
        seg["occurrence_count"] = len(seg["sequences"])
        if row.area_sq_cm > 0:
            seg["area_sq_cm"] = row.area_sq_cm
    return segments


def _refresh_completed_rule_messages(state: LiveSessionState, store: MetadataStore) -> None:
    for row in state.cpts:
        if row.lifecycle != "completed":
            continue
        meta = live_rule_meta(row.cpt_code, store)
        if row.billing_rule == EIGHT_MINUTE_RULE:
            if state.billing_rule == "ama_rule_of_8":
                row.rule_message = (
                    f"{row.units} unit(s) billed under AMA Rule of 8 "
                    f"({row.duration_minutes_exact:g} min recorded for this code)."
                )
            else:
                row.rule_message = (
                    f"{row.units} unit(s) billed after pooled 8-minute rule "
                    f"({row.duration_minutes_exact:g} min recorded for this code)."
                )
        elif meta.timer_mode == "area":
            row.rule_message = (
                f"{row.units} unit(s) from area-based rule "
                f"({row.area_sq_cm:g} sq cm recorded)."
            )
        elif meta.timer_mode == "occurrence":
            row.rule_message = (
                f"{row.units} unit(s) under {rule_badge_label(meta)}."
            )
        else:
            row.rule_message = (
                f"{row.units} unit(s) under {rule_badge_label(meta)} "
                f"({row.duration_minutes_exact:g} min recorded)."
            )
        _sync_row_messages(row)


def _recalculate_units(state: LiveSessionState, store: MetadataStore) -> None:
    resolved = set(state.resolved_conflicts)
    open_conflicts = unresolved_bypassable(state.conflicts, resolved)
    pending_cpts: set[str] = set()
    for conflict in open_conflicts:
        pending_cpts |= conflict_codes(conflict)

    segments = _build_live_segments(state)
    if not segments:
        for row in state.cpts:
            if row.lifecycle == "completed":
                row.units = 0
        return

    unit_results = calculate_all_units(segments, store, state.billing_rule)
    by_cpt = {item.cpt_code: item for item in unit_results}

    units_by_cpt: dict[str, int] = {}
    for cpt, res in by_cpt.items():
        capped, _limit = apply_mue_cap(cpt, res.units, store)
        units_by_cpt[cpt] = capped

    for row in state.cpts:
        if row.lifecycle != "completed":
            continue
        units = units_by_cpt.get(row.cpt_code, 0)
        if row.cpt_code in pending_cpts and "ncci_bundling" in row.pending_reasons:
            units = 0
        row.units = units
        row.mue_note = ""
        res = by_cpt.get(row.cpt_code)
        if res:
            capped = units_by_cpt.get(row.cpt_code, 0)
            if capped < res.units:
                _, limit = apply_mue_cap(row.cpt_code, res.units, store)
                if limit is not None:
                    row.mue_note = f"MUE limit {limit} (remaining minutes discarded)"

    _refresh_completed_rule_messages(state, store)


def _refresh_conflicts(state: LiveSessionState, store: MetadataStore) -> None:
    active = active_cpt_codes(state.cpts)
    conflicts, issues, hard_removed = incremental_conflicts(active, store)

    old_conflicts = {c.conflict_id: c for c in state.conflicts}
    for c in conflicts:
        if c.conflict_id in old_conflicts:
            old_c = old_conflicts[c.conflict_id]
            if old_c.ai_enriched:
                c.ai_enriched = old_c.ai_enriched
                c.recommendations = old_c.recommendations

    for cpt in hard_removed:
        row = _find_row(state.cpts, cpt)
        if row:
            row.lifecycle = "removed"
            row.billing_status = "removed"
            row.units = 0
            issue = next((i for i in issues if i.code == cpt and i.severity == "error"), None)
            if not issue:
                issue = next((i for i in issues if i.code == cpt), None)
            if issue:
                row.removal_reason = _issue_removal_reason(issue)
                row.message = issue.message
                row.rule_message = ""
                row.icd_guidance = ""

    state.conflicts = conflicts
    _apply_conflict_pending(state)


def _reconcile_billing_state(state: LiveSessionState, store: MetadataStore) -> None:
    """Refresh conflicts, re-apply pending flags, and recalculate units."""
    _refresh_conflicts(state, store)
    _apply_conflict_pending(state)
    _recalculate_units(state, store)


def _reconcile_billing_state_and_save(state: LiveSessionState, store: MetadataStore) -> None:
    _reconcile_billing_state(state, store)
    save_session(state)


def _refresh_and_recalculate_billing(state: LiveSessionState, store: MetadataStore) -> None:
    """Refresh hard conflicts and recalculate units without a second pending pass."""
    _refresh_conflicts(state, store)
    _recalculate_units(state, store)


def _refresh_and_recalculate_billing_and_save(
    state: LiveSessionState,
    store: MetadataStore,
) -> None:
    _refresh_and_recalculate_billing(state, store)
    save_session(state)


def _pending_and_recalculate_billing(state: LiveSessionState, store: MetadataStore) -> None:
    _apply_conflict_pending(state)
    _recalculate_units(state, store)


def _sync_all_row_messages(state: LiveSessionState) -> None:
    for row in state.cpts:
        _sync_row_messages(row)


