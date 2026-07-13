"""Shared billing-rule metadata for LLM prompts and payloads."""

from __future__ import annotations

from typing import Any

from app.engine.cpt_aoc_info import AddOnCodeStore
from app.engine.eight_minute import EIGHT_MINUTE_RULE, STRUCTURED_SINGLE_UNIT_PARENTS
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import get_category_rule_store


def timing_rules_system_instructions() -> str:
    return """CRITICAL — Per-CPT billing rules:
- Every line includes a billing_rule and the rule-specific metadata needed for calculation. Never substitute a different rule.
- The session-level rule (Medicare CMS vs AMA) affects ONLY billing_rule="8_minute_rule".
- Never add minutes from any other billing_rule to the Medicare timed pool.

Medicare 8-Minute Rule (CMS pooled rule):
1. Sum duration_minutes ONLY from lines where billing_rule="8_minute_rule" → this is the timed treatment pool.
2. Convert that pool total to billable units: 0 units if ≤7 min; 1 unit for 8–22 min; +1 unit per additional 15 min (23–37 = 2, 38–52 = 3, etc.).
3. Allocate pool units across timed lines using CMS substantial-portion / remainder methodology.
4. Respect structured parent/add-on allocation metadata when supplied.

AMA Rule of Eight:
1. Apply per-code thresholds ONLY to lines where billing_rule="8_minute_rule" (each on its own minutes: 0 if ≤7 min, 1 for 8–22, +1 per 15 min thereafter).
2. Do NOT pool minutes across timed codes.
3. Respect structured parent/add-on allocation metadata when supplied.

Other billing_rule calculations (independent of CMS vs AMA):
- full_block_required: base code = 1 unit only when duration_minutes >= block_minutes; valid add-on = floor(duration_minutes / increment_minutes).
- untimed_per_session, untimed_per_encounter, untimed_per_day, untimed_per_episode: 1 unit when the service is present, regardless of duration or repeated sequences.
- untimed_per_procedure: occurrence_count units.
- area_based: per-wound codes use occurrence_count; a base area code is 1 unit when area_sq_cm >= area_threshold_sq_cm; a valid add-on is floor(area_sq_cm / increment_sq_cm).
- time_band_select: service duration is the maximum duration among eligible candidate lines; exactly one candidate whose supplied time-band contains it receives 1 unit (lowest CPT code wins a tie); all others receive 0.

Input validation:
- Require positive duration only for 8_minute_rule, full_block_required, and time_band_select.
- Zero duration is valid for untimed and area-based rules; do not fail those lines solely because duration is zero.
- Require area_sq_cm only when an area-based calculation needs an area threshold or increment.
- If required rule metadata is missing, do not guess: mark the affected line failed or the calculation ambiguous."""


def resolve_billing_rule(
    cpt: str,
    billing_rule: str | None,
    store: MetadataStore,
) -> str | None:
    if billing_rule is not None:
        return billing_rule or None
    return store.billing_rule(cpt.strip())


def timed_pool_minutes(lines: list[dict[str, Any]], store: MetadataStore) -> float:
    total = 0.0
    for line in lines:
        cpt = str(line.get("cpt", "")).strip()
        if not cpt:
            continue
        if resolve_billing_rule(cpt, line.get("billing_rule"), store) == EIGHT_MINUTE_RULE:
            total += float(line.get("duration_minutes", line.get("minutes", 0)) or 0)
    return total


def enrich_summary_line(line: dict[str, Any], store: MetadataStore) -> dict[str, Any]:
    cpt = str(line.get("cpt", "")).strip()
    billing_rule = resolve_billing_rule(cpt, line.get("billing_rule"), store)
    sequences = list(line.get("sequences") or [])
    occurrence_count = int(line.get("occurrence_count") or len(sequences) or 1)
    enriched: dict[str, Any] = {
        "cpt": cpt,
        "billing_rule": billing_rule,
        "duration_minutes": line.get("duration_minutes", line.get("minutes", 0)),
        "occurrence_count": occurrence_count,
    }
    for key in (
        "summary_units",
        "engine_units",
        "area_sq_cm",
        "description",
        "modifier",
        "region",
        "body_region",
    ):
        if key in line and line[key] is not None:
            enriched[key] = line[key]

    category_store = get_category_rule_store()
    aoc_store = AddOnCodeStore.from_metadata(store)
    if billing_rule == "full_block_required":
        block = category_store.get_block_minutes(cpt)
        if block:
            enriched["block_minutes"] = block
    elif billing_rule == "time_band_select":
        try:
            low, high = category_store.get_time_band_bounds(cpt)
            enriched["time_band_min_minutes"] = low
            enriched["time_band_max_minutes"] = high
        except KeyError:
            pass
    elif billing_rule == "area_based":
        threshold = category_store.get_area_threshold_sq_cm(cpt)
        if threshold:
            enriched["area_threshold_sq_cm"] = threshold

    aoc_entry = store.aoc.get(cpt, {})
    if aoc_entry:
        enriched["is_addon"] = aoc_store.is_addon(cpt)
        enriched["parent_code"] = aoc_store.get_parent_code(cpt)
        enriched["addon_codes_allowed"] = aoc_store.addon_codes_allowed(cpt)
        enriched["structured_single_unit_parent"] = (
            cpt in STRUCTURED_SINGLE_UNIT_PARENTS
        )
        if billing_rule == "area_based":
            increment_area = aoc_store.get_increment_sq_cm(cpt)
            if increment_area:
                enriched["increment_sq_cm"] = increment_area
        else:
            increment_minutes = aoc_store.get_increment_minutes(cpt)
            if increment_minutes:
                enriched["increment_minutes"] = increment_minutes
    return enriched


def build_llm_billing_payload(
    lines: list[dict[str, Any]],
    billing_rule: str,
    rule_label: str,
    store: MetadataStore,
) -> dict[str, Any]:
    enriched = [enrich_summary_line(line, store) for line in lines]
    timed_lines = [
        line for line in enriched if line.get("billing_rule") == EIGHT_MINUTE_RULE
    ]
    other_lines = [
        line for line in enriched if line.get("billing_rule") != EIGHT_MINUTE_RULE
    ]
    pool = timed_pool_minutes(enriched, store)

    payload: dict[str, Any] = {
        "rule": rule_label,
        "timed_pool_minutes": pool,
        "timed_pool_note": (
            "For Medicare 8-Minute Rule, use ONLY timed_pool_minutes when pooling. "
            "Never add minutes from non-8_minute_rule lines."
        ),
        "timed_lines": timed_lines,
        "other_lines": other_lines,
        "billing_summary": enriched,
    }
    return payload
