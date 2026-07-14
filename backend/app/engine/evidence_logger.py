"""Persistent audit log for LLM-suggested CPT detections and transcript evidence."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DETECTION_EVIDENCE_LOG

logger = logging.getLogger(__name__)

_file_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_payload(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for cpt_code, entries in raw.items():
        if isinstance(entries, list):
            normalized[str(cpt_code)] = [entry for entry in entries if isinstance(entry, dict)]
    return normalized


def _load_evidence(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}

    for attempt in range(3):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return _normalize_payload(raw)
        except json.JSONDecodeError as exc:
            backup = path.with_suffix(path.suffix + f".corrupt-{attempt}")
            try:
                shutil.copy2(path, backup)
                logger.error(
                    "Corrupt detection evidence log backed up to %s: %s",
                    backup,
                    exc,
                )
            except OSError:
                logger.error("Corrupt detection evidence log could not be backed up: %s", exc)
            if attempt < 2:
                continue
            return {}
        except OSError as exc:
            logger.warning(
                "Could not read detection evidence log (%s), attempt %s: %s",
                path,
                attempt + 1,
                exc,
            )
            if attempt < 2:
                continue
            return {}
    return {}


def _write_evidence(path: Path, payload: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def log_cpt_detection_evidence(
    session_id: str,
    cpt_code: str,
    *,
    exact_quote: str,
    reasoning: str = "",
    log_path: Path | None = None,
) -> None:
    """
    Append one LLM detection record under the CPT code in detection_evidence.json.

    Called when the therapist approves an AI-suggested CPT — rejected suggestions
    are never logged. The file persists across server restarts; each call adds
    another entry to the CPT's array without removing prior sessions or other CPT keys.
    """
    quote = str(exact_quote or "").strip()
    code = str(cpt_code or "").strip()
    if not code or not quote:
        return

    path = log_path or DETECTION_EVIDENCE_LOG
    record = {
        "exact_quote": quote,
        "reasoning": str(reasoning or "").strip(),
        "session_id": str(session_id or "").strip(),
        "logged_at": _utc_now_iso(),
    }

    with _file_lock:
        payload = _load_evidence(path)
        existing = payload.setdefault(code, [])
        duplicate = any(
            item.get("exact_quote") == record["exact_quote"]
            and item.get("session_id") == record["session_id"]
            for item in existing
        )
        if duplicate:
            return
        existing.append(record)
        _write_evidence(path, payload)

    logger.info(
        "Logged LLM detection evidence for %s (session %s): %r",
        code,
        session_id,
        quote,
    )
