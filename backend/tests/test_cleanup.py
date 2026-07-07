"""Smoke import test — deprecated gemini shim modules must stay removed."""

from __future__ import annotations

from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1] / "app" / "engine"


@pytest.mark.parametrize(
    "filename",
    [
        "gemini_errors.py",
        "gemini_billing_rules.py",
        "summary_gemini_validation.py",
    ],
)
def test_deprecated_gemini_shim_files_removed(filename: str) -> None:
    assert not (ENGINE_DIR / filename).is_file()
