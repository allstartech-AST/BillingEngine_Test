from app.engine.detection_summary import extract_summary_cpt_codes, reconcile_detection_summary
from app.engine.loader import MetadataStore


def test_extract_summary_shape_b():
    codes, total = extract_summary_cpt_codes({"97140": {}, "97110": {}})
    assert codes == {"97140", "97110"}
    assert total is None


def test_extract_summary_shape_a():
    codes, total = extract_summary_cpt_codes({"total_cpt_detected": 3})
    assert codes == set()
    assert total == 3


def test_reconcile_mismatch(store: MetadataStore):
    issues = reconcile_detection_summary(
        {"97140": {}, "97110": {}, "97530": {}},
        {"97140", "97110"},
        "",
        store,
    )
    assert any("97530" in i.message for i in issues)
