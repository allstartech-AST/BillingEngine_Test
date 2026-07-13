"""
Verify billing calculator logic against category rules.
Run: python temp/verify_billing_calculators.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEMP = Path(__file__).resolve().parent


@dataclass
class SegmentUnits:
    cpt_code: str
    minutes_exact: float
    minutes_billed: int
    units: int
    method: str
    sequences: list


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
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(cats)
        for e in general:
            self.rule_by_code[e["cpt_code"]] = e["billingRule"]

    def get_rule(self, cpt_code: str) -> str | None:
        return self.rule_by_code.get(cpt_code)

    def get_block_minutes(self, cpt_code: str) -> int | None:
        return self.block_minutes.get(cpt_code)

    def get_time_band_bounds(self, cpt_code: str) -> tuple[float, float | None]:
        return self.time_bands[cpt_code]

    def get_area_threshold_sq_cm(self, cpt_code: str) -> int | None:
        return self.area_threshold.get(cpt_code)


def _parse_time_band(text: str) -> tuple[float, float | None]:
    cleaned = text.replace(" minutes", "").strip()
    if cleaned.endswith("+"):
        return float(re.search(r"(\d+)", cleaned).group(1)), None
    low, high = cleaned.split("-")
    return float(low), float(high)


class AddOnCodeStore:
    def __init__(self, aoc_path: Path):
        entries = json.loads(aoc_path.read_text(encoding="utf-8"))
        self.by_code = {e["cpt_code"]: e for e in entries}

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
        bt = self.by_code[cpt_code].get("billingTime", "")
        if bt == "same as primary":
            parent = self.by_code[cpt_code]["parentCode"]
            bt = self.by_code[parent].get("billingTime", "")
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
        bt = self.by_code[cpt_code].get("billingTime", "")
        m = re.search(r"(\d+)\s*sq\s*cm", bt)
        return int(m.group(1)) if m else 0


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, TEMP / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    # Inject mocks
    fake_eight = type(sys)("app.engine.eight_minute")
    fake_eight.SegmentUnits = SegmentUnits
    fake_cats = type(sys)("app.engine.pt_ot_slp_billing_categories")
    fake_cats.CategoryRuleStore = CategoryRuleStore
    fake_aoc = type(sys)("app.engine.cpt_aoc_info")
    fake_aoc.AddOnCodeStore = AddOnCodeStore
    sys.modules["app.engine.eight_minute"] = fake_eight
    sys.modules["app.engine.pt_ot_slp_billing_categories"] = fake_cats
    sys.modules["app.engine.cpt_aoc_info"] = fake_aoc
    sys.modules["app"] = type(sys)("app")
    sys.modules["app.engine"] = type(sys)("app.engine")
    spec.loader.exec_module(mod)
    return mod


def seg(minutes: float, sequences: list | None = None, area_sq_cm: float = 0) -> dict:
    sequences = sequences if sequences is not None else [1]
    return {
        "minutes": minutes,
        "minutes_exact": minutes,
        "minutes_billed": int(minutes),
        "sequences": sequences,
        "area_sq_cm": area_sq_cm,
    }


def units_map(results) -> dict[str, int]:
    return {r.cpt_code: r.units for r in results}


class TestCase:
    def __init__(self, name: str, fn, segments: dict, expected: dict):
        self.name = name
        self.fn = fn
        self.segments = segments
        self.expected = expected


def run_tests():
    cat_store = CategoryRuleStore(
        BASE / "pt_ot_slp_billing_categories.json",
        BASE / "billing/cpt_general_info.json",
    )
    aoc_store = AddOnCodeStore(BASE / "billing/cpt_aoc_info.json")

    mods = {
        "eight_minute_rule": _load_module("eight_minute_rule", "eight_minute_rule.py"),
        "full_block_required": _load_module("full_block_required", "full_block_required.py"),
        "untimed_per_session": _load_module("untimed_per_session", "untimed_per_session.py"),
        "untimed_per_encounter": _load_module("untimed_per_encounter", "untimed_per_encounter.py"),
        "untimed_per_procedure": _load_module("untimed_per_procedure", "untimed_per_procedure.py"),
        "untimed_per_day": _load_module("untimed_per_day", "untimed_per_day.py"),
        "untimed_per_episode": _load_module("untimed_per_episode", "untimed_per_episode.py"),
        "area_based": _load_module("area_based", "area_based.py"),
        "time_band_select": _load_module("time_band_select", "time_band_select.py"),
    }

    tests = [
        TestCase(
            "8min: single code 22 min",
            lambda s: mods["eight_minute_rule"].calculate_units(s, cat_store, aoc_store),
            {"97110": seg(22)},
            {"97110": 1},
        ),
        TestCase(
            "8min: single code 23 min",
            lambda s: mods["eight_minute_rule"].calculate_units(s, cat_store, aoc_store),
            {"97110": seg(23)},
            {"97110": 2},
        ),
        TestCase(
            "8min: pair 90912+90913 30 min",
            lambda s: mods["eight_minute_rule"].calculate_units(s, cat_store, aoc_store),
            {"90912": seg(20), "90913": seg(10)},
            {"90912": 1, "90913": 1},
        ),
        TestCase(
            "8min: pair + pooled 97110",
            lambda s: mods["eight_minute_rule"].calculate_units(s, cat_store, aoc_store),
            {"97110": seg(45), "90912": seg(23), "90913": seg(0)},
            {"97110": 3, "90912": 1, "90913": 1},
        ),
        TestCase(
            "8min: global pool caps split codes",
            lambda s: mods["eight_minute_rule"].calculate_units(s, cat_store, aoc_store),
            {"97110": seg(23), "90912": seg(23), "90913": seg(0)},
            {"97110": 1, "90912": 1, "90913": 1},
        ),
        TestCase(
            "full_block: 92607 60 min",
            lambda s: mods["full_block_required"].calculate_units(s, cat_store, aoc_store),
            {"92607": seg(60)},
            {"92607": 1},
        ),
        TestCase(
            "full_block: 92607 59 min",
            lambda s: mods["full_block_required"].calculate_units(s, cat_store, aoc_store),
            {"92607": seg(59)},
            {"92607": 0},
        ),
        TestCase(
            "full_block: addon 97551 30 min",
            lambda s: mods["full_block_required"].calculate_units(s, cat_store, aoc_store),
            {"97550": seg(30), "97551": seg(30)},
            {"97550": 1, "97551": 2},
        ),
        TestCase(
            "session: once per session",
            lambda s: mods["untimed_per_session"].calculate_units(s, cat_store),
            {"92507": seg(0, [1, 2, 3])},
            {"92507": 1},
        ),
        TestCase(
            "encounter: eval once",
            lambda s: mods["untimed_per_encounter"].calculate_units(s, cat_store),
            {"97163": seg(89, [1])},
            {"97163": 1},
        ),
        TestCase(
            "procedure: 3 occurrences",
            lambda s: mods["untimed_per_procedure"].calculate_units(s, cat_store),
            {"95851": seg(0, [1, 2, 3])},
            {"95851": 3},
        ),
        TestCase(
            "per day",
            lambda s: mods["untimed_per_day"].calculate_units(s, cat_store),
            {"97010": seg(0, [1])},
            {"97010": 1},
        ),
        TestCase(
            "per episode",
            lambda s: mods["untimed_per_episode"].calculate_units(s, cat_store),
            {"98975": seg(0, [1])},
            {"98975": 1},
        ),
        TestCase(
            "area: per wound 3 sites",
            lambda s: mods["area_based"].calculate_units(s, cat_store, aoc_store),
            {"97605": seg(0, [1, 2, 3])},
            {"97605": 3},
        ),
        TestCase(
            "area: 97597 25 sq cm",
            lambda s: mods["area_based"].calculate_units(s, cat_store, aoc_store),
            {"97597": seg(0, [1], 25)},
            {"97597": 1},
        ),
        TestCase(
            "area: addon 97598 40 sq cm",
            lambda s: mods["area_based"].calculate_units(s, cat_store, aoc_store),
            {"97597": seg(0, [1], 20), "97598": seg(0, [1], 40)},
            {"97597": 1, "97598": 2},
        ),
        TestCase(
            "time band: 8 min picks one 5-10 code",
            lambda s: mods["time_band_select"].calculate_units(s, cat_store),
            {"98966": seg(8), "98967": seg(8)},
            {"98966": 1, "98967": 0},
        ),
        TestCase(
            "time band: 15 min",
            lambda s: mods["time_band_select"].calculate_units(s, cat_store),
            {"98967": seg(15), "98971": seg(15)},
            {"98967": 1, "98971": 0},
        ),
    ]

    passed = 0
    failed = []
    for t in tests:
        got = units_map(t.fn(t.segments))
        exp = t.expected
        ok = got == exp
        if ok:
            passed += 1
        else:
            failed.append((t.name, exp, got))

    # Coverage: all 98 codes should map to a billing rule
    all_codes = {
        e["cpt_code"]
        for e in json.loads((BASE / "billing/cpt_general_info.json").read_text())
    }
    ruled = set(cat_store.rule_by_code.keys())
    missing_rule = sorted(all_codes - ruled)

    print(f"Tests: {passed}/{len(tests)} passed")
    for name, exp, got in failed:
        print(f"  FAIL {name}")
        print(f"       expected {exp}")
        print(f"       got      {got}")
    if missing_rule:
        print(f"Codes missing rule mapping: {missing_rule}")
    return failed, passed, len(tests)


if __name__ == "__main__":
    failed, passed, total = run_tests()
    sys.exit(1 if failed else 0)
