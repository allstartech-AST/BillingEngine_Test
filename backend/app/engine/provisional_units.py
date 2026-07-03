from app.engine.eight_minute import calculate_units
from app.engine.loader import MetadataStore
from app.engine.mue import apply_mue_cap
from app.models.output import BillingConflict


def _column_two_codes(conflicts: list[BillingConflict]) -> set[str]:
    codes: set[str] = set()
    for conflict in conflicts:
        if conflict.conflict_type != "bypassable_bundle":
            continue
        if conflict.column_two_code:
            codes.add(conflict.column_two_code)
    return codes


def calculate_provisional_unit_maps(
    active_cpts: set[str],
    segments_by_cpt: dict[str, dict],
    billing_conflicts: list[BillingConflict],
    store: MetadataStore,
) -> tuple[dict[str, int], dict[str, int]]:
    """Return (max_scenario, conservative_scenario) unit maps per CPT."""
    active_segments = {
        cpt: segments_by_cpt[cpt] for cpt in active_cpts if cpt in segments_by_cpt
    }
    if not active_segments:
        return {}, {}

    max_map: dict[str, int] = {}
    for item in calculate_units(active_segments, store):
        units, _ = apply_mue_cap(item.cpt_code, item.units, store)
        max_map[item.cpt_code] = units

    column_two = _column_two_codes(billing_conflicts)
    conservative_cpts = active_cpts - column_two
    conservative_segments = {
        cpt: segments_by_cpt[cpt]
        for cpt in conservative_cpts
        if cpt in segments_by_cpt
    }
    conservative_map: dict[str, int] = {cpt: 0 for cpt in active_cpts}
    if conservative_segments:
        for item in calculate_units(conservative_segments, store):
            units, _ = apply_mue_cap(item.cpt_code, item.units, store)
            conservative_map[item.cpt_code] = units

    return max_map, conservative_map
