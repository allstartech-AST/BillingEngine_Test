from __future__ import annotations

from app.engine.cpt_aoc_info import AddOnCodeStore
from app.engine.eight_minute import (
    STRUCTURED_SINGLE_UNIT_PARENTS,
    SegmentUnits,
    _append_result,
    _is_eligible_8_minute,
    _segment_minutes,
)
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import get_category_rule_store


def _ama_units_from_minutes(minutes: float) -> int:
    """AMA Rule of 8 — per-code, no pooling across CPTs."""
    whole = int(minutes)
    base_units = whole // 15
    remainder = whole % 15
    if remainder >= 8:
        base_units += 1
    return base_units


def _calculate_units_ama(
    active_segments: dict[str, dict],
    category_store,
    aoc_store: AddOnCodeStore,
) -> list[SegmentUnits]:
    """
    AMA Rule of 8 (Substantial Portion Methodology).

    Unlike Medicare, time is not pooled — each eligible code is calculated on
    its own minutes. Structured add-on pairs still cap the parent at 1 unit and
    bill overflow on the add-on line using the add-on's own time.
    """
    results: list[SegmentUnits] = []
    eligible = {
        cpt_code: data
        for cpt_code, data in active_segments.items()
        if _is_eligible_8_minute(cpt_code, active_segments, category_store, aoc_store)
    }
    if not eligible:
        return results

    allocations = {cpt_code: 0 for cpt_code in eligible}
    processed: set[str] = set()

    for parent, data in sorted(eligible.items()):
        if parent in processed or aoc_store.is_addon(parent):
            continue

        addons = [
            code
            for code in aoc_store.addon_codes_allowed(parent)
            if code in eligible and aoc_store.is_addon(code)
        ]
        if not addons:
            continue

        valid_addons = [
            code for code in addons if aoc_store.is_valid_addon(code, active_segments)
        ]
        if not valid_addons:
            continue

        parent_minutes = _segment_minutes(data)
        addon = valid_addons[0]
        addon_minutes = _segment_minutes(eligible[addon])

        if parent in STRUCTURED_SINGLE_UNIT_PARENTS:
            parent_units = min(_ama_units_from_minutes(parent_minutes), 1)
            addon_units = _ama_units_from_minutes(addon_minutes)
        else:
            parent_units = _ama_units_from_minutes(parent_minutes)
            addon_units = _ama_units_from_minutes(addon_minutes)

        allocations[parent] = parent_units
        allocations[addon] = addon_units
        processed.add(parent)
        processed.add(addon)

    for cpt_code, data in eligible.items():
        if cpt_code in processed:
            continue
        allocations[cpt_code] = _ama_units_from_minutes(_segment_minutes(data))

    for cpt_code, data in eligible.items():
        method = "ama_rule_of_8_addon" if aoc_store.is_addon(cpt_code) else "ama_rule_of_8"
        _append_result(results, cpt_code, data, allocations[cpt_code], method)

    return results


def calculate_units(
    active_segments: dict[str, dict],
    store: MetadataStore,
) -> list[SegmentUnits]:
    category_store = get_category_rule_store()
    aoc_store = AddOnCodeStore.from_metadata(store)
    return _calculate_units_ama(active_segments, category_store, aoc_store)
