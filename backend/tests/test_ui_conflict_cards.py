"""UI conflict presentation helpers."""

from app.engine.ui_conflict_cards import ncci_conflicts_for_cpt
from app.models.output import BillingConflict


def _conflict(cpt_a: str, cpt_b: str, conflict_id: str) -> BillingConflict:
    return BillingConflict(
        conflict_id=conflict_id,
        conflict_type="bypassable_bundle",
        codes=[cpt_a, cpt_b],
        column_one_code=cpt_a,
        column_two_code=cpt_b,
        modifier_indicator="1",
        modifier_applies_to=cpt_b,
        issue="bundle",
        recommendations=[],
        ai_enriched=False,
    )


def test_ncci_conflicts_for_cpt_returns_all_matches() -> None:
    conflicts = [
        _conflict("97110", "97530", "c1"),
        _conflict("97110", "97140", "c2"),
        _conflict("92507", "92508", "c3"),
    ]
    matches = ncci_conflicts_for_cpt("97110", conflicts)
    assert {c.conflict_id for c in matches} == {"c1", "c2"}
