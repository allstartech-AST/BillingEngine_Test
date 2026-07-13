from app.engine.eight_minute import SegmentUnits
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore


def calculate_units(
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
        if category_store.get_rule(cpt_code) != "untimed_per_encounter":
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
                method="untimed_per_encounter",
                sequences=sequences,
            )
        )

    return results
