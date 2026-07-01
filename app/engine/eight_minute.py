from dataclasses import dataclass

from app.engine.loader import MetadataStore


@dataclass
class SegmentUnits:
    cpt_code: str
    minutes_exact: float
    minutes_billed: int
    units: int
    method: str
    sequences: list[int]


def total_units_from_minutes(minutes: int) -> int:
    if minutes <= 7:
        return 0
    return 1 + (minutes - 8) // 15


def calculate_units(
    segments_by_cpt: dict[str, dict],
    store: MetadataStore,
) -> list[SegmentUnits]:
    timed: dict[str, dict] = {}
    untimed: dict[str, dict] = {}

    for cpt, data in segments_by_cpt.items():
        if store.is_timed(cpt):
            timed[cpt] = data
        else:
            untimed[cpt] = data

    results: list[SegmentUnits] = []

    for cpt, data in untimed.items():
        count = len(data["sequences"])
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        billed = data.get("minutes_billed", int(exact))
        results.append(
            SegmentUnits(
                cpt_code=cpt,
                minutes_exact=exact,
                minutes_billed=billed,
                units=max(count, 1) if count else 0,
                method="occurrence",
                sequences=data["sequences"],
            )
        )

    if not timed:
        return results

    total_billed = sum(
        d.get("minutes_billed", int(d.get("minutes", 0))) for d in timed.values()
    )
    pool_units = total_units_from_minutes(total_billed)

    raw: dict[str, dict] = {}
    for cpt, data in timed.items():
        mins = data.get("minutes_billed")
        if mins is None:
            mins = int(data.get("minutes", 0))
        exact = data.get("minutes_exact", data.get("minutes", 0.0))
        raw[cpt] = {
            "minutes_exact": exact,
            "minutes_billed": mins,
            "sequences": data["sequences"],
            "raw_units": mins // 15,
            "remainder": mins % 15,
            "units": mins // 15,
        }

    sum_raw = sum(item["raw_units"] for item in raw.values())
    extra = pool_units - sum_raw
    if extra > 0:
        ranked = sorted(
            raw.keys(),
            key=lambda c: raw[c]["remainder"],
            reverse=True,
        )
        for cpt in ranked:
            if extra <= 0:
                break
            raw[cpt]["units"] += 1
            extra -= 1

    for cpt, item in raw.items():
        results.append(
            SegmentUnits(
                cpt_code=cpt,
                minutes_exact=item["minutes_exact"],
                minutes_billed=item["minutes_billed"],
                units=item["units"],
                method="eight_minute_rule",
                sequences=item["sequences"],
            )
        )

    return results
