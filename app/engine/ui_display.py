from datetime import datetime

from app.config import MODIFIERS
from app.engine.icd10 import _icd_in_crosswalk, resolve_ranked_icd
from app.engine.loader import MetadataStore
from app.engine.provisional_units import calculate_provisional_unit_maps
from app.models.input import BillingSessionInput
from app.models.output import (
    BillableCode,
    BillingConflict,
    DiagnosisCptResult,
    RemovedCode,
    TranscriptCptSupport,
    TranscriptIcdSupport,
    UiCptActions,
    UiCptCard,
    UiDisplay,
    UiIcdCard,
    UiIcdSuggestion,
    UiProvisionalUnits,
    UiRemovedCard,
    UiSessionHeader,
    UiSuggestion,
    UiSummaryCards,
)

_STATUS_LABELS = {
    "ready": "Ready",
    "ready_with_advisories": "Medexa Summarized",
    "needs_therapist_action": "Medexa Summarized",
    "blocked": "Blocked",
}

_ABBREV = {
    "therapeutic": "Therapeutic",
    "procedure": "Proc.",
    "exercise": "Ex.",
    "exercises": "Ex.",
    "activities": "Act.",
    "activity": "Act.",
    "neuromuscular": "Neuromusc.",
    "re-education": "Ed.",
    "manual": "Manual",
    "therapy": "Ther.",
}


