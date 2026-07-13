"""Billing unit dispatcher — orchestrates all billing-rule category calculators.

Each calculator internally filters for its applicable CPT codes by checking
the billingRule in CategoryRuleStore, so every calculator receives the full
set of active segments and returns results only for codes it handles.  This
guarantees no code is double-counted and no code is silently dropped.
"""

from __future__ import annotations

from app.engine import ama_rule
from app.engine import area_based
from app.engine import full_block_required
from app.engine import time_band_select
from app.engine import untimed_per_day
from app.engine import untimed_per_encounter
from app.engine import untimed_per_episode
from app.engine import untimed_per_procedure
from app.engine import untimed_per_session
from app.engine.eight_minute import SegmentUnits
from app.engine.eight_minute import calculate_units as calculate_units_eight_minute
from app.engine.loader import MetadataStore


def calculate_all_units(
    segments_by_cpt: dict[str, dict],
    store: MetadataStore,
    billing_rule: str = "cms_8_minute",
) -> list[SegmentUnits]:
    """Calculate billable units for every CPT code across all billing categories.

    Parameters
    ----------
    segments_by_cpt:
        Dict mapping CPT code -> segment data (minutes, sequences, etc.).
    store:
        Shared metadata store for CPT lookups.
    billing_rule:
        Session-level timing rule — ``"ama_rule_of_8"`` or ``"cms_8_minute"``
        (default).  Only affects Category A (8-minute-rule) codes; all other
        categories are rule-agnostic.

    Returns
    -------
    list[SegmentUnits]
        Merged results from all applicable calculators.
    """
    results: list[SegmentUnits] = []

    # ── Category A: timed codes under the 8-minute rule ──────────────
    if billing_rule == "ama_rule_of_8":
        results.extend(ama_rule.calculate_units(segments_by_cpt, store))
    else:
        results.extend(calculate_units_eight_minute(segments_by_cpt, store))

    # ── Category B: full block required ───────────────────────────────
    results.extend(full_block_required.calculate_units(segments_by_cpt, store))

    # ── Category C: untimed per session ───────────────────────────────
    results.extend(untimed_per_session.calculate_units(segments_by_cpt, store))

    # ── Category D: untimed per procedure ─────────────────────────────
    results.extend(untimed_per_procedure.calculate_units(segments_by_cpt, store))

    # ── Category E: untimed per day ───────────────────────────────────
    results.extend(untimed_per_day.calculate_units(segments_by_cpt, store))

    # ── Category F: area based ────────────────────────────────────────
    results.extend(area_based.calculate_units(segments_by_cpt, store))

    # ── Category G: time band select ──────────────────────────────────
    results.extend(time_band_select.calculate_units(segments_by_cpt, store))

    # ── Category H: untimed per episode ───────────────────────────────
    results.extend(untimed_per_episode.calculate_units(segments_by_cpt, store))

    # ── Category I: untimed per encounter ─────────────────────────────
    results.extend(untimed_per_encounter.calculate_units(segments_by_cpt, store))

    return results
