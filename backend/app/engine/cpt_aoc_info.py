from __future__ import annotations

import re

from app.engine.loader import MetadataStore


class AddOnCodeStore:
    def __init__(self, by_code: dict[str, dict]):
        self.by_code = by_code

    @classmethod
    def from_metadata(cls, store: MetadataStore) -> AddOnCodeStore:
        return cls(store.aoc)

    def is_addon(self, cpt_code: str) -> bool:
        return bool(self.by_code.get(cpt_code, {}).get("isAddonCode"))

    def get_parent_code(self, cpt_code: str) -> str | None:
        return self.by_code.get(cpt_code, {}).get("parentCode")

    def addon_codes_allowed(self, parent: str) -> list[str]:
        return list(self.by_code.get(parent, {}).get("addonCodesAllowed") or [])

    def is_valid_addon(self, cpt_code: str, active_segments: dict) -> bool:
        entry = self.by_code.get(cpt_code)
        if not entry or not entry.get("isAddonCode"):
            return False
        parent = entry.get("parentCode")
        if not parent or parent not in active_segments:
            return False
        parent_entry = self.by_code.get(parent, {})
        return cpt_code in (parent_entry.get("addonCodesAllowed") or [])

    def get_increment_minutes(self, cpt_code: str) -> int:
        entry = self.by_code.get(cpt_code)
        if not entry:
            return 0
        bt = entry.get("billingTime", "")
        if bt == "same as primary":
            parent = entry.get("parentCode")
            if parent:
                bt = self.by_code.get(parent, {}).get("billingTime", "")
        m = re.search(r"(\d+)\s*minutes", bt)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d+)\s*hours", bt)
        if m:
            return int(m.group(1)) * 60
        m = re.search(r"(\d+)\s*sq\s*cm", bt)
        if m:
            return int(m.group(1))
        return 0

    def get_increment_sq_cm(self, cpt_code: str) -> int:
        bt = self.by_code.get(cpt_code, {}).get("billingTime", "")
        m = re.search(r"(\d+)\s*sq\s*cm", bt)
        return int(m.group(1)) if m else 0
