from app.engine.loader import MetadataStore


def test_icd10_descriptions_fallback(store: MetadataStore):
    store.icd10_descriptions["M50.11"] = "Cervical disc disorder with radiculopathy"

    assert store.medexa_icd_semantic_text("M50.11") == "Cervical disc disorder with radiculopathy"
    assert "Cervical" in store.medexa_icd_display_label("M50.11")

    store.icd10_descriptions.pop("M50.11", None)
