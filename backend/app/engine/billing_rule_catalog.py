"""Live-session billing rule metadata for timer UI and lifecycle routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.engine.cpt_aoc_info import AddOnCodeStore
from app.engine.eight_minute import EIGHT_MINUTE_RULE
from app.engine.loader import MetadataStore
from app.engine.pt_ot_slp_billing_categories import get_category_rule_store

TimerMode = Literal["duration_units", "duration_doc", "occurrence", "area"]

DURATION_UNIT_RULES = frozenset(
    {EIGHT_MINUTE_RULE, "full_block_required", "time_band_select"}
)
OCCURRENCE_RULES = frozenset(
    {
        "untimed_per_session",
        "untimed_per_encounter",
        "untimed_per_procedure",
        "untimed_per_day",
        "untimed_per_episode",
    }
)


@dataclass(frozen=True)
class LiveRuleMeta:
    billing_rule: str
    timer_mode: TimerMode
    block_minutes: int | None = None
    increment_minutes: int | None = None
    time_band_min: float | None = None
    time_band_max: float | None = None
    area_threshold_sq_cm: int | None = None
    increment_sq_cm: int | None = None
    is_addon: bool = False
    parent_cpt_code: str | None = None


def uses_duration_for_units(timer_mode: TimerMode) -> bool:
    return timer_mode == "duration_units"


def rule_badge_label(meta: LiveRuleMeta) -> str:
    rule = meta.billing_rule
    if rule == EIGHT_MINUTE_RULE:
        return "8-Minute Rule"
    if rule == "full_block_required":
        if meta.is_addon and meta.increment_minutes:
            return f"Full Block Add-on ({meta.increment_minutes} min)"
        if meta.block_minutes:
            return f"Full Block ({meta.block_minutes} min)"
        return "Full Block Required"
    if rule == "time_band_select":
        if meta.time_band_min is not None:
            high = meta.time_band_max
            band = f"{int(meta.time_band_min)}–{int(high)} min" if high else f"{int(meta.time_band_min)}+ min"
            return f"Time Band {band}"
        return "Time Band Select"
    if rule == "area_based":
        return "Area Based"
    if rule == "untimed_per_procedure":
        return "Per Procedure"
    if rule == "untimed_per_session":
        return "Per Session"
    if rule == "untimed_per_day":
        return "Per Day"
    if rule == "untimed_per_encounter":
        return "Per Encounter"
    if rule == "untimed_per_episode":
        return "Per Episode"
    return rule.replace("_", " ").title()


def rule_detect_message(meta: LiveRuleMeta, session_billing_rule: str) -> str:
    if meta.timer_mode == "duration_units":
        if meta.billing_rule == EIGHT_MINUTE_RULE:
            label = "AMA Rule of 8" if session_billing_rule == "ama_rule_of_8" else "8-minute rule"
            return f"{label} applies — provide duration when this CPT ends."
        if meta.billing_rule == "full_block_required":
            if meta.is_addon and meta.increment_minutes:
                return (
                    f"Full-block add-on — {meta.increment_minutes} min per unit increment. "
                    "Start timer when service begins."
                )
            block = meta.block_minutes or "?"
            return f"Full block required — need {block} min for 1 unit. Start timer when service begins."
        if meta.billing_rule == "time_band_select":
            return "Time-band code — record service duration to select the matching band."
    if meta.timer_mode == "area":
        return "Area-based code — enter wound area (sq cm). Timer is optional for documentation."
    return "Occurrence-based code — mark complete when service is provided. Timer optional for documentation."


def live_rule_meta(cpt_code: str, store: MetadataStore) -> LiveRuleMeta:
    category_store = get_category_rule_store()
    aoc_store = AddOnCodeStore.from_metadata(store)
    billing_rule = store.billing_rule(cpt_code) or ""
    is_addon = aoc_store.is_addon(cpt_code)
    parent = aoc_store.get_parent_code(cpt_code)

    if billing_rule in DURATION_UNIT_RULES:
        timer_mode: TimerMode = "duration_units"
    elif billing_rule == "area_based":
        timer_mode = "area"
    elif billing_rule in OCCURRENCE_RULES:
        timer_mode = "occurrence"
    else:
        timer_mode = "duration_doc"

    block_minutes = category_store.get_block_minutes(cpt_code)
    increment_minutes = aoc_store.get_increment_minutes(cpt_code) if is_addon else None
    time_band_min: float | None = None
    time_band_max: float | None = None
    try:
        low, high = category_store.get_time_band_bounds(cpt_code)
        time_band_min = low
        time_band_max = high
    except KeyError:
        pass

    area_threshold = category_store.get_area_threshold_sq_cm(cpt_code)
    increment_sq_cm = aoc_store.get_increment_sq_cm(cpt_code) if is_addon else None

    return LiveRuleMeta(
        billing_rule=billing_rule,
        timer_mode=timer_mode,
        block_minutes=block_minutes,
        increment_minutes=increment_minutes or None,
        time_band_min=time_band_min,
        time_band_max=time_band_max,
        area_threshold_sq_cm=area_threshold,
        increment_sq_cm=increment_sq_cm or None,
        is_addon=is_addon,
        parent_cpt_code=parent,
    )
