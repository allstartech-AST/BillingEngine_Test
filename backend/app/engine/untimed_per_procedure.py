"""Category D — untimed_per_procedure unit calculator."""

from __future__ import annotations

from app.engine.eight_minute import SegmentUnits
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore, get_category_rule_store

RULE = "untimed_per_procedure"


def _calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
) -> list[SegmentUnits]:
    """
    Category D — untimed_per_procedure.

    No time-based units; bills once each time the procedure is performed —
    units scale with occurrence count.
    """
    results: list[SegmentUnits] = []

    for cpt_code, data in active_segments.items():
        if category_store.get_rule(cpt_code) != RULE:
            continue

        sequences = data.get("sequences", [])
        count = len(sequences)
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        billed = data.get("minutes_billed", int(exact))
        units = max(count, 1) if count else 0

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
