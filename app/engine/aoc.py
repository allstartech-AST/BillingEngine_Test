from app.engine.loader import MetadataStore
from app.models.output import AutoAppliedChange, Issue, RemovedCode


def validate_addon_codes(
    active_cpts: set[str],
    store: MetadataStore,
) -> tuple[set[str], list[RemovedCode], list[AutoAppliedChange], list[Issue]]:
    removed: set[str] = set()
    removed_records: list[RemovedCode] = []
    changes: list[AutoAppliedChange] = []
    issues: list[Issue] = []

    for cpt in sorted(active_cpts):
        rec = store.aoc.get(cpt)
        if not rec or not rec.get("isAddonCode"):
            continue
        parent = rec.get("parentCode")
        if parent and parent not in active_cpts:
            removed.add(cpt)
            detail = f"Add-on {cpt} requires parent {parent} on same session."
            removed_records.append(
                RemovedCode(
                    cpt_code=cpt,
                    reason="missing_addon_parent",
                    details=detail,
                    auto_applied=True,
                )
            )
            changes.append(
                AutoAppliedChange(
                    action="remove_addon",
                    cpt_code=cpt,
                    details=detail,
                )
            )

    for cpt in sorted(active_cpts - removed):
        rec = store.aoc.get(cpt)
        if not rec:
            continue
        allowed = rec.get("addonCodesAllowed") or []
        for addon in allowed:
            if addon in store.general and addon not in active_cpts:
                issues.append(
                    Issue(
                        severity="info",
                        code=cpt,
                        message=(
                            f"Primary {cpt} allows add-on {addon} but it was not detected."
                        ),
                    )
                )

    return removed, removed_records, changes, issues