def format_duration_mmss(minutes_exact: float) -> str:
    total_seconds = max(0, int(round(minutes_exact * 60)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def format_session_duration(minutes: float) -> str:
    total_seconds = max(0, int(round(minutes * 60)))
    minutes_part, seconds = divmod(total_seconds, 60)
    return f"{minutes_part:02d}:{seconds:02d}"


def _short_cpt_label(cpt_code: str, description: str, store: MetadataStore) -> str:
    entry = store.medexa.get(cpt_code, {})
    if entry.get("label"):
        label = str(entry["label"]).strip()
        if len(label) <= 24:
            return label
        return label[:22] + "."

    words = description.replace(",", " ").replace(";", " ").split()
    parts: list[str] = []
    for word in words[:6]:
        lower = word.lower().strip(".")
        if lower in _ABBREV:
            parts.append(_ABBREV[lower])
        elif lower in ("1", "one", "or", "more", "areas", "each", "15", "minutes"):
            continue
        else:
            parts.append(word.capitalize() if word.islower() else word)
    short = " ".join(parts[:4]).strip()
    if len(short) > 28:
        short = short[:26] + "."
    return short or cpt_code


def _format_session_datetime(iso_value: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %I:%M %p").replace(" 0", " ")
    except ValueError:
        return iso_value


def _primary_ncci_conflict(
    cpt: str, conflicts: list[BillingConflict]
) -> BillingConflict | None:
    for conflict in conflicts:
        if conflict.conflict_type != "bypassable_bundle":
            continue
        if cpt in conflict.codes:
            return conflict
    return None


def _overlap_conflict(cpt: str, conflicts: list[BillingConflict]) -> BillingConflict | None:
    for conflict in conflicts:
        if conflict.conflict_type == "overlap" and cpt in conflict.codes:
            return conflict
    return None


def build_ui_display(
    payload: BillingSessionInput,
    store: MetadataStore,
    *,
    eval_status: str,
    billable_codes: list[BillableCode],
    removed_codes: list[RemovedCode],
    billing_conflicts: list[BillingConflict],
    segments_by_cpt: dict[str, dict],
    active_cpts: set[str],
    detected_cpts: set[str],
    diagnosis_results: list[DiagnosisCptResult],
    icd_support: list[TranscriptIcdSupport],
    cpt_support: list[TranscriptCptSupport],
    resolved_primary: str | None,
    ranked_icds: list[str],
    total_timeline_minutes: float,
    ncci_pending_cpts: set[str],
    icd_pending_cpts: set[str],
) -> UiDisplay:
    max_units, conservative_units = calculate_provisional_unit_maps(
        active_cpts, segments_by_cpt, billing_conflicts, store
    )

    billable_by_cpt = {c.cpt_code: c for c in billable_codes}
    diagnosis_by_cpt = {r.cpt_code: r for r in diagnosis_results}
    cpt_support_by = {s.cpt_code: s for s in cpt_support}
    icd_support_by = {s.icd10_code: s for s in icd_support}
    removed_set = {r.cpt_code for r in removed_codes}

    cpt_cards: list[UiCptCard] = []
    units_display_total = 0

    ordered_cpts = sorted(
        detected_cpts,
        key=lambda c: min(segments_by_cpt.get(c, {}).get("sequences", [999])),
    )

    for cpt in ordered_cpts:
        if cpt in removed_set:
            continue

        seg = segments_by_cpt.get(cpt, {})
        minutes_exact = float(seg.get("minutes_exact", 0.0))
        billable = billable_by_cpt.get(cpt)
        if not billable and cpt not in active_cpts:
            continue

        pending_reasons = list(billable.pending_reasons) if billable else []
        is_confirmed = billable.billing_status == "confirmed" if billable else False
        units_current = billable.units if billable else 0

        overlap_pending = "temporal_overlap" in pending_reasons
        ncci_pending = "ncci_bundling" in pending_reasons
        icd_pending = "icd_medical_necessity" in pending_reasons

        if is_confirmed:
            units_display = units_current
            provisional = None
        elif overlap_pending:
            units_display = units_current
            provisional = None
        elif ncci_pending:
            units_display = max_units.get(cpt, units_current)
            provisional = UiProvisionalUnits(
                max=max_units.get(cpt, units_current),
                conservative=conservative_units.get(cpt, 0),
            )
        else:
            units_display = units_current
            provisional = None

        units_display_total += units_display

        description = store.description(cpt) if store.knows_cpt(cpt) else cpt
        short_label = _short_cpt_label(cpt, description, store)
        duration_display = format_duration_mmss(minutes_exact)

        card_style: str = "standard" if is_confirmed else "review"
        badge = None
        conflict_message = None
        conflict_with = None
        conflict_id = None
        modifiers: list[str] = []
        suggestions: list[UiSuggestion] = []
        actions = UiCptActions()

        ncci = _primary_ncci_conflict(cpt, billing_conflicts)
        overlap = _overlap_conflict(cpt, billing_conflicts)

        if ncci_pending and ncci:
            conflict_id = ncci.conflict_id
            conflict_with = (
                ncci.column_one_code
                if cpt == ncci.column_two_code
                else ncci.column_two_code or ncci.column_one_code
            )
            modifier_labels = ", ".join(f"-{m}" for m in MODIFIERS)
            applies_here = cpt == ncci.column_two_code or ncci.modifier_applies_to == cpt
            if applies_here:
                badge = "Modifier 59 Required"
                modifiers = list(MODIFIERS)
                conflict_message = (
                    f"NCCI bundle with Column 1 code {conflict_with}. If this was a distinct "
                    f"separate service, apply {modifier_labels} to {cpt}."
                )
            else:
                badge = "Review Required"
                col2 = ncci.column_two_code or conflict_with
                conflict_message = (
                    f"NCCI bundle with {conflict_with}. Column 2 ({col2}) may need "
                    f"{modifier_labels} if billed as distinct from Column 1."
                )
            actions = UiCptActions(reject_enabled=True, approve_enabled=True)
            suggestions.append(
                UiSuggestion(
                    type="ncci_bundling",
                    severity="action_required",
                    summary=conflict_message,
                    conflict_id=conflict_id,
                    modifiers=modifiers,
                )
            )
        elif overlap_pending and overlap:
            conflict_id = overlap.conflict_id
            others = [code for code in overlap.codes if code != cpt]
            conflict_with = others[0] if others else None
            badge = "Review Required"
            conflict_message = overlap.issue
            actions = UiCptActions(reject_enabled=True, approve_enabled=True)
            suggestions.append(
                UiSuggestion(
                    type="temporal_overlap",
                    severity="action_required",
                    summary=overlap.issue,
                    conflict_id=conflict_id,
                )
            )

        if icd_pending:
            diag = diagnosis_by_cpt.get(cpt)
            if diag and diag.guidance:
                suggestions.append(
                    UiSuggestion(
                        type="icd_medical_necessity",
                        severity="action_required",
                        summary=diag.guidance,
                    )
                )
                if not badge:
                    badge = "Review Required"

        support = cpt_support_by.get(cpt)
        if support and support.transcript_support == "weak" and support.guidance:
            suggestions.append(
                UiSuggestion(
                    type="transcript_weak",
                    severity="advisory",
                    summary=support.guidance,
                )
            )

        cpt_cards.append(
            UiCptCard(
                cpt_code=cpt,
                short_label=short_label,
                description=description,
                units_display=units_display,
                units_current=units_current,
                duration_display=duration_display,
                duration_minutes_exact=round(minutes_exact, 2),
                verification_status="confirmed" if is_confirmed else "pending_review",
                card_style=card_style,  # type: ignore[arg-type]
                badge=badge,
                conflict_message=conflict_message,
                conflict_with_cpt=conflict_with,
                conflict_id=conflict_id,
                modifiers_suggested=modifiers,
                actions=actions,
                provisional_units=provisional,
                suggestions=suggestions,
                sequences=list(seg.get("sequences", [])),
            )
        )

    icd_linked: dict[str, list[str]] = {icd: [] for icd in ranked_icds}
    crosswalk_linked: dict[str, list[str]] = {icd: [] for icd in ranked_icds}
    for result in diagnosis_results:
        if result.cpt_code not in active_cpts:
            continue
        if result.matched_icd:
            ranked_key = resolve_ranked_icd(result.matched_icd, ranked_icds)
            if ranked_key:
                icd_linked[ranked_key].append(result.cpt_code)
    for cpt in sorted(active_cpts):
        valid_set = store.icd10.get(cpt)
        if not valid_set:
            continue
        for icd in ranked_icds:
            if _icd_in_crosswalk(icd, valid_set):
                crosswalk_linked[icd].append(cpt)

    active_count = len(billable_codes)
    icd_cards: list[UiIcdCard] = []
    for icd in ranked_icds:
        support = icd_support_by.get(icd)
        label = (
            support.label
            if support and support.label
            else store.medexa_icd_display_label(icd)
        )
        matched = sorted(set(icd_linked.get(icd, [])))
        crosswalk = sorted(set(crosswalk_linked.get(icd, [])))
        linked = matched if matched else crosswalk
        hits = len(linked)
        crosswalk_summary = (
            f"On crosswalk for {hits} of {active_count} billed CPT(s)"
            if active_count
            else "No active billed CPTs"
        )

        icd_suggestions: list[UiIcdSuggestion] = []
        needs_review = False

        if support and support.transcript_support in ("weak", "no_lookup"):
            needs_review = True
            icd_suggestions.append(
                UiIcdSuggestion(
                    type="transcript_support",
                    severity="advisory" if support.transcript_support == "weak" else "action_required",
                    summary=support.guidance or f"Transcript support: {support.transcript_support}",
                )
            )

        for result in diagnosis_results:
            if (
                result.medical_necessity == "pending_icd_review"
                and result.cpt_code in icd_pending_cpts
                and result.guidance
            ):
                needs_review = True
                icd_suggestions.append(
                    UiIcdSuggestion(
                        type="medical_necessity",
                        severity="action_required",
                        summary=result.guidance,
                    )
                )

        icd_cards.append(
            UiIcdCard(
                icd10_code=icd,
                label=label or None,
                is_primary=icd == resolved_primary,
                transcript_support=support.transcript_support if support else "no_lookup",
                confidence_score=support.confidence_score if support else None,
                linked_cpt_codes=linked,
                crosswalk_summary=crosswalk_summary,
                verification_status="confirmed" if not needs_review else "pending_review",
                card_style="review" if needs_review else "standard",
                suggestions=icd_suggestions,
                acknowledge_enabled=needs_review,
            )
        )

    removed_section = [
        UiRemovedCard(
            cpt_code=r.cpt_code,
            reason=r.reason,
            details=r.details,
            auto_applied=r.auto_applied,
        )
        for r in removed_codes
    ]

    has_eight_minute = any(c.is_timed for c in billable_codes)

    return UiDisplay(
        session_header=UiSessionHeader(
            session_title="Therapeutic Therapy Session",
            status_label=_STATUS_LABELS.get(eval_status, eval_status),
            session_datetime=_format_session_datetime(payload.session_metadata.session_start),
            patient_id=payload.client_info.client_id,
            patient_name=payload.client_info.client_name,
            duration_display=format_session_duration(total_timeline_minutes),
            units_total=units_display_total,
        ),
        summary_cards=UiSummaryCards(
            session_time_display=format_session_duration(total_timeline_minutes),
            session_units_total=units_display_total,
            eight_minute_rule=has_eight_minute,
            threshold_note="",
        ),
        icd_cards=icd_cards,
        cpt_cards=cpt_cards,
        removed_section=removed_section,
    )
