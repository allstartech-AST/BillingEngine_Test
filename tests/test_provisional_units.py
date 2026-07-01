from app.engine.provisional_units import calculate_provisional_unit_maps
from app.models.output import BillingConflict, ConflictRecommendation


def test_conservative_excludes_column_two(store):
    segments = {
        "97110": {"minutes_exact": 26.0, "minutes_billed": 26, "minutes": 26.0, "sequences": [1]},
        "97112": {"minutes_exact": 16.0, "minutes_billed": 16, "minutes": 16.0, "sequences": [2]},
    }
    conflicts = [
        BillingConflict(
            conflict_id="ncci_97112_97110",
            conflict_type="bypassable_bundle",
            codes=["97110", "97112"],
            column_one_code="97110",
            column_two_code="97112",
            issue="bundle",
            recommendations=[ConflictRecommendation(action="apply_modifier", summary="mod")],
        )
    ]
    max_map, conservative_map = calculate_provisional_unit_maps(
        {"97110", "97112"}, segments, conflicts, store
    )
    assert max_map.get("97112", 0) >= 0
    assert conservative_map.get("97112", -1) == 0
    assert "97110" in conservative_map
