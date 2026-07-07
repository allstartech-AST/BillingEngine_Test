"""Knowledge-base context strings for live LLM CPT tasks."""

from __future__ import annotations

import json

from app.engine.loader import MetadataStore


def build_compact_medexa_reference(store: MetadataStore) -> str:
    """Compact allowlist for suggest-missing (code + label only)."""
    lines = ["--- ENTIRE MEDEXA CPT DICTIONARY ---"]
    for code, entry in sorted(store.medexa.items()):
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
