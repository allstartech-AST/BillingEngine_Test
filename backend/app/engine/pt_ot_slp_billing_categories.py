from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import BILLING_FILES

_store: CategoryRuleStore | None = None


def _parse_time_band(text: str) -> tuple[float, float | None]:
    cleaned = text.replace(" minutes", "").strip()
    if cleaned.endswith("+"):
        return float(re.search(r"(\d+)", cleaned).group(1)), None
    low, high = cleaned.split("-")
    return float(low), float(high)


class CategoryRuleStore:
    def __init__(self, categories_path: Path, general_path: Path):
        cats = json.loads(categories_path.read_text(encoding="utf-8"))
        general = json.loads(general_path.read_text(encoding="utf-8"))
        self.rule_by_code: dict[str, str] = {
            e["cpt_code"]: e["billingRule"] for e in general
        }
        self.block_minutes: dict[str, int] = {}
        self.time_bands: dict[str, tuple[float, float | None]] = {}
        self.area_threshold: dict[str, int] = {}

        def walk(obj):
            if isinstance(obj, dict):
                br = obj.get("billing_rule")
                if "codes" in obj and br:
                    for code in obj["codes"]:
                        self.rule_by_code.setdefault(code, br)
                        if "block_minutes" in obj:
                            self.block_minutes[code] = obj["block_minutes"]
                        if "time_band" in obj:
                            self.time_bands[code] = _parse_time_band(obj["time_band"])
                        if br == "area_based" and "billing_time" in obj:
                            m = re.search(r"(\d+)\s*sq\s*cm", obj["billing_time"])
                            if m and "per unit" not in obj["billing_time"]:
                                self.area_threshold[code] = int(m.group(1))
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(cats)
        for entry in general:
            self.rule_by_code[entry["cpt_code"]] = entry["billingRule"]

    def get_rule(self, cpt_code: str) -> str | None:
        return self.rule_by_code.get(cpt_code)

    def get_block_minutes(self, cpt_code: str) -> int | None:
        return self.block_minutes.get(cpt_code)

    def get_time_band_bounds(self, cpt_code: str) -> tuple[float, float | None]:
        return self.time_bands[cpt_code]

    def get_area_threshold_sq_cm(self, cpt_code: str) -> int | None:
        return self.area_threshold.get(cpt_code)


def get_category_rule_store() -> CategoryRuleStore:
    global _store
    if _store is None:
        _store = CategoryRuleStore(
            BILLING_FILES["categories"],
            BILLING_FILES["general"],
        )
    return _store


def reset_category_rule_store() -> None:
    global _store
    _store = None
