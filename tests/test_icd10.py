from app.engine.icd10 import extract_icd_codes, validate_medical_necessity


def test_extract_icd_codes():
    codes = extract_icd_codes({"icd_1": "M54.50", "icd_2": "M50.01"})
    assert codes == ["M50.01", "M54.50"]


def test_extract_icd_codes_ranked_preserves_order():
    from app.engine.icd10 import extract_icd_codes_ranked

    codes = extract_icd_codes_ranked({"icd_1": "M54.50", "icd_2": "M50.01"})
    assert codes == ["M54.50", "M50.01"]


def test_extract_icd_codes_with_labels():
    codes = extract_icd_codes(
        {"F01.50": "Vascular dementia, moderate", "M54.5": "Low back pain"}
    )
    assert "F01.50" in codes
    assert "M54.5" in codes


def test_icd_pending_review_for_97168(store):
    results, pending = validate_medical_necessity({"97168"}, ["M54.50"], store)
    assert "97168" in pending
    assert results[0].medical_necessity == "pending_icd_review"
    assert results[0].review_reason in ("crosswalk_miss", "no_icd_description", "low_semantic_match")
    assert results[0].guidance
    assert results[0].valid_icd10_alternatives
    assert "M50.01" in results[0].valid_icd10_alternatives
    assert results[0].auto_removed is False


def test_icd_pending_no_description(store):
    results, pending = validate_medical_necessity(
        {"97110"}, ["F01.50"], store, diagnosis_labels={}
    )
    assert "97110" in pending
    assert results[0].review_reason == "no_icd_description"
    assert results[0].semantic_confidence is None or results[0].semantic_confidence == 0


def test_icd_valid_for_97168(store):
    results, pending = validate_medical_necessity({"97168"}, ["M50.01"], store)
    assert pending == set()
    assert results[0].medical_necessity == "valid"
    assert results[0].matched_icd == "M50.01"


def test_icd_valid_no_crosswalk(store):
    results, pending = validate_medical_necessity({"99999"}, ["M54.50"], store)
    assert pending == set()
    assert results[0].medical_necessity == "valid_no_crosswalk"
