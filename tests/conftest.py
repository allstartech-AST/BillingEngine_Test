import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from app.engine.loader import load_metadata, reset_metadata_cache


@pytest.fixture(scope="session")
def store():
    reset_metadata_cache()
    return load_metadata()
