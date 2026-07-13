from app.engine.cpt_aoc_info import AddOnCodeStore
from app.engine.eight_minute import SegmentUnits
from app.engine.pt_ot_slp_billing_categories import CategoryRuleStore

SEGMENT_SIZE_MINUTES = 15
THRESHOLD_MINUTES = 8

# CPT "first 15 minutes" codes — at most 1 base unit; overflow goes to add-on.
STRUCTURED_SINGLE_UNIT_PARENTS = frozenset({"90912", "97129"})


def _units_from_pooled(minutes: float) -> int:
    if minutes < THRESHOLD_MINUTES:
        return 0
    return (int(minutes) + 7) // SEGMENT_SIZE_MINUTES


def _segment_minutes(data: dict) -> float:
    return float(data.get("minutes", 0.0))


def _allowed_addons(aoc_store: AddOnCodeStore, parent: str) -> list[str]:
    if hasattr(aoc_store, "addon_codes_allowed"):
        return list(aoc_store.addon_codes_allowed(parent) or [])
    return []


def _parent_code(aoc_store: AddOnCodeStore, cpt_code: str) -> str | None:
    if hasattr(aoc_store, "get_parent_code"):
        return aoc_store.get_parent_code(cpt_code)
    return None


def _is_eligible_8_minute(
    cpt_code: str,
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
    aoc_store: AddOnCodeStore,
) -> bool:
    if category_store.get_rule(cpt_code) == "8_minute_rule":
        return True
    if not aoc_store.is_addon(cpt_code):
        return False
    parent = _parent_code(aoc_store, cpt_code)
    if not parent or category_store.get_rule(parent) != "8_minute_rule":
        return False
    return aoc_store.is_valid_addon(cpt_code, active_segments)


def _append_result(
    results: list[SegmentUnits],
    cpt_code: str,
    data: dict,
    units: int,
    method: str,
) -> None:
    sequences = data.get("sequences", [])
    exact = data.get("minutes_exact", data.get("minutes", 0.0))
    billed = data.get("minutes_billed", int(exact))
    results.append(
        SegmentUnits(
            cpt_code=cpt_code,
            minutes_exact=exact,
            minutes_billed=billed,
            units=units,
            method=method,
            sequences=sequences,
        )
    )


def _allocate_largest_remainder(
    weights: dict[str, float],
    total_units: int,
) -> dict[str, int]:
    if total_units <= 0 or not weights:
        return {code: 0 for code in weights}

    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        return {code: 0 for code in weights}

    shares = {code: total_units * (w / weight_sum) for code, w in weights.items()}
    floors = {code: int(shares[code]) for code in weights}
    allocated = dict(floors)
    remainder = total_units - sum(floors.values())
    for code in sorted(weights, key=lambda c: shares[c] - floors[c], reverse=True):
        if remainder <= 0:
            break
        allocated[code] += 1
        remainder -= 1
    return allocated


def calculate_units(
    active_segments: dict[str, dict],
    category_store: CategoryRuleStore,
    aoc_store: AddOnCodeStore,
) -> list[SegmentUnits]:
    """
    Category A — 8_minute_rule.

    Pools direct timed minutes across all eligible codes (including add-ons
    whose parent uses this rule), then applies the Medicare 8-minute rule
    (15-minute segments, 8-minute threshold).

    Structured add-on pairs (90912/90913, 97129/97130): parent receives the
    first unit; each additional pooled unit bills on the add-on line.

    Remaining pool codes share leftover units by largest-remainder allocation.
    """
    results: list[SegmentUnits] = []
    eligible = {
        cpt_code: data
        for cpt_code, data in active_segments.items()
        if _is_eligible_8_minute(cpt_code, active_segments, category_store, aoc_store)
    }
    if not eligible:
        return results

    pool_minutes = sum(_segment_minutes(data) for data in eligible.values())
    total_units = _units_from_pooled(pool_minutes)
    allocations = {cpt_code: 0 for cpt_code in eligible}
    remaining = total_units
    processed: set[str] = set()

    for parent, data in sorted(eligible.items()):
        if parent in processed or aoc_store.is_addon(parent):
            continue

        addons = [
            code
            for code in _allowed_addons(aoc_store, parent)
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
        addon_minutes = sum(_segment_minutes(eligible[code]) for code in valid_addons)
        pair_minutes = parent_minutes + addon_minutes
        pair_units = min(_units_from_pooled(pair_minutes), remaining)

        if parent in STRUCTURED_SINGLE_UNIT_PARENTS:
            parent_units = 1 if pair_units >= 1 else 0
        else:
            parent_units = min(_units_from_pooled(parent_minutes), pair_units)

        parent_units = min(parent_units, remaining)
        addon_units = min(max(0, pair_units - parent_units), remaining - parent_units)

        allocations[parent] += parent_units
        allocations[valid_addons[0]] += addon_units
        remaining -= parent_units + addon_units
        processed.add(parent)
        processed.add(valid_addons[0])

    rest = {cpt_code: data for cpt_code, data in eligible.items() if cpt_code not in processed}
    if rest and remaining > 0:
        rest_alloc = _allocate_largest_remainder(
            {cpt_code: _segment_minutes(data) for cpt_code, data in rest.items()},
            remaining,
        )
        for cpt_code, units in rest_alloc.items():
            allocations[cpt_code] += units

    for cpt_code, data in eligible.items():
        method = "8_minute_rule_addon" if aoc_store.is_addon(cpt_code) else "8_minute_rule"
        _append_result(results, cpt_code, data, allocations[cpt_code], method)

    return results
