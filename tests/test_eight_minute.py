from app.engine.eight_minute import total_units_from_minutes, calculate_units


def test_total_units_table():
    assert total_units_from_minutes(7) == 0
    assert total_units_from_minutes(8) == 1
    assert total_units_from_minutes(22) == 1
    assert total_units_from_minutes(23) == 2
    assert total_units_from_minutes(38) == 3


def test_pooled_remainder_allocation(store):
    segments = {
        "97110": {"minutes": 16.0, "sequences": [1]},
        "97140": {"minutes": 10.0, "sequences": [2]},
    }
    results = {r.cpt_code: r for r in calculate_units(segments, store)}
    assert results["97110"].units == 1
    assert results["97140"].units == 1
