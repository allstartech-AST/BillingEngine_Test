"""Shared timed vs untimed billing rules for Gemini prompts and payloads."""

from __future__ import annotations

from typing import Any

from app.engine.loader import MetadataStore


def timing_rules_system_instructions() -> str:
    return """CRITICAL — Timed vs untimed CPT codes:
- Each summary line includes is_timed (true = timed treatment code, false = untimed/occurrence/manual code).
- Untimed codes (is_timed=false): duration_minutes is documentation only. NEVER add untimed minutes to any timed pool or total-minute sum. Bill untimed codes by occurrence/manual units (typically compare summary_units directly; one line = one occurrence unless stated otherwise).
- Timed codes (is_timed=true): duration_minutes drives unit math.

Medicare 8-Minute Rule (CMS pooled rule):
1. Sum duration_minutes ONLY from lines where is_timed=true → this is the timed treatment pool.
2. Convert that pool total to billable units: 0 units if ≤7 min; 1 unit for 8–22 min; +1 unit per additional 15 min (23–37 = 2, 38–52 = 3, etc.).
3. Allocate pool units across timed lines using CMS substantial-portion / remainder methodology.
4. Do NOT include untimed line minutes in step 1 or in total_units for timed billing.

AMA Rule of Eight:
1. Apply per-code thresholds ONLY to lines where is_timed=true (each timed code on its own minutes: 0 if ≤7 min, 1 for 8–22, +1 per 15 min thereafter).
2. Do NOT pool minutes across timed codes.
3. Untimed lines (is_timed=false) are excluded from AMA minute thresholds — validate their units separately (occurrence/manual)."""


def resolve_is_timed(cpt: str, is_timed: bool | None, store: MetadataStore) -> bool:
    if is_timed is not None:
        return is_timed
    return store.is_timed(cpt.strip())


def timed_pool_minutes(lines: list[dict[str, Any]], store: MetadataStore) -> float:
    total = 0.0
    for line in lines:
        cpt = str(line.get("cpt", "")).strip()
        if not cpt:
            continue
        if resolve_is_timed(cpt, line.get("is_timed"), store):
            total += float(line.get("duration_minutes", line.get("minutes", 0)) or 0)
    return total


def enrich_summary_line(line: dict[str, Any], store: MetadataStore) -> dict[str, Any]:
    cpt = str(line.get("cpt", "")).strip()
    is_timed = resolve_is_timed(cpt, line.get("is_timed"), store)
    enriched: dict[str, Any] = {
        "cpt": cpt,
        "is_timed": is_timed,
        "duration_minutes": line.get("duration_minutes", line.get("minutes", 0)),
    }
    if "summary_units" in line:
        enriched["summary_units"] = line["summary_units"]
    if "engine_units" in line:
        enriched["engine_units"] = line["engine_units"]
    if "minutes" in line and "duration_minutes" not in line:
        enriched["duration_minutes"] = line["minutes"]
    return enriched


def build_gemini_billing_payload(
    lines: list[dict[str, Any]],
    billing_rule: str,
    rule_label: str,
    store: MetadataStore,
) -> dict[str, Any]:
    enriched = [enrich_summary_line(line, store) for line in lines]
    timed_lines = [line for line in enriched if line["is_timed"]]
    untimed_lines = [line for line in enriched if not line["is_timed"]]
    pool = timed_pool_minutes(enriched, store)

    payload: dict[str, Any] = {
        "rule": rule_label,
        "timed_pool_minutes": pool,
        "timed_pool_note": (
            "For Medicare 8-Minute Rule, use ONLY timed_pool_minutes when pooling. "
            "Never add minutes from untimed lines."
        ),
        "timed_lines": timed_lines,
        "untimed_lines": untimed_lines,
        "billing_summary": enriched,
    }
    return payload
