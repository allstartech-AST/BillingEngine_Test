"""AI suggest-missing conflict guardrails."""

from app.engine.conflict_evaluation import codes_hard_rejected_if_added
from app.engine.llm_cpt_tasks import filter_suggestable_cpts
from app.engine.llm_kb import build_suggest_conflict_context
from app.engine.loader import MetadataStore


def test_codes_hard_rejected_if_added_hard_bundle(store: MetadataStore) -> None:
    rejected = codes_hard_rejected_if_added({"92526"}, ["97032"], store)
    assert "97032" in rejected


def test_build_suggest_conflict_context_lists_hard_bundle(store: MetadataStore) -> None:
    context = build_suggest_conflict_context(store, ["92526"])
    assert "97032" in context
    assert "Do NOT suggest" in context


def test_filter_suggestable_cpts_drops_hard_conflicts(store: MetadataStore) -> None:
    suggested = [
        {"cpt_code": "97032", "reasoning": "should be dropped"},
        {"cpt_code": "97140", "reasoning": "may be kept"},
    ]
    filtered = filter_suggestable_cpts(suggested, ["92526"], store)
    codes = {item["cpt_code"] for item in filtered}
    assert "97032" not in codes
