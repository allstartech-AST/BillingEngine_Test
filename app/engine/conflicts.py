from app.models.output import BillingConflict, TherapistAction


def filter_billing_conflicts(
    conflicts: list[BillingConflict],
    active_cpts: set[str],
) -> list[BillingConflict]:
    """Drop stale conflicts that reference removed CPT codes."""
    filtered: list[BillingConflict] = []
    for conflict in conflicts:
        if conflict.conflict_type == "bypassable_bundle":
            if all(code in active_cpts for code in conflict.codes):
                filtered.append(conflict)
        elif conflict.conflict_type == "overlap":
            if any(code in active_cpts for code in conflict.codes):
                filtered.append(conflict)
        else:
            filtered.append(conflict)
    return filtered


def filter_therapist_actions(
    actions: list[TherapistAction],
    active_conflicts: list[BillingConflict],
) -> list[TherapistAction]:
    active_ids = {c.conflict_id for c in active_conflicts}
    return [a for a in actions if a.conflict_id in active_ids]
