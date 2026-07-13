"""Category I — untimed_per_encounter unit calculator."""

from __future__ import annotations

from app.engine.eight_minute import SegmentUnits
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore, get_category_rule_store

RULE = "untimed_per_encounter"


def _calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
) -> list[SegmentUnits]:
    """
    Category I — untimed_per_encounter.

    No time-based units; bills exactly 1 unit if the code occurs in the
    patient encounter (evaluation, re-evaluation, or non-E/M encounter
    service), regardless of duration or repeat occurrences.
    """
    results: list[SegmentUnits] = []

    for cpt_code, data in active_segments.items():
        if category_store.get_rule(cpt_code) != RULE:
            continue

        sequences = data.get("sequences", [])
        count = len(sequences)
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        billed = data.get("minutes_billed", int(exact))
        units = 1 if count else 0

        results.append(
            SegmentUnits(
                cpt_code=cpt_code,
                minutes_exact=exact,
                minutes_billed=billed,
                units=units,
                method=RULE,
                sequences=sequences,
            )
        )

    return results


def calculate_units(
    segments_by_cpt: dict[str, dict],
    store: MetadataStore,
) -> list[SegmentUnits]:
    """Public wrapper that resolves stores from MetadataStore."""
    category_store = get_category_rule_store()
    return _calculate_units(segments_by_cpt, category_store)
