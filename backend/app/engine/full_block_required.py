"""Category B — full_block_required unit calculator."""

from __future__ import annotations

from app.engine.cpt_aoc_info import AddOnCodeStore
from app.engine.eight_minute import SegmentUnits
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore, get_category_rule_store

RULE = "full_block_required"


def _calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
    aoc_store: AddOnCodeStore,
) -> list[SegmentUnits]:
    """
    Category B — full_block_required.

    Base codes: each unit requires the full CPT-defined block_minutes;
    no partial credit. 1 unit if minutes >= block_minutes, else 0.

    Add-on codes: validated via AOCStore against its declared parent
    (must be present in this same active_segments set and be listed in the
    parent's addonCodesAllowed); orphaned/invalid add-ons are skipped.
    Valid add-ons bill full completed increments only —
    units = minutes // increment_minutes — with any remainder discarded.
    """
    results: list[SegmentUnits] = []

    for cpt_code, data in active_segments.items():
        sequences = data.get("sequences", [])
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        billed = data.get("minutes_billed", int(exact))
        minutes = data.get("minutes", 0.0)

        if aoc_store.is_addon(cpt_code):
            if not aoc_store.is_valid_addon(cpt_code, active_segments):
                continue  # orphaned/invalid add-on — parent not billed here

            parent = aoc_store.get_parent_code(cpt_code)
            if not parent or category_store.get_rule(parent) != RULE:
                continue  # add-on's parent is not a full_block_required code

            increment = aoc_store.get_increment_minutes(cpt_code)
            units = int(minutes // increment) if increment else 0

            results.append(
                SegmentUnits(
                    cpt_code=cpt_code,
                    minutes_exact=exact,
                    minutes_billed=billed,
                    units=units,
                    method="full_block_required_addon",
                    sequences=sequences,
                )
            )
            continue

        if category_store.get_rule(cpt_code) != RULE:
            continue

        block_minutes = category_store.get_block_minutes(cpt_code)
        units = 1 if block_minutes and minutes >= block_minutes else 0

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
    aoc_store = AddOnCodeStore.from_metadata(store)
    return _calculate_units(segments_by_cpt, category_store, aoc_store)
