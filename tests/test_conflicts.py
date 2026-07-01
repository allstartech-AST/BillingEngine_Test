from app.engine.conflicts import filter_billing_conflicts, filter_therapist_actions
from app.engine.loader import MetadataStore
from app.models.output import BillingConflict, ConflictRecommendation, TherapistAction


def _ncci_conflict(c1: str, c2: str) -> BillingConflict:
    return BillingConflict(
        conflict_id=f"ncci_{c2}_{c1}",
        conflict_type="bypassable_bundle",
        codes=sorted([c1, c2]),
        column_one_code=c1,
        column_two_code=c2,
        issue="test",
        recommendations=[],
        modifier_indicator="1",
    )


def _overlap_conflict(c1: str, c2: str) -> BillingConflict:
    return BillingConflict(
        conflict_id=f"overlap_{c1}_{c2}",
        conflict_type="overlap",
        codes=sorted([c1, c2]),
        issue="overlap test",
        recommendations=[],
    )


def test_filter_drops_ncci_with_removed_cpt():
    conflicts = [
        _ncci_conflict("97150", "97110"),
        _ncci_conflict("97110", "97750"),
    ]
    active = {"97110", "97750", "97530"}
    filtered = filter_billing_conflicts(conflicts, active)
    assert len(filtered) == 1
    assert filtered[0].conflict_id == "ncci_97750_97110"


def test_filter_keeps_overlap_when_one_cpt_still_active():
    conflicts = [_overlap_conflict("97014", "97012")]
    active = {"97012", "97110"}
    filtered = filter_billing_conflicts(conflicts, active)
    assert len(filtered) == 1


def test_filter_therapist_actions():
    conflicts = [_ncci_conflict("97110", "97750")]
    actions = [
        TherapistAction(
            type="bypassable_bundle",
            codes=["97110", "97750"],
            modifier_indicator="1",
            modifiers_suggested=["59"],
            modifiers_not_applicable=[],
            guidance="g",
            conflict_id="ncci_97750_97110",
        ),
        TherapistAction(
            type="bypassable_bundle",
            codes=["97150", "97110"],
            modifier_indicator="1",
            modifiers_suggested=["59"],
            modifiers_not_applicable=[],
            guidance="stale",
            conflict_id="ncci_97110_97150",
        ),
    ]
    filtered = filter_therapist_actions(actions, conflicts)
    assert len(filtered) == 1
    assert filtered[0].conflict_id == "ncci_97750_97110"


def test_medexa_icd_display_label_dedupes_spine():
    store = MetadataStore()
    store.medexa_icd10 = {
        "A18.01": {
            "code": "A18.01",
            "label": "Tuberculosis of spine",
            "body_parts": ["spine"],
        }
    }
    assert store.medexa_icd_display_label("A18.01") == "Tuberculosis of spine"
    assert "spine spine" not in store.medexa_icd_semantic_text("A18.01")
