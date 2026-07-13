"""One-off migration: isTimed -> billingRule in billing JSON files."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "data" / "billing"


def migrate_general(path: Path) -> None:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    for row in rows:
        if "billingRule" in row:
            continue
        if "isTimed" in row:
            val = row.pop("isTimed")
            row["billingRule"] = "8_minute_rule" if val is True else None
    path.write_text(json.dumps(rows, indent=4) + "\n", encoding="utf-8")


def strip_is_timed(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return
    for row in data:
        if isinstance(row, dict):
            row.pop("isTimed", None)
    path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def main() -> None:
    migrate_general(BASE / "cpt_general_info.json")
    for name in (
        "cpt_aoc_info.json",
        "cpt_mue_info.json",
        "cpt_icd10_info.json",
        "cpt_ptp_info.json",
    ):
        strip_is_timed(BASE / name)
    print("billingRule JSON migration complete")


if __name__ == "__main__":
    main()
