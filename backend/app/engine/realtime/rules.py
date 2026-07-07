from app.engine.conflict_evaluation import evaluate_cpt_conflicts
from app.engine.icd10 import validate_medical_necessity
from app.engine.loader import MetadataStore
from app.models.live import LiveCptRow
from app.models.output import BillingConflict, Issue


def active_cpt_codes(rows: list[LiveCptRow]) -> set[str]:
    return {
        row.cpt_code
        for row in rows
        if row.lifecycle not in ("removed", "error")
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
    """Evaluate add-on/PTP/MUE for the active CPT set (live mode: mark removed, no auto-delete)."""
    return evaluate_cpt_conflicts(active_cpts, store)


def icd_pending_for_cpt(
    cpt_code: str,
    icds: list[str],
    store: MetadataStore,
) -> tuple[bool, str]:
    if not icds:
        return True, "No ICD-10 codes detected on session — therapist should review and add diagnoses before billing."
    results, pending = validate_medical_necessity({cpt_code}, icds, store)
    if not results:
        return True, f"No medical necessity result for {cpt_code}."
    result = results[0]
    if result.medical_necessity in ("valid", "valid_no_crosswalk"):
        return False, result.guidance or ""
    if result.medical_necessity == "pending_icd_review":
        return True, result.guidance or "Detected ICDs require therapist review for medical necessity."
    if result.medical_necessity == "invalid":
        return True, result.guidance or f"Detected ICDs do not support {cpt_code} - therapist should review."
    return cpt_code in pending, result.guidance or ""


def unresolved_bypassable(conflicts: list[BillingConflict], resolved: set[str]) -> list[BillingConflict]:
    return [
        c
        for c in conflicts
        if c.conflict_type == "bypassable_bundle" and c.conflict_id not in resolved
    ]


def conflict_codes(conflict: BillingConflict) -> set[str]:
    return set(conflict.codes)
