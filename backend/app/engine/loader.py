import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import BILLING_FILES, ICD10_DESCRIPTIONS_FILE, MEDEXA_FILE, MEDEXA_ICD10_FILE


@dataclass
class MetadataStore:
    general: dict[str, dict] = field(default_factory=dict)
    icd10: dict[str, set[str]] = field(default_factory=dict)
    ptp: dict[str, dict] = field(default_factory=dict)
    mue: dict[str, dict] = field(default_factory=dict)
    aoc: dict[str, dict] = field(default_factory=dict)
    medexa: dict[str, dict] = field(default_factory=dict)
    medexa_icd10: dict[str, dict] = field(default_factory=dict)
    icd10_descriptions: dict[str, str] = field(default_factory=dict)
    cpt_keyword_index: dict[str, set[str]] = field(default_factory=dict)
    icd_keyword_index: dict[str, set[str]] = field(default_factory=dict)

    def knows_cpt(self, cpt_code: str) -> bool:
        return cpt_code in self.general or cpt_code in self.aoc

    def description(self, cpt_code: str) -> str:
        rec = self.general.get(cpt_code, {})
        if rec.get("description"):
            return rec.get("description", "")
        return ""

    def medexa_cpt_semantic_text(self, cpt_code: str) -> str:
        """Clinical text for CPT↔ICD semantic scoring from medexa_cpt_lookup.json."""
        entry = self.medexa.get(cpt_code, {})
        parts: list[str] = []
        if entry.get("label"):
            parts.append(str(entry["label"]))
        if entry.get("notes"):
            parts.append(str(entry["notes"]))
        triggers = entry.get("trigger_phrases") or []
        if triggers:
            parts.append(" ".join(triggers[:8]))
        if parts:
            return " ".join(parts)
        return self.description(cpt_code)

    def icd_description(self, icd_code: str) -> str:
        """Fallback ICD label from icd10_descriptions.json when medexa has no entry."""
        from app.engine.icd_semantic import icd_code_variants

        for variant in icd_code_variants(icd_code):
            label = self.icd10_descriptions.get(variant)
            if label:
                return str(label).strip()
        return ""

    def medexa_icd_display_label(self, icd_code: str) -> str:
        """Human-readable ICD label without duplicating body-part tokens already in label."""
        entry = self._medexa_icd_entry(icd_code)
        if entry:
            label = str(entry.get("label", "") or "").strip()
            if label:
                body_parts = entry.get("body_parts") or []
                label_lower = label.lower()
                extra: list[str] = []
                for part in body_parts:
                    part_str = str(part).strip()
                    if part_str and part_str.lower() not in label_lower:
                        extra.append(part_str)
                if extra:
                    return f"{label} ({', '.join(extra)})"
                return label
        return self.icd_description(icd_code)

    def medexa_icd_semantic_text(self, icd_code: str) -> str:
        """Clinical text for CPT↔ICD semantic scoring from medexa or icd10_descriptions."""
        entry = self._medexa_icd_entry(icd_code)
        if entry:
            label = str(entry.get("label", "") or "").strip()
            body_parts = entry.get("body_parts") or []
            label_lower = label.lower()
            tokens: list[str] = []
            if label:
                tokens.append(label)
            for part in body_parts:
                part_str = str(part).strip()
                if part_str and part_str.lower() not in label_lower:
                    tokens.append(part_str)
            text = " ".join(tokens).strip()
            if text:
                return text
        return self.icd_description(icd_code)

    def _medexa_icd_entry(self, icd_code: str) -> dict | None:
        from app.engine.icd_semantic import icd_code_variants

        for variant in icd_code_variants(icd_code):
            entry = self.medexa_icd10.get(variant)
            if entry:
                return entry
        return None

    def billing_rule(self, cpt_code: str) -> str | None:
        """Per-CPT billing category from cpt_general_info or cpt_aoc_info."""
        rec = self.general.get(cpt_code, {})
        if "billingRule" in rec:
            value = rec.get("billingRule")
            return str(value) if value else None
        if rec.get("isTimed"):
            return "8_minute_rule"
        aoc_rec = self.aoc.get(cpt_code, {})
        aoc_rule = aoc_rec.get("billingRule")
        return str(aoc_rule) if aoc_rule else None


_store: MetadataStore | None = None


def _load_json(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def _load_medexa_dict(path: Path) -> dict[str, dict]:
    raw = _load_json(path)
    result: dict[str, dict] = {}
    for key, value in raw.items():
        if key == "_meta":
            continue
        result[key] = value
    return result


def load_metadata() -> MetadataStore:
    global _store
    if _store is not None:
        return _store

    store = MetadataStore()

    for row in _load_json(BILLING_FILES["general"]):
        store.general[row["cpt_code"]] = row

    for row in _load_json(BILLING_FILES["icd10"]):
        codes = {item["code"] for item in row.get("valid_icd10_codes", [])}
        store.icd10[row["cpt_code"]] = codes

    for row in _load_json(BILLING_FILES["ptp"]):
        store.ptp[row["cpt_code"]] = row.get("ptp", {})

    for row in _load_json(BILLING_FILES["mue"]):
        store.mue[row["cpt_code"]] = row.get("mue", {})

    for row in _load_json(BILLING_FILES["aoc"]):
        store.aoc[row["cpt_code"]] = row

    store.medexa = _load_medexa_dict(MEDEXA_FILE)
    for cpt_code, entry in store.medexa.items():
        phrases = entry.get("trigger_phrases", [])
        phrases.append(entry.get("label", ""))
        for phrase in phrases:
            words = re.findall(r'\b[a-z0-9]+\b', str(phrase).lower())
            for w in words:
                store.cpt_keyword_index.setdefault(w, set()).add(cpt_code)

    if MEDEXA_ICD10_FILE.exists():
        store.medexa_icd10 = _load_medexa_dict(MEDEXA_ICD10_FILE)
        for icd_code, entry in store.medexa_icd10.items():
            phrases = entry.get("trigger_phrases", [])
            phrases.append(entry.get("label", ""))
            for phrase in phrases:
                words = re.findall(r'\b[a-z0-9]+\b', str(phrase).lower())
                for w in words:
                    store.icd_keyword_index.setdefault(w, set()).add(icd_code)
    if ICD10_DESCRIPTIONS_FILE.exists():
        raw_desc = _load_json(ICD10_DESCRIPTIONS_FILE)
        if isinstance(raw_desc, dict):
            store.icd10_descriptions = {
                str(key): str(value)
                for key, value in raw_desc.items()
                if key != "_meta" and value
            }

    _store = store
    return store


def reset_metadata_cache() -> None:
    global _store
    _store = None
    from app.engine.pt_ot_slp_billing_categories import reset_category_rule_store

    reset_category_rule_store()
