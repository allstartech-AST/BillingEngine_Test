from datetime import datetime, timezone

from app.engine.billing_rule_catalog import (
    live_rule_meta,
    rule_badge_label,
)
from app.engine.eight_minute import EIGHT_MINUTE_RULE
from app.engine.icd10 import _icd_in_crosswalk
from app.engine.loader import MetadataStore
from app.engine.realtime.rules import icd_pending_for_cpt, unresolved_bypassable
from app.engine.ui_display import (
    _short_cpt_label,
    format_duration_mmss,
    format_session_duration,
)
from app.models.live import LiveCptRow, LiveSessionState
from app.models.output import (
    BillingConflict,
    UiCptActions,
    UiCptCard,
    UiCptTimerMeta,
    UiDisplay,
    UiIcdCard,
    UiRemovedCard,
    UiSessionHeader,
    UiSummaryCards,
    UiSuggestion,
)

_STATUS_LABELS = {
    "active": "Live Session",
    "ended": "Session Ended",
    "blocked": "Blocked",
}

_REMOVAL_LABELS = {
    "mue_zero": "MUE limit zero — not billable",
    "hard_bundle": "NCCI hard edit (modifier indicator 0)",
    "missing_addon_parent": "Orphan add-on code",
    "blocked": "Blocked from claim",
}


from app.engine.ui_conflict_cards import (
    build_live_ncci_presentation,
    ncci_conflicts_for_cpt,
)


def visible_live_cpt_rows(cpts: list[LiveCptRow]) -> list[LiveCptRow]:
    return [r for r in cpts if r.lifecycle not in ("removed", "error")]


def _visible_rows(cpts: list[LiveCptRow]) -> list[LiveCptRow]:
    return visible_live_cpt_rows(cpts)


def _build_icd_card(state: LiveSessionState, store: MetadataStore) -> list[UiIcdCard]:
    ranked_icds = state.icds
    if not ranked_icds:
        return []

    active_cpts = {
        r.cpt_code
        for r in state.cpts
        if r.lifecycle not in ("removed", "error")
    }
    active_count = len(active_cpts)

    labels: list[str] = []
    crosswalk_by_icd: dict[str, list[str]] = {}
    for icd in ranked_icds:
        label = store.medexa_icd_display_label(icd)
        if label:
            labels.append(f"{icd} ({label})")
        else:
            labels.append(icd)
        linked: list[str] = []
        for cpt in sorted(active_cpts):
            valid_set = store.icd10.get(cpt)
            if valid_set and _icd_in_crosswalk(icd, valid_set):
                linked.append(cpt)
        crosswalk_by_icd[icd] = linked

    all_linked = sorted({cpt for codes in crosswalk_by_icd.values() for cpt in codes})
    hits = len(all_linked)
    crosswalk_summary = (
        f"{len(ranked_icds)} diagnosis(es) detected · supports {hits} of {active_count} CPT(s)"
        if active_count
        else f"{len(ranked_icds)} diagnosis(es) detected · no CPTs yet"
    )
    needs_review = active_count > 0 and hits < active_count

    return [
        UiIcdCard(
            icd10_code=ranked_icds[0],
            detected_icd10_codes=list(ranked_icds),
            label=" · ".join(labels),
            is_primary=True,
            transcript_support="detected",
            confidence_score=None,
            linked_cpt_codes=all_linked,
            crosswalk_summary=crosswalk_summary,
            verification_status="confirmed" if not needs_review else "pending_review",
            card_style="review" if needs_review else "standard",
            suggestions=[],
            acknowledge_enabled=False,
        )
    ]


def _timer_meta_for_row(row: LiveCptRow, state: LiveSessionState, store: MetadataStore) -> UiCptTimerMeta:
    meta = live_rule_meta(row.cpt_code, store)
    return UiCptTimerMeta(
        timer_mode=meta.timer_mode,
        block_minutes=meta.block_minutes,
        increment_minutes=meta.increment_minutes,
        time_band_min=meta.time_band_min,
        time_band_max=meta.time_band_max,
        area_threshold_sq_cm=meta.area_threshold_sq_cm,
        increment_sq_cm=meta.increment_sq_cm,
        session_billing_rule=state.billing_rule,
        area_sq_cm=row.area_sq_cm,
        occurrence_count=row.occurrence_count,
        auto_units=meta.timer_mode in ("duration_units", "occurrence", "area"),
    )


