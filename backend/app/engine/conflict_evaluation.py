"""Shared CPT-set conflict evaluation for batch pipeline and live sessions.

Evaluation order matches the batch pipeline: add-on → PTP → MUE.
Mode-specific side effects (auto-remove vs mark row removed) stay in callers.

Temporal overlap (``check_temporal_overlaps`` in pipeline.py) is batch-only: it
requires per-segment ``timestamp_start`` / ``timestamp_end`` on
``DetectedCptCode``. Live sessions record duration at CPT end, not overlapping
segment windows, so overlap detection is not applicable on the live path.
"""

from __future__ import annotations

from app.engine.aoc import validate_addon_codes
from app.engine.loader import MetadataStore
from app.engine.mue import check_mue_zero
from app.engine.ptp import (
    build_bypassable_conflict,
    classify_ptp_conflicts,
    ptp_hard_bundle_detail,
)
from app.models.output import BillingConflict, Issue


def evaluate_ptp_conflicts_live(
    active_cpts: set[str],
    store: MetadataStore,
) -> tuple[list[BillingConflict], list[Issue], set[str]]:
    """Classify PTP edits for live mode: issues + bypassable conflicts, no auto-delete."""
    hard, bypassable = classify_ptp_conflicts(active_cpts, store)
    hard_removed = {conflict.component for conflict in hard}
    issues: list[Issue] = []
    for conflict in hard:
        issues.append(
            Issue(
                severity="error",
                code=conflict.component,
                message=ptp_hard_bundle_detail(conflict, mode="live"),
            )
        )

    billing_conflicts: list[BillingConflict] = []
    for conflict in bypassable:
        if conflict.component in hard_removed:
            continue
        billing_conflicts.append(build_bypassable_conflict(conflict, store))

    return billing_conflicts, issues, hard_removed


def evaluate_cpt_conflicts(
    active_cpts: set[str],
    store: MetadataStore,
) -> tuple[list[BillingConflict], list[Issue], set[str]]:
    """Add-on → PTP → MUE scan shared by live incremental refresh."""
    issues: list[Issue] = []
    hard_removed: set[str] = set()
    billing_conflicts: list[BillingConflict] = []

    _, addon_records, _, _ = validate_addon_codes(active_cpts, store)
    for record in addon_records:
        hard_removed.add(record.cpt_code)
        issues.append(
            Issue(
                severity="error",
                code=record.cpt_code,
                message=record.details,
            )
        )

    remaining = active_cpts - hard_removed
    ptp_conflicts, ptp_issues, ptp_hard = evaluate_ptp_conflicts_live(remaining, store)
    hard_removed |= ptp_hard
    issues.extend(ptp_issues)
    billing_conflicts.extend(ptp_conflicts)

    mue_zero, mue_records, _, mue_issues = check_mue_zero(active_cpts - hard_removed, store)
    hard_removed |= mue_zero
    for record in mue_records:
        issues.append(
            Issue(severity="error", code=record.cpt_code, message=record.details)
        )
    issues.extend(mue_issues)

    return billing_conflicts, issues, hard_removed
