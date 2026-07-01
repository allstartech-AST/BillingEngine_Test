from app.engine.aoc import validate_addon_codes
from app.engine.icd10 import validate_medical_necessity
from app.engine.loader import MetadataStore
from app.engine.mue import check_mue_zero
from app.engine.ptp import PtpConflict, _build_bypassable_conflict, _find_conflicts
from app.models.live import LiveCptRow
from app.models.output import BillingConflict, Issue


def active_cpt_codes(rows: list[LiveCptRow]) -> set[str]:
    return {
        row.cpt_code
        for row in rows
        if row.lifecycle not in ("removed", "error")
    }


def billable_cpt_codes(rows: list[LiveCptRow]) -> set[str]:
    return {
        row.cpt_code
        for row in rows
        if row.lifecycle not in ("removed", "error", "manual_billing")
    }


def _issue_removal_reason(issue: Issue) -> str:
    msg = issue.message.lower()
    if "mue limit is 0" in msg:
        return "mue_zero"
    if "hard ncci" in msg or "no modifier" in msg:
        return "hard_bundle"
    if "add-on" in msg or "addon" in msg:
        return "missing_addon_parent"
    return "blocked"


def incremental_conflicts(
    active_cpts: set[str],
    store: MetadataStore,
) -> tuple[list[BillingConflict], list[Issue], set[str]]:
    """Evaluate PTP/AOC/MUE for the current active CPT set (live mode: no auto-remove)."""
    issues: list[Issue] = []
    hard_removed: set[str] = set()
    billing_conflicts: list[BillingConflict] = []

    addon_removed, addon_records, _, _ = validate_addon_codes(active_cpts, store)
    for record in addon_records:
        hard_removed.add(record.cpt_code)
        issues.append(
            Issue(
                severity="error",
                code=record.cpt_code,
                message=record.details,
            )
        )

    mue_zero, mue_records, _, mue_issues = check_mue_zero(active_cpts - hard_removed, store)
    hard_removed |= mue_zero
    for record in mue_records:
        issues.append(
            Issue(severity="error", code=record.cpt_code, message=record.details)
        )
    issues.extend(mue_issues)

    remaining = active_cpts - hard_removed
    ptp_raw = _find_conflicts(remaining, store)
    for conflict in ptp_raw:
        if conflict.modifier_indicator == "0":
            hard_removed.add(conflict.component)
            detail = (
                f"{conflict.component} bundled into {conflict.primary}; "
                "hard NCCI edit (no modifier)."
            )
            issues.append(
                Issue(severity="error", code=conflict.component, message=detail)
            )
        else:
            billing_conflicts.append(_build_bypassable_conflict(conflict, store))

    return billing_conflicts, issues, hard_removed


def icd_pending_for_cpt(
    cpt_code: str,
    icds: list[str],
    store: MetadataStore,
) -> tuple[bool, str]:
    if not icds:
        return True, "No ICD-10 codes on session — add diagnoses before billing."
    results, pending = validate_medical_necessity({cpt_code}, icds, store)
    if not results:
        return True, f"No medical necessity result for {cpt_code}."
    result = results[0]
    if result.medical_necessity in ("valid", "valid_no_crosswalk"):
        return False, result.guidance or ""
    if result.medical_necessity == "pending_icd_review":
        return True, result.guidance or "ICD medical necessity requires therapist review."
    if result.medical_necessity == "invalid":
        return True, result.guidance or f"Submitted ICDs do not support {cpt_code}."
    return cpt_code in pending, result.guidance or ""


def unresolved_bypassable(conflicts: list[BillingConflict], resolved: set[str]) -> list[BillingConflict]:
    return [
        c
        for c in conflicts
        if c.conflict_type == "bypassable_bundle" and c.conflict_id not in resolved
    ]


def conflict_codes(conflict: BillingConflict) -> set[str]:
    return set(conflict.codes)
