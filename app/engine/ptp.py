from dataclasses import dataclass

from app.config import MODIFIERS
from app.engine.loader import MetadataStore
from app.models.output import (
    AutoAppliedChange,
    BillingConflict,
    ConflictRecommendation,
    RemovedCode,
    TherapistAction,
)


@dataclass
class PtpConflict:
    component: str
    primary: str
    modifier_indicator: str


def _find_conflicts(active_cpts: set[str], store: MetadataStore) -> list[PtpConflict]:
    conflicts: list[PtpConflict] = []
    seen: set[tuple[str, str]] = set()

    for cpt in active_cpts:
        ptp = store.ptp.get(cpt, {})
        for entry in ptp.get("bundled_into", []):
            primary = entry.get("primary_code")
            if primary in active_cpts:
                key = (cpt, primary)
                if key not in seen:
                    seen.add(key)
                    conflicts.append(
                        PtpConflict(
                            component=cpt,
                            primary=primary,
                            modifier_indicator=str(entry.get("modifier_indicator", "0")),
                        )
                    )
        for entry in ptp.get("bundles_others", []):
            bundled = entry.get("bundled_code")
            if bundled in active_cpts:
                key = (bundled, cpt)
                if key not in seen:
                    seen.add(key)
                    conflicts.append(
                        PtpConflict(
                            component=bundled,
                            primary=cpt,
                            modifier_indicator=str(entry.get("modifier_indicator", "0")),
                        )
                    )
    return conflicts


def _build_bypassable_conflict(conflict: PtpConflict, store: MetadataStore) -> BillingConflict:
    component = conflict.component
    primary = conflict.primary
    conflict_id = f"ncci_{component}_{primary}"
    comp_desc = store.description(component)
    prim_desc = store.description(primary)
    issue = (
        f"NCCI bundling conflict: {component} ({comp_desc}) and {primary} ({prim_desc}) "
        "are typically bundled. They may only be billed together if they were distinct, "
        "separate services performed at a separate time or on a separate body region."
    )
    recommendations = [
        ConflictRecommendation(
            action="apply_modifier",
            summary=(
                f"If {component} and {primary} were distinct separate services, apply "
                "modifier 59 (or XE/XP/XS/XU as appropriate) to the column-two code and "
                "document separate body regions and clinical intent."
            ),
            modifiers=list(MODIFIERS),
        ),
        ConflictRecommendation(
            action="remove_code",
            summary=(
                f"If the services were not distinct, remove {component} from the claim "
                f"and bill only {primary} (or vice versa based on what was actually performed)."
            ),
        ),
        ConflictRecommendation(
            action="document_distinct_service",
            summary=(
                "Ensure the note documents separate start/stop times, distinct clinical "
                "intent, and body region for each code."
            ),
        ),
    ]
    return BillingConflict(
        conflict_id=conflict_id,
        conflict_type="bypassable_bundle",
        codes=sorted([component, primary]),
        column_one_code=primary,
        column_two_code=component,
        column_one_description=prim_desc,
        column_two_description=comp_desc,
        modifier_applies_to=component,
        issue=issue,
        recommendations=recommendations,
        modifier_indicator=conflict.modifier_indicator,
    )


def resolve_ptp_conflicts(
    active_cpts: set[str],
    store: MetadataStore,
) -> tuple[
    set[str],
    list[RemovedCode],
    list[TherapistAction],
    list[AutoAppliedChange],
    list[BillingConflict],
]:
    removed: set[str] = set()
    removed_records: list[RemovedCode] = []
    therapist_actions: list[TherapistAction] = []
    changes: list[AutoAppliedChange] = []
    billing_conflicts: list[BillingConflict] = []

    conflicts = _find_conflicts(active_cpts, store)
    hard_components: set[str] = set()
    bypassable: list[PtpConflict] = []

    for conflict in conflicts:
        if conflict.modifier_indicator == "0":
            hard_components.add(conflict.component)
        else:
            bypassable.append(conflict)

    for component in sorted(hard_components):
        if component not in active_cpts:
            continue
        removed.add(component)
        detail = f"{component} bundled into primary code; hard NCCI edit (no modifier)."
        removed_records.append(
            RemovedCode(
                cpt_code=component,
                reason="hard_bundle",
                details=detail,
                auto_applied=True,
            )
        )
        changes.append(
            AutoAppliedChange(
                action="remove_hard_bundle",
                cpt_code=component,
                details=detail,
            )
        )

    for conflict in bypassable:
        if conflict.component in removed:
            continue
        billing_conflict = _build_bypassable_conflict(conflict, store)
        billing_conflicts.append(billing_conflict)
        therapist_actions.append(
            TherapistAction(
                type="bypassable_bundle",
                codes=billing_conflict.codes,
                modifier_indicator="1",
                modifiers_suggested=list(MODIFIERS),
                modifiers_not_applicable=[],
                guidance=billing_conflict.issue,
                conflict_id=billing_conflict.conflict_id,
            )
        )

    return removed, removed_records, therapist_actions, changes, billing_conflicts
