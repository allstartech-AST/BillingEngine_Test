from app.engine.eight_minute import SegmentUnits
from app.engine.loader import MetadataStore

def calculate_units(
    active_segments: dict[str, dict], store: MetadataStore
) -> list[SegmentUnits]:
    """
    Applies the AMA Rule of 8 (Substantial Portion Methodology).
    Unlike Medicare's 8-minute rule, time is NOT pooled.
    Each timed code is calculated individually based on its own total time.
    """
    results: list[SegmentUnits] = []

    for cpt_code, data in active_segments.items():
        minutes = data.get("minutes", 0.0)
        minutes_billed = data.get("minutes_billed", 0)
        sequences = data.get("sequences", [])

        if not store.is_timed(cpt_code):
            count = len(sequences)
            results.append(
                SegmentUnits(
                    cpt_code=cpt_code,
                    minutes_exact=minutes,
                    minutes_billed=minutes_billed,
                    units=max(count, 1) if count else 0,
                    method="occurrence",
                    sequences=sequences,
                )
            )
            continue

        base_units = int(minutes // 15)
        remainder = minutes % 15

        if remainder >= 8:
            base_units += 1

        results.append(
            SegmentUnits(
                cpt_code=cpt_code,
                minutes_exact=minutes,
                minutes_billed=minutes_billed,
                units=base_units,
                method="ama_rule_of_8",
                sequences=sequences,
            )
        )

    return results
