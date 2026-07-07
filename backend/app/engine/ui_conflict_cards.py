"""Shared NCCI / overlap conflict presentation for batch and live UI cards."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import MODIFIERS
from app.models.output import BillingConflict, UiCptActions, UiSuggestion


def primary_ncci_conflict(
    cpt: str,
    conflicts: list[BillingConflict],
) -> BillingConflict | None:
    for conflict in conflicts:
        if conflict.conflict_type != "bypassable_bundle":
            continue
        if cpt in conflict.codes:
            return conflict
    return None


def overlap_conflict(
    cpt: str,
    conflicts: list[BillingConflict],
) -> BillingConflict | None:
    for conflict in conflicts:
        if conflict.conflict_type == "overlap" and cpt in conflict.codes:
            return conflict
    return None


def modifier_labels() -> str:
    return ", ".join(f"-{m}" for m in MODIFIERS)


@dataclass(frozen=True)
class NcciPresentation:
    badge: str | None
    conflict_message: str | None
    conflict_with: str | None
    conflict_id: str | None
    modifiers: list[str]
    actions: UiCptActions
    suggestion: UiSuggestion | None


def build_batch_ncci_presentation(
    cpt: str,
    ncci: BillingConflict,
    *,
    ncci_pending: bool,
) -> NcciPresentation | None:
    if not ncci_pending:
        return None

    conflict_id = ncci.conflict_id
    conflict_with = (
        ncci.column_one_code
        if cpt == ncci.column_two_code
        else ncci.column_two_code or ncci.column_one_code
    )
    labels = modifier_labels()
    applies_here = cpt == ncci.column_two_code or ncci.modifier_applies_to == cpt
    if applies_here:
        badge = "Modifier 59 Required"
        modifiers = list(MODIFIERS)
        conflict_message = (
            f"NCCI bundle with Column 1 code {conflict_with}. If this was a distinct "
            f"separate service, apply {labels} to {cpt}."
        )
    else:
        badge = "Review Required"
        col2 = ncci.column_two_code or conflict_with
        modifiers = []
        conflict_message = (
            f"NCCI bundle with {conflict_with}. Column 2 ({col2}) may need "
            f"{labels} if billed as distinct from Column 1."
        )

    actions = UiCptActions(reject_enabled=True, approve_enabled=True)
    suggestion = UiSuggestion(
        type="ncci_bundling",
        severity="action_required",
        summary=conflict_message,
        conflict_id=conflict_id,
        modifiers=modifiers,
    )
    return NcciPresentation(
        badge=badge,
        conflict_message=conflict_message,
        conflict_with=conflict_with,
        conflict_id=conflict_id,
        modifiers=modifiers,
        actions=actions,
        suggestion=suggestion,
    )


def build_live_ncci_presentation(
    cpt: str,
    ncci: BillingConflict,
    *,
    include_conflict: bool,
    existing_badge: str | None = None,
) -> NcciPresentation | None:
    if not include_conflict:
        return None

    conflict_with = (
        ncci.column_one_code
        if cpt == ncci.column_two_code
        else ncci.column_two_code or ncci.column_one_code
    )
    labels = modifier_labels()
    applies_here = cpt == ncci.column_two_code or ncci.modifier_applies_to == cpt
    indicator = ncci.modifier_indicator or "1"
    modifiers: list[str] = []
    conflict_message: str | None = None
    conflict_id: str | None = None
    badge: str | None = None

    if applies_here:
        badge = "Modifier 59 Required"
        modifiers = list(MODIFIERS)
        ai_enriched_applied = False
        if ncci.ai_enriched:
            for rec in ncci.recommendations:
                if rec.action == "apply_modifier":
                    modifiers = rec.modifiers or []
                    conflict_message = rec.summary
                    ai_enriched_applied = True
                    break
        if not ai_enriched_applied:
            conflict_message = (
                f"NCCI bundle with Column 1 code {conflict_with} (modifier indicator {indicator}). "
                f"If this was a distinct separate service, apply {labels} to {cpt}."
            )
        conflict_id = ncci.conflict_id
        actions = UiCptActions(approve_enabled=True, reject_enabled=True)
    else:
        badge = existing_badge or "Review Required"
        col2 = ncci.column_two_code or conflict_with
        conflict_message = (
            f"NCCI bundle with {conflict_with} (modifier indicator {indicator}). "
            f"Please resolve this conflict on the Column 2 code ({col2})."
        )
        actions = UiCptActions()

    suggestion = UiSuggestion(
        type="ncci_bundling",
        severity="action_required",
        summary=conflict_message or "",
        conflict_id=conflict_id,
        modifiers=modifiers,
    )
    return NcciPresentation(
        badge=badge,
        conflict_message=conflict_message,
        conflict_with=conflict_with,
        conflict_id=conflict_id,
        modifiers=modifiers,
        actions=actions,
        suggestion=suggestion,
    )


def build_overlap_presentation(
    cpt: str,
    overlap: BillingConflict,
) -> NcciPresentation:
    conflict_id = overlap.conflict_id
    others = [code for code in overlap.codes if code != cpt]
    conflict_with = others[0] if others else None
    actions = UiCptActions(reject_enabled=True, approve_enabled=True)
    suggestion = UiSuggestion(
        type="temporal_overlap",
        severity="action_required",
        summary=overlap.issue,
        conflict_id=conflict_id,
    )
    return NcciPresentation(
        badge="Review Required",
        conflict_message=overlap.issue,
        conflict_with=conflict_with,
        conflict_id=conflict_id,
        modifiers=[],
        actions=actions,
        suggestion=suggestion,
    )
