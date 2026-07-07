"""Pytest fixtures for billing engine tests."""

from __future__ import annotations

import pytest

from app.engine.loader import MetadataStore, load_metadata


@pytest.fixture(scope="session")
def store() -> MetadataStore:
    return load_metadata()
