"""Shared test fixtures. Backend modules import from the backend/ root,
so tests run with backend/ on sys.path (pytest rootdir = backend/)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from config import settings


@pytest.fixture(autouse=True)
def isolated_incident_db(tmp_path, monkeypatch):
    """Every test gets its own empty incident database, so the durable
    incident store never leaks state between tests."""
    monkeypatch.setattr(settings, "incident_db_path", str(tmp_path / "incidents.db"))
    yield