def build_live_ui_display(state: LiveSessionState, store: MetadataStore) -> UiDisplay:
    resolved = set(state.resolved_conflicts)
    open_conflicts = unresolved_bypassable(state.conflicts, resolved)

    completed_rows = [r for r in state.cpts if r.lifecycle == "completed"]
    timed_completed = [r for r in completed_rows if r.billing_rule == EIGHT_MINUTE_RULE]
    total_minutes = sum(r.duration_minutes_exact for r in completed_rows)
    pooled_minutes = sum(r.minutes_billed for r in timed_completed)
    units_total = sum(
        r.units
        for r in completed_rows
        if r.billing_status not in ("removed", "error")
    )

    cpt_cards: list[UiCptCard] = []
    for row in _visible_rows(state.cpts):
        description = store.description(row.cpt_code)
        short_label = _short_cpt_label(row.cpt_code, description, store)
        rule_meta = live_rule_meta(row.cpt_code, store)
        timer_meta = _timer_meta_for_row(row, state, store)
        is_pending = row.billing_status == "pending_therapist_review"
        is_detected = row.lifecycle in ("detected", "pending_start", "manual_billing")
        is_completed = row.lifecycle == "completed"
        is_open = row.lifecycle in ("detected", "pending_start", "running", "paused", "manual_billing")

        if is_completed:
            units_display = row.units
            duration_display = format_duration_mmss(row.duration_minutes_exact)
        elif is_open:
            units_display = row.units if row.units else 0
            duration_display = "—"
        else:
            units_display = 0
            duration_display = "—"

        ncci_list = ncci_conflicts_for_cpt(row.cpt_code, open_conflicts)
        badge = None
        conflict_message = None
        conflict_with = None
        conflict_id = None
        modifiers: list[str] = []
        actions = UiCptActions()
        suggestions: list[UiSuggestion] = []
        card_style = "standard"
        verification = "confirmed"

        if row.lifecycle == "ai_suggested":
            badge = "✨ AI Suggested"
            card_style = "ai_suggested"
            verification = "pending_review"
            suggestions.append(
                UiSuggestion(
                    type="ai_suggested",
                    severity="action_required",
                    summary=getattr(row, "ai_reasoning", "AI detected this service based on the transcript."),
                    conflict_id=f"ai_suggest_{row.cpt_code}"
                )
            )
        elif row.billing_rule == EIGHT_MINUTE_RULE:
            if state.billing_rule == "ama_rule_of_8":
                badge = badge or "AMA Rule of 8"
                if is_detected or row.lifecycle == "pending_start":
                    suggestions.append(
                        UiSuggestion(
                            type="rule_applicability",
                            severity="advisory",
                            summary="AMA Rule of 8 applies — end this CPT with duration to calculate units.",
                        )
                    )
                elif is_completed:
                    suggestions.append(
                        UiSuggestion(
                            type="units_calculated",
                            severity="advisory",
                            summary=(
                                f"{row.units} unit(s) under AMA Rule of 8 "
                                f"({row.duration_minutes_exact:g} min recorded for this code)."
                            ),
                        )
                    )
            else:
                badge = badge or "8-Minute Rule"
                if is_detected or row.lifecycle == "pending_start":
                    suggestions.append(
                        UiSuggestion(
                            type="rule_applicability",
                            severity="advisory",
                            summary="8-minute rule applies — end this CPT with duration to calculate units.",
                        )
                    )
                elif is_completed:
                    suggestions.append(
                        UiSuggestion(
                            type="units_calculated",
                            severity="advisory",
                            summary=(
                                f"{row.units} unit(s) after pooled 8-minute rule "
                                f"({row.duration_minutes_exact:g} min recorded for this code)."
                            ),
                        )
                    )
        elif not badge:
            badge = rule_badge_label(rule_meta)
            summary = row.rule_message or rule_badge_label(rule_meta)
            suggestions.append(
                UiSuggestion(type="manual_billing", severity="advisory", summary=summary)
            )

        if getattr(row, "ai_supported", True) is False:
            badge = badge or "Transcript Weak"
            card_style = "review"
            verification = "pending_review"
            suggestions.append(
                UiSuggestion(
                    type="transcript_weak",
                    severity="action_required",
                    summary=f"AI Detection: This CPT code may not be supported by the transcript. {getattr(row, 'ai_reasoning', '')}",
                    conflict_id=f"ai_reject_{row.cpt_code}",
                )
            )

        ai_verified = False
        ai_confidence = None
        if row.lifecycle != "ai_suggested" and getattr(row, "ai_supported", None) is True:
            ai_verified = True
            ai_confidence = getattr(row, "ai_confidence", None)
            if ai_confidence is None or ai_confidence <= 0:
                ai_confidence = 100

        if ncci_list and (is_pending or is_detected or is_completed):
            card_style = "review"
            verification = "pending_review"
            for ncci_conflict in ncci_list:
                presentation = build_live_ncci_presentation(
                    row.cpt_code,
                    ncci_conflict,
                    include_conflict=True,
                    existing_badge=badge,
                )
                if not presentation:
                    continue
                if presentation.badge and not badge:
                    badge = presentation.badge
                if presentation.suggestion:
                    suggestions.append(presentation.suggestion)
                if len(ncci_list) == 1:
                    conflict_with = presentation.conflict_with
                    conflict_message = presentation.conflict_message
                    conflict_id = presentation.conflict_id
                    modifiers = presentation.modifiers
                    actions = presentation.actions

        icd_guidance = row.icd_guidance
        if not icd_guidance and "icd_medical_necessity" in row.pending_reasons:
            _, icd_guidance = icd_pending_for_cpt(row.cpt_code, state.icds, store)

        if "icd_medical_necessity" in row.pending_reasons:
            card_style = "review"
            verification = "pending_review"
            if icd_guidance:
                suggestions.append(
                    UiSuggestion(
                        type="icd_medical_necessity",
                        severity="action_required",
                        summary=icd_guidance,
                    )
                )
            if not badge or badge in ("8-Minute Rule", "AMA Rule of 8", "Manual / Occurrence"):
                badge = "Review Required"
        elif icd_guidance and is_completed and "crosswalk" in icd_guidance.lower():
            suggestions.append(
                UiSuggestion(type="icd_medical_necessity", severity="advisory", summary=icd_guidance)
            )

        elif row.lifecycle == "running":
            suggestions.append(
                UiSuggestion(
                    type="awaiting_end",
                    severity="advisory",
                    summary="Awaiting duration — end this CPT to calculate units.",
                )
            )

        is_addon = False
        parent_cpt_code = None
        if row.cpt_code in store.aoc and store.aoc[row.cpt_code].get("isAddonCode"):
            is_addon = True
            parent_cpt_code = store.aoc[row.cpt_code].get("parentCode")

        cpt_cards.append(
            UiCptCard(
                cpt_code=row.cpt_code,
                short_label=short_label,
                description=description,
                units_display=units_display,
                units_current=row.units,
                duration_display=duration_display,
                duration_minutes_exact=row.duration_minutes_exact,
                verification_status=verification,  # type: ignore[arg-type]
                card_style=card_style,  # type: ignore[arg-type]
                badge=badge or rule_badge_label(rule_meta),
                ai_verified=ai_verified,
                ai_confidence=ai_confidence,
                conflict_message=conflict_message,
                conflict_with_cpt=conflict_with,
                conflict_id=conflict_id,
                modifiers_suggested=modifiers,
                actions=actions,
                suggestions=suggestions,
                sequences=[row.sequence],
                billing_rule=row.billing_rule,
                applied_modifiers=row.applied_modifiers,
                is_addon=is_addon,
                parent_cpt_code=parent_cpt_code,
                timer_meta=timer_meta,
            )
        )

    icd_cards = _build_icd_card(state, store)

    removed_section = [
        UiRemovedCard(
            cpt_code=r.cpt_code,
            reason=_REMOVAL_LABELS.get(r.removal_reason, "removed"),
            details=r.message or "Removed from billable set.",
            auto_applied=True,
        )
        for r in state.cpts
        if r.lifecycle == "removed"
    ]

    has_eight_minute = any(
        r.billing_rule == EIGHT_MINUTE_RULE for r in state.cpts if r.lifecycle != "removed"
    )

    pool_note = ""

    now = datetime.now(timezone.utc).strftime("%B %d, %I:%M %p").replace(" 0", " ")

    return UiDisplay(
        session_header=UiSessionHeader(
            session_title="Live Therapy Session",
            status_label=_STATUS_LABELS.get(state.status, state.status),
            session_datetime=now,
            patient_id=state.client_info.client_id,
            patient_name=state.client_info.client_name,
            duration_display=format_session_duration(total_minutes),
            units_total=units_total,
        ),
        summary_cards=UiSummaryCards(
            session_time_display=format_session_duration(total_minutes),
            session_units_total=units_total,
            eight_minute_rule=has_eight_minute,
            billing_rule=state.billing_rule,
            threshold_note=pool_note or state.session_message,
        ),
        icd_cards=icd_cards,
        cpt_cards=cpt_cards,
        removed_section=removed_section,
    )
