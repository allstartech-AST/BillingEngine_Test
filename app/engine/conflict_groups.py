from collections import defaultdict

from app.models.output import BillingConflict, ConflictGroup


def group_billing_conflicts(conflicts: list[BillingConflict]) -> list[ConflictGroup]:
    """Cluster conflicts for therapist UX: overlaps first, then NCCI hubs."""
    groups: list[ConflictGroup] = []
    overlap_conflicts = [c for c in conflicts if c.conflict_type == "overlap"]
    ncci_conflicts = [c for c in conflicts if c.conflict_type == "bypassable_bundle"]

    if overlap_conflicts:
        groups.append(
            ConflictGroup(
                group_id="overlap_all",
                group_type="temporal_overlap",
                anchor_cpt=None,
                priority=1,
                conflict_ids=[c.conflict_id for c in overlap_conflicts],
                summary=(
                    f"{len(overlap_conflicts)} segment time overlap(s) - "
                    "assign distinct service windows before billing."
                ),
            )
        )

    hub_map: dict[str, list[BillingConflict]] = defaultdict(list)
    pair_conflicts: list[BillingConflict] = []
    for conflict in ncci_conflicts:
        hub = conflict.column_one_code
        if hub:
            hub_map[hub].append(conflict)
        else:
            pair_conflicts.append(conflict)

    for hub, hub_conflicts in sorted(hub_map.items()):
        bundled = sorted(
            {
                c.column_two_code
                for c in hub_conflicts
                if c.column_two_code
            }
        )
        bundled_text = ", ".join(bundled) if bundled else "related codes"
        groups.append(
            ConflictGroup(
                group_id=f"ncci_hub_{hub}",
                group_type="ncci_hub",
                anchor_cpt=hub,
                priority=2,
                conflict_ids=[c.conflict_id for c in hub_conflicts],
                summary=(
                    f"NCCI bundling - Column 1 {hub} conflicts with "
                    f"{len(hub_conflicts)} service(s): {bundled_text}."
                ),
            )
        )

    for conflict in pair_conflicts:
        codes = " + ".join(conflict.codes)
        groups.append(
            ConflictGroup(
                group_id=f"ncci_pair_{conflict.conflict_id}",
                group_type="ncci_pair",
                anchor_cpt=conflict.column_one_code,
                priority=2,
                conflict_ids=[conflict.conflict_id],
                summary=f"NCCI bundling conflict between {codes}.",
            )
        )

    other = [c for c in conflicts if c.conflict_type not in ("overlap", "bypassable_bundle")]
    if other:
        groups.append(
            ConflictGroup(
                group_id="other_conflicts",
                group_type="other",
                anchor_cpt=None,
                priority=3,
                conflict_ids=[c.conflict_id for c in other],
                summary=f"{len(other)} additional conflict(s) require review.",
            )
        )

    return sorted(groups, key=lambda group: (group.priority, group.group_id))
