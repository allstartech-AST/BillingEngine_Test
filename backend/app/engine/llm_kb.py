"""Knowledge-base context strings for live LLM CPT tasks."""

from __future__ import annotations

import json

from app.engine.loader import MetadataStore


def build_compact_medexa_reference(store: MetadataStore) -> str:
    """Compact allowlist for suggest-missing (billable codes with medexa labels)."""
    lines = ["--- ENTIRE MEDEXA CPT DICTIONARY ---"]
    for code, entry in sorted(store.medexa.items()):
        if not store.knows_cpt(code):
            continue
        label = entry.get("label", "")
        lines.append(f"- {code}: {label}")
    return "\n".join(lines)


def build_compact_ptp_pair_context(
    store: MetadataStore,
    primary_cpt: str,
    bundled_cpt: str,
) -> str:
    """PTP edits between two active codes only (for modifier tasks)."""
    lines: list[str] = []
    pair = {primary_cpt.strip(), bundled_cpt.strip()}
    for cpt in sorted(pair):
        ptp = store.ptp.get(cpt, {})
        if not ptp:
            continue
        snippets: list[dict] = []
        for entry in ptp.get("bundled_into", []):
            if entry.get("primary_code") in pair:
                snippets.append(entry)
        for entry in ptp.get("bundles_others", []):
            if entry.get("bundled_code") in pair:
                snippets.append(entry)
        if snippets:
            lines.append(f"CPT {cpt} NCCI PTP (pair only): {json.dumps(snippets)}")
    return "\n".join(lines)


def build_suggest_conflict_context(store: MetadataStore, existing_cpts: list[str]) -> str:
    """Compact guardrails so suggest-missing avoids auto-rejected codes."""
    active = {code for code in existing_cpts if code}
    if not active:
        return ""

    rules: list[str] = []
    seen: set[str] = set()

    def add_rule(line: str) -> None:
        if line in seen:
            return
        seen.add(line)
        rules.append(line)

    for primary in sorted(active):
        for entry in store.ptp.get(primary, {}).get("bundles_others", []):
            if str(entry.get("modifier_indicator", "0")) != "0":
                continue
            bundled = entry.get("bundled_code")
            if bundled and store.knows_cpt(bundled):
                add_rule(
                    f"- Do NOT suggest {bundled}: hard NCCI bundle with existing {primary} "
                    "(modifier indicator 0; no bypass)."
                )

    for component in sorted(active):
        for entry in store.ptp.get(component, {}).get("bundled_into", []):
            if str(entry.get("modifier_indicator", "0")) != "0":
                continue
            primary = entry.get("primary_code")
            if primary and store.knows_cpt(primary) and primary not in active:
                add_rule(
                    f"- Do NOT suggest {primary}: would hard-bundle/remove existing {component}."
                )

    for code, rec in store.aoc.items():
        if not rec.get("isAddonCode") or not store.knows_cpt(code) or code in active:
            continue
        parent = rec.get("parentCode")
        if parent and parent not in active:
            add_rule(
                f"- Do NOT suggest add-on {code} alone: requires parent {parent} on the session."
            )

    if not rules:
        return ""

    return (
        "--- BILLING CONFLICT GUARDRAILS (relative to existing session CPTs) ---\n"
        "Never suggest a code that would be auto-rejected due to hard NCCI bundles, "
        "missing add-on parent, or MUE-zero limits.\n"
        + "\n".join(rules)
    )


def build_kb_context(store: MetadataStore, *cpts: str) -> str:
    kb_text = []
    if not cpts:
        return build_compact_medexa_reference(store)

    for cpt in cpts:
        if not cpt:
            continue
        cpt = cpt.strip()
        kb_text.append(f"--- KNOWLEDGE BASE FOR CPT {cpt} ---")

        if store.knows_cpt(cpt):
            kb_text.append(f"General Info: {json.dumps(store.general.get(cpt, {}))}")

        ptp_info = store.ptp.get(cpt)
        if ptp_info:
            kb_text.append(f"NCCI PTP Edit Rules: {json.dumps(ptp_info)}")

        mue_info = store.mue.get(cpt)
        if mue_info:
            kb_text.append(f"MUE Limits: {json.dumps(mue_info)}")

        aoc_info = store.aoc.get(cpt)
        if aoc_info:
            kb_text.append(f"AOC Requirements: {json.dumps(aoc_info)}")

        medexa_info = store.medexa.get(cpt)
        if medexa_info:
            kb_text.append(f"Medexa Info: {json.dumps(medexa_info)}")

    return "\n\n".join(kb_text)
