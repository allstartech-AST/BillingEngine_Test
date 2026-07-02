from app.engine.loader import MetadataStore
from app.models.output import AutoAppliedChange, Issue, RemovedCode


def check_mue_zero(
    active_cpts: set[str],
    store: MetadataStore,
) -> tuple[set[str], list[RemovedCode], list[AutoAppliedChange], list[Issue]]:
    removed: set[str] = set()
    removed_records: list[RemovedCode] = []
    changes: list[AutoAppliedChange] = []
    issues: list[Issue] = []

    for cpt in sorted(active_cpts):
        mue = store.mue.get(cpt)
        if mue is None:
            issues.append(
                Issue(
                    severity="info",
                    code=cpt,
                    message=f"No MUE data for {cpt}.",
                )
            )
            continue
        limit = mue.get("limit")
        if limit is None:
            issues.append(
                Issue(
                    severity="info",
                    code=cpt,
                    message=f"MUE limit unknown for {cpt}.",
                )
            )
        elif limit == 0:
            removed.add(cpt)
            cpt_name = store.medexa.get(cpt, {}).get("label") or store.description(cpt) or cpt
            detail = f"MUE limit for {cpt_name} is zero."
            removed_records.append(
                RemovedCode(
                    cpt_code=cpt,
                    reason="mue_zero",
                    details=detail,
                    auto_applied=True,
                )
            )
            changes.append(
                AutoAppliedChange(
                    action="remove_mue_zero",
                    cpt_code=cpt,
                    details=detail,
                )
            )
        elif mue.get("adjudication") == 3:
            cpt_name = store.medexa.get(cpt, {}).get("label") or store.description(cpt) or cpt
            issues.append(
                Issue(
                    severity="info",
                    code=cpt,
                    message=f"MUE adjudication indicator 3 present for {cpt_name}; maximum limit is {limit}.",
                )
            )

    return removed, removed_records, changes, issues


def apply_mue_cap(
    cpt_code: str,
    units: int,
    store: MetadataStore,
) -> tuple[int, int | None]:
    mue = store.mue.get(cpt_code)
    if not mue:
        return units, None
    limit = mue.get("limit")
    if limit is None:
        return units, None
    return min(units, int(limit)), int(limit)
