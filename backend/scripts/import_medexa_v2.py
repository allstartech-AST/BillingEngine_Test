"""Extract medexa v2.0.0 JSON from agent transcript and write to data/medexa."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TRANSCRIPT = Path(
    r"C:\Users\DELL\.cursor\projects\c-AllStar-CodeTest-BillingEngine-Prototype"
    r"\agent-transcripts\f210c317-c0b3-4faf-a41e-37b1e0c5b85b"
    r"\f210c317-c0b3-4faf-a41e-37b1e0c5b85b.jsonl"
)
OUT = BACKEND / "data" / "medexa" / "medexa_cpt_lookup.json"
GENERAL = BACKEND / "data" / "billing" / "cpt_general_info.json"

LEGACY_V1_ONLY = {
    "0362T", "0373T", "90913", "92627", "97014", "97037", "97130", "97151",
    "97152", "97153", "97154", "97155", "97156", "97157", "97158", "97169",
    "97170", "97171", "97172", "97546", "98976", "98977", "98981", "98984",
    "98985", "G0542",
}


def main() -> int:
    if not TRANSCRIPT.exists():
        print(f"Transcript not found: {TRANSCRIPT}", file=sys.stderr)
        return 1

    payload = None
    for line in TRANSCRIPT.open(encoding="utf-8"):
        obj = json.loads(line)
        if obj.get("role") != "user":
            continue
        text = obj["message"]["content"][0].get("text", "")
        if '"version": "2.0.0"' not in text or '"90901"' not in text:
            continue
        match = re.search(r"\{\s*\"_meta\"", text)
        if not match:
            continue
        json_text = text[match.start() :]
        for marker in ("}\n\nis this lookup", "}\n</user_query>"):
            end = json_text.find(marker)
            if end != -1:
                json_text = json_text[: end + 1]
                break
        payload = json.loads(json_text)
        break

    if payload is None:
        print("v2 medexa JSON not found in transcript", file=sys.stderr)
        return 1

    codes = [k for k in payload if k != "_meta"]
    general = {e["cpt_code"] for e in json.loads(GENERAL.read_text(encoding="utf-8"))}
    missing = sorted(general - set(codes))
    extra = sorted(set(codes) - general)
    still_legacy = LEGACY_V1_ONLY & set(codes)

    if missing:
        print(f"ERROR: missing general codes in v2: {missing}", file=sys.stderr)
        return 1
    if extra:
        print(f"ERROR: extra codes not in general: {extra}", file=sys.stderr)
        return 1
    if still_legacy:
        print(f"ERROR: legacy v1-only codes still present: {sorted(still_legacy)}", file=sys.stderr)
        return 1

    payload["_meta"]["version"] = "2.0.0"
    OUT.write_text(json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} with {len(codes)} codes (v2.0.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
