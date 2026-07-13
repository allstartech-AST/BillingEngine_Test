"""Category G — time_band_select unit calculator."""

from __future__ import annotations

from app.engine.eight_minute import SegmentUnits
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore, get_category_rule_store

RULE = "time_band_select"


def _minutes_in_band(minutes: float, low: float, high: float | None) -> bool:
    if minutes < low:
        return False
    if high is None:
        return True
    return minutes <= high


def _calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
) -> list[SegmentUnits]:
    """
    Category G — time_band_select.

    Pick exactly one code whose CPT time band matches total service minutes.
    Not additive — only the matching band receives 1 unit; all others are 0.
    When multiple candidate codes share the same matching band, the lowest CPT
    code wins.
    """
    results: list[SegmentUnits] = []
    eligible = {
        cpt_code: data
        for cpt_code, data in active_segments.items()
        if category_store.get_rule(cpt_code) == RULE
    }
    if not eligible:
        return results

    service_minutes = max(float(data.get("minutes", 0.0)) for data in eligible.values())
    matching = [
        cpt_code
        for cpt_code in eligible
        if _minutes_in_band(
            service_minutes,
            *category_store.get_time_band_bounds(cpt_code),
        )
    ]
    winner = min(matching) if matching else None

    for cpt_code, data in eligible.items():
        sequences = data.get("sequences", [])
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        billed = data.get("minutes_billed", int(exact))
        units = 1 if cpt_code == winner else 0

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
