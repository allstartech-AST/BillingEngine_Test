from app.engine.cpt_aoc_info import AddOnCodeStore
from app.engine.eight_minute import SegmentUnits
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore

PER_WOUND_CODES = frozenset({"97605", "97606", "97607"})


def _area_sq_cm(data: dict) -> float:
    return float(data.get("area_sq_cm", data.get("area", 0.0)))


def _increment_sq_cm(aoc_store: AddOnCodeStore, cpt_code: str) -> int:
    if hasattr(aoc_store, "get_increment_sq_cm"):
        value = aoc_store.get_increment_sq_cm(cpt_code)
        if value:
            return int(value)
    return int(aoc_store.get_increment_minutes(cpt_code) or 0)


def calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
    aoc_store: AddOnCodeStore,
) -> list[SegmentUnits]:
    """
    Category F — area_based.

    Units are driven by wound area (sq cm) or per-wound tier, not time.

    Per-wound codes (97605–97607): 1 unit per wound when the service occurs.

    Area-increment codes (97597): 1 unit when area >= threshold (first block).

    Add-on codes (97598, 97608): validated via AOC; units = completed area
    increments only — area // increment_sq_cm — remainder discarded.
    """
    results: list[SegmentUnits] = []

    for cpt_code, data in active_segments.items():
        sequences = data.get("sequences", [])
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        billed = data.get("minutes_billed", int(exact))
        area = _area_sq_cm(data)

        if aoc_store.is_addon(cpt_code):
            if not aoc_store.is_valid_addon(cpt_code, active_segments):
                continue

            increment = _increment_sq_cm(aoc_store, cpt_code)
            units = int(area // increment) if increment else 0

            results.append(
                SegmentUnits(
                    cpt_code=cpt_code,
                    minutes_exact=exact,
                    minutes_billed=billed,
                    units=units,
                    method="area_based_addon",
                    sequences=sequences,
                )
            )
            continue

        if category_store.get_rule(cpt_code) != "area_based":
            continue

        if cpt_code in PER_WOUND_CODES:
            units = len(sequences) if sequences else 0
        else:
            threshold = category_store.get_area_threshold_sq_cm(cpt_code)
            units = 1 if threshold and area >= threshold else 0

        results.append(
            SegmentUnits(
                cpt_code=cpt_code,
                minutes_exact=exact,
                minutes_billed=billed,
                units=units,
                method="area_based",
                sequences=sequences,
            )
        )

    return results
