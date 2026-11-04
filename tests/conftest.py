"""Isolate test metadata and sandbox directories."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import store


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch) -> Iterator[None]:
    """Prevent test writes outside a temporary synthetic sandbox root."""
    for index in range(1, 4):
        monkeypatch.setattr(
            settings,
            f"sandbox_database_url_{index}",
            f"sqlite:///{tmp_path / str(index) / 'sandbox.db'}",
        )
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'source.db'}")
    with store.lock:
        store.tasks.clear()
        store.runs.clear()
        store.decisions.clear()
        store.audit_log.clear()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Expose a local in-process API client."""
    with TestClient(app) as test_client:
        yield test_client
