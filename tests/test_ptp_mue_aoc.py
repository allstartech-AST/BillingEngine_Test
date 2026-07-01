from app.engine.aoc import validate_addon_codes
from app.engine.mue import apply_mue_cap, check_mue_zero
from app.engine.ptp import resolve_ptp_conflicts


def test_addon_requires_parent(store):
    removed, records, _, _ = validate_addon_codes({"97546"}, store)
    assert "97546" in removed
    assert records[0].reason == "missing_addon_parent"


def test_hard_bundle_97810_97813(store):
    removed, records, actions, _, conflicts = resolve_ptp_conflicts({"97810", "97813"}, store)
    assert "97810" in removed
    assert not actions


def test_bypassable_bundle(store):
    removed, _, actions, _, conflicts = resolve_ptp_conflicts({"97168", "97530"}, store)
    assert "97168" not in removed
    assert any(a.type == "bypassable_bundle" for a in actions)


def test_mue_cap(store):
    capped, _ = apply_mue_cap("97168", 2, store)
    assert capped == 1



def test_bypassable_returns_billing_conflicts(store):
    _, _, _, _, conflicts = resolve_ptp_conflicts({"97168", "97530"}, store)
    assert conflicts
    assert conflicts[0].conflict_type == "bypassable_bundle"
    assert conflicts[0].recommendations
