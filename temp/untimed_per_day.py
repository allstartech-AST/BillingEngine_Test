from app.engine.eight_minute import SegmentUnits
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore


def calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
) -> list[SegmentUnits]:
    """
    Category E — untimed_per_day.

    No time-based units; bills exactly 1 unit per calendar day when the
    service is provided, regardless of duration or how many times it appears
    in sequences (day scoping is applied upstream).
    """
    results: list[SegmentUnits] = []

    for cpt_code, data in active_segments.items():
        if category_store.get_rule(cpt_code) != "untimed_per_day":
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
                method="untimed_per_day",
                sequences=sequences,
            )
        )

    return results
