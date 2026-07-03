"""One-off: restore engine modules from agent transcript (last Write + StrReplace chain)."""
import json
from pathlib import Path

TRANSCRIPT = Path(
    r"C:\Users\DELL\.cursor\projects\c-AllStar-CodeTest-ProperData\agent-transcripts"
    r"\3f12d943-ec25-4614-8301-1cef14e5e131\3f12d943-ec25-4614-8301-1cef14e5e131.jsonl"
)
ROOT = Path(__file__).resolve().parent.parent

RESTORE = {
    "app/engine/evaluation_status.py",
    "app/engine/pending_review.py",
    "app/engine/detection_summary.py",
    "app/engine/segment_review.py",
    "app/engine/temporal_overlap.py",
    "app/engine/icd_semantic.py",
    "app/engine/icd10.py",
    "app/engine/duration.py",
    "app/engine/conflicts.py",
    "app/engine/human_summary.py",
    "app/engine/lookup_matcher.py",
    "app/engine/transcript_medexa.py",
    "app/engine/eight_minute.py",
    "app/models/input.py",
    "tests/test_conflicts.py",
    "tests/test_segment_review.py",
    "tests/test_detection_summary.py",
    "tests/test_temporal_overlap.py",
    "tests/test_duration_timeline.py",
}


def _rel(path_raw: str) -> str | None:
    p = path_raw.replace("\\", "/")
    marker = "ProperData/"
    if marker not in p:
        return None
    return p.split(marker, 1)[1]


def main() -> None:
    writes: dict[str, str] = {}
    patches: dict[str, list[tuple[str, str]]] = {}

    for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for part in obj.get("message", {}).get("content", []):
            if part.get("type") != "tool_use":
                continue
            name = part.get("name")
            inp = part.get("input", {})
            rel = _rel(inp.get("path", ""))
            if not rel or rel not in RESTORE:
                continue
            if name == "Write":
                writes[rel] = inp.get("contents", "")
            elif name == "StrReplace":
                patches.setdefault(rel, []).append(
                    (inp.get("old_string", ""), inp.get("new_string", ""))
                )

    for rel, content in writes.items():
        text = content
        missed = 0
        for old, new in patches.get(rel, []):
            if old and old in text:
                text = text.replace(old, new, 1)
            elif old:
                missed += 1
        out = ROOT / rel.replace("/", "\\")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {rel} ({len(text)} chars, {missed} patch misses)")

    print(f"restored {len(writes)} files")


if __name__ == "__main__":
    main()
