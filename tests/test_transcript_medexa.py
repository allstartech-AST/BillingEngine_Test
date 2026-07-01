from app.engine.transcript_medexa import validate_cpt_transcript_support


def test_97110_supported(store):
    transcript = "We did therapeutic exercises working on shoulder strengthening today."
    result = validate_cpt_transcript_support("97110", transcript, store)
    assert result.transcript_support == "supported"


def test_tens_word_boundary(store):
    transcript = "Patient did tens of repetitions during the session."
    result = validate_cpt_transcript_support("97014", transcript, store)
    assert result.transcript_support != "supported"


def test_not_applicable_addon(store):
    result = validate_cpt_transcript_support("97130", "any transcript", store)
    assert result.transcript_support == "not_applicable"
