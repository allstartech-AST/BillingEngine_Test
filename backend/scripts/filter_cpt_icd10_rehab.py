"""Filter cpt_icd10_info.json to 98 therapy CPTs and PT/OT/SLP-relevant ICD-10 codes."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPT_SOURCE = ROOT / "temp" / "cpt_general_info.json"
ICD_SOURCE = ROOT / "backend" / "data" / "billing" / "cpt_icd10_info.json"
ICD_OUTPUT = ICD_SOURCE

SPEECH_CPT_PREFIXES = ("925", "926", "937")
SPEECH_CPT_CODES = {
    "96105",
    "96125",
    "G0451",
    "G2251",
}
TELEHEALTH_CPT_CODES = {
    "98966",
    "98967",
    "98968",
    "98970",
    "98971",
    "98972",
}
WOUND_CPT_CODES = {"97597", "97605", "97606", "97607", "97608"}
MODALITY_CPT_CODES = {
    "90901",
    "90912",
    "95992",
    "97010",
    "97012",
    "97016",
    "97018",
    "97022",
    "97024",
    "97026",
    "97028",
    "95851",
    "95852",
    "97602",
    "97610",
    "G0281",
    "G0283",
    "G0329",
}

PT_OT_CORE_CPTS = ("97110",)
SLP_EVAL_CORE_CPTS = ("92507", "92521", "92522", "92523", "92524")
SLP_SWALLOW_CORE_CPTS = ("92526",)
SLP_DYSPHAGIA_CORE_CPTS = ("92610", "92611")

_POISONING = re.compile(r"^T(?:3[6-9]|[4-5]\d|6[0-5])", re.I)
_ACUTE_CNS_INFECTION = re.compile(r"^G0[0-9]", re.I)
_CEREBROVASCULAR = re.compile(r"^I6[0-9]", re.I)
_DIABETES = re.compile(r"^E1[0-3]", re.I)
_Z_REHAB = re.compile(
    r"^Z(?:"
    r"46\.8|"
    r"47|"
    r"48|"
    r"50|"
    r"51\.89|"
    r"74|"
    r"86\.73|"
    r"87\.39|"
    r"87\.82|"
    r"89|"
    r"96\.6"
    r")",
    re.I,
)


def _speech_icd(code: str) -> bool:
    if code.startswith(("F80", "F81", "F82", "F83", "F84", "F88", "F89", "F98")):
        return True
    if code.startswith(("R13", "R47", "R48", "R49")):
        return True
    if code.startswith(("H90", "H91", "H93")):
        return True
    if code.startswith("J38") or code.startswith("J69"):
        return True
    if code.startswith(
        (
            "G30",
            "G31",
            "G35",
            "G37",
            "G40",
            "G43",
            "G44",
            "G45",
            "G50",
            "G51",
            "G52",
            "G54",
            "G56",
            "G57",
            "G58",
            "G60",
            "G61",
            "G62",
            "G70",
            "G71",
            "G72",
            "G73",
            "G80",
            "G81",
            "G82",
            "G83",
            "G89",
            "G90",
            "G91",
            "G93",
            "G95",
        )
    ):
        return True
    if _CEREBROVASCULAR.match(code) or code.startswith("I69"):
        return True
    if code.startswith(("R41", "R42")):
        return True
    if code.startswith("F07"):
        return True
    if code == "B91":
        return True
    if code.startswith("Q"):
        return True
    return False


def _wound_icd(code: str) -> bool:
    if code.startswith(("L89", "L97", "L98")):
        return True
    if _DIABETES.match(code) and ".6" in code:
        return True
    if code.startswith(("S", "T")) and not _POISONING.match(code):
        return True
    if code.startswith("M"):
        return True
    return False


def _pt_ot_icd(code: str) -> bool:
    if code.startswith(("M", "S")):
        return True
    if code.startswith("T") and not _POISONING.match(code):
        return True
    if code.startswith("G") and not _ACUTE_CNS_INFECTION.match(code):
        return True
    if _CEREBROVASCULAR.match(code) or code.startswith("I69"):
        return True
    if code.startswith(("R13", "R26", "R27", "R41", "R42", "R47", "R48", "R49", "R52", "R53", "R54", "R62")):
        return True
    if code.startswith(("H81", "H90", "H91", "H93")):
        return True
    if code.startswith(("F07", "F80", "F81", "F82", "F83", "F84", "F88", "F89", "F98")):
        return True
    if code.startswith("Q"):
        return True
    if code.startswith(("L89", "L97", "L98")):
        return True
    if _DIABETES.match(code):
        return True
    if code.startswith(("J38", "J69")):
        return True
    if _Z_REHAB.match(code):
        return True
    if code == "B91":
        return True
    return False


def is_rehab_icd(code: str, cpt_code: str) -> bool:
    code = code.strip().upper()
    if not code:
        return False
    if cpt_code in WOUND_CPT_CODES:
        return _wound_icd(code)
    if cpt_code.startswith(SPEECH_CPT_PREFIXES) or cpt_code in SPEECH_CPT_CODES:
        return _speech_icd(code) or _pt_ot_icd(code)
    return _pt_ot_icd(code)


def _default_wound_icds() -> list[str]:
    return [
        "L89.000",
        "L89.100",
        "L89.200",
        "L89.300",
        "L89.40",
        "L89.500",
        "L89.600",
        "L97.101",
        "L97.102",
        "L97.109",
        "L97.201",
        "L97.202",
        "L97.209",
        "L97.401",
        "L97.402",
        "L97.409",
        "L97.501",
        "L97.502",
        "L97.509",
        "E11.621",
        "E10.621",
        "E13.621",
        "M86.9",
        "T81.30XA",
        "T81.31XA",
        "T81.32XA",
        "T81.33XA",
        "T81.34XA",
    ]


def _codes_for_cpt(existing: dict[str, dict], cpt_code: str) -> list[str]:
    entry = existing.get(cpt_code, {})
    return [item["code"] for item in entry.get("valid_icd10_codes", []) if item.get("code")]


def _build_master_sets(existing: dict[str, dict]) -> tuple[set[str], set[str], set[str], set[str]]:
    pt_ot_master: set[str] = set()
    for cpt in PT_OT_CORE_CPTS:
        for code in _codes_for_cpt(existing, cpt):
            if _pt_ot_icd(code):
                pt_ot_master.add(code)

    slp_eval_master: set[str] = set()
    for cpt in SLP_EVAL_CORE_CPTS:
        for code in _codes_for_cpt(existing, cpt):
            if _speech_icd(code):
                slp_eval_master.add(code)

    slp_swallow_master: set[str] = set()
    for cpt in SLP_SWALLOW_CORE_CPTS:
        for code in _codes_for_cpt(existing, cpt):
            if _speech_icd(code):
                slp_swallow_master.add(code)

    slp_dysphagia_master: set[str] = set()
    for cpt in SLP_DYSPHAGIA_CORE_CPTS:
        for code in _codes_for_cpt(existing, cpt):
            if _speech_icd(code):
                slp_dysphagia_master.add(code)

    wound_master = set(_default_wound_icds())
    for cpt in WOUND_CPT_CODES:
        for code in _codes_for_cpt(existing, cpt):
            if _wound_icd(code):
                wound_master.add(code)

    return pt_ot_master, slp_eval_master, slp_swallow_master, slp_dysphagia_master, wound_master


def _speech_allowed_set(cpt_code: str, slp_eval_master: set[str], slp_swallow_master: set[str], slp_dysphagia_master: set[str]) -> set[str]:
    if cpt_code in {"92526"}:
        return slp_swallow_master
    if cpt_code.startswith("926") or cpt_code in {"92520"}:
        return slp_dysphagia_master | slp_swallow_master
    if cpt_code in {"93797", "93798"}:
        return slp_eval_master | slp_swallow_master
    return slp_eval_master | slp_swallow_master


def _filter_codes_for_cpt(
    cpt_code: str,
    raw_codes: list[str],
    pt_ot_master: set[str],
    slp_eval_master: set[str],
    slp_swallow_master: set[str],
    slp_dysphagia_master: set[str],
    wound_master: set[str],
) -> list[str]:
    if cpt_code in WOUND_CPT_CODES:
        allowed = wound_master
        filtered = {code for code in raw_codes if code in allowed or _wound_icd(code)}
        if not filtered:
            filtered = set(wound_master)
        return sorted(filtered)

    if cpt_code.startswith(SPEECH_CPT_PREFIXES) or cpt_code in SPEECH_CPT_CODES:
        allowed = _speech_allowed_set(
            cpt_code,
            slp_eval_master,
            slp_swallow_master,
            slp_dysphagia_master,
        )
        return sorted({code for code in raw_codes if code in allowed})

    if cpt_code in MODALITY_CPT_CODES:
        return sorted({code for code in raw_codes if code in pt_ot_master})

    filtered = {code for code in raw_codes if is_rehab_icd(code, cpt_code) and code in pt_ot_master}
    return sorted(filtered)


def filter_crosswalk(existing_path: Path | None = None) -> list[dict]:
    source_path = existing_path or ICD_SOURCE
    with CPT_SOURCE.open(encoding="utf-8") as handle:
        cpt_rows = json.load(handle)
    target_cpts = [row["cpt_code"] for row in cpt_rows]

    with source_path.open(encoding="utf-8") as handle:
        existing = {entry["cpt_code"]: entry for entry in json.load(handle)}

    pt_ot_master, slp_eval_master, slp_swallow_master, slp_dysphagia_master, wound_master = _build_master_sets(existing)
    print(f"Master PT/OT ICDs: {len(pt_ot_master)}")
    print(f"Master SLP eval ICDs: {len(slp_eval_master)}")
    print(f"Master SLP swallow ICDs: {len(slp_swallow_master)}")
    print(f"Master SLP dysphagia ICDs: {len(slp_dysphagia_master)}")
    print(f"Master wound ICDs: {len(wound_master)}")

    output: list[dict] = []
    stats: dict[str, int] = {}

    for cpt_code in target_cpts:
        raw_codes = _codes_for_cpt(existing, cpt_code)
        filtered = _filter_codes_for_cpt(
            cpt_code,
            raw_codes,
            pt_ot_master,
            slp_eval_master,
            slp_swallow_master,
            slp_dysphagia_master,
            wound_master,
        )
        stats[cpt_code] = len(filtered)
        output.append(
            {
                "cpt_code": cpt_code,
                "valid_icd10_codes": [{"code": code} for code in filtered],
            }
        )

    total_icds = sum(stats.values())
    print(f"CPT rows written: {len(output)}")
    print(f"Total ICD mappings: {total_icds}")
    print("Largest CPT mappings:")
    for cpt, count in sorted(stats.items(), key=lambda item: item[1], reverse=True)[:12]:
        print(f"  {cpt}: {count}")
    return output


def main() -> None:
    # Read from a backup of the full crosswalk if we already overwrote the source.
    backup = ICD_SOURCE.with_suffix(".json.bak")
    source = backup if backup.exists() else ICD_SOURCE
    if not backup.exists():
        ICD_SOURCE.replace(backup)
        print(f"Backed up original crosswalk to {backup}")
    filtered = filter_crosswalk(source)
    with ICD_OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(filtered, handle, indent=4)
        handle.write("\n")
    print(f"Wrote {ICD_OUTPUT}")


if __name__ == "__main__":
    main()
