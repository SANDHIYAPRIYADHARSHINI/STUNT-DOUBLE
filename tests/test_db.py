"""Real SQLite source, copy isolation, reset and ownership boundaries."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.config import settings
from app.db import (
    configured_demo_paths,
    create_demo_database,
    create_sandbox_databases,
    database_path,
    initialize_demo_databases,
    read_customers,
    reset_sandboxes,
)
from app.models import Task
from app.services.agent_runner import run_agents


def rows(path: Path) -> dict[int, dict]:
    """Read persisted rows with a closed connection."""
    with closing(sqlite3.connect(path)) as connection:
        return read_customers(connection)


def execute(path: Path, sql: str) -> None:
    """Commit a test mutation to one synthetic database."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(sql)


def test_creation_schema_and_initial_data():
    paths = initialize_demo_databases()
    source, configured_paths = configured_demo_paths(settings)
    assert paths == configured_paths
    assert len(paths) == len(set(paths)) == 3
    assert source.is_file() and all(path.is_file() for path in paths)
    original = rows(source)
    assert len(original) == 3
    assert all(rows(path) == original for path in paths)
    assert set(original[1]) == {
        "id",
        "name",
        "email",
        "phone",
        "status",
        "created_at",
        "last_active_at",
    }
    assert all(row["email"].endswith("@example.invalid") for row in original.values())
    assert all(row["name"].startswith("Demo ") for row in original.values())
    assert {row["status"] for row in original.values()} == {"active", "inactive"}
    assert not database_path(settings.database_url).exists()


def test_isolation():
    paths = initialize_demo_databases()
    source, _ = configured_demo_paths(settings)
    original = rows(source)
    execute(paths[0], "DELETE FROM customers WHERE id=1")
    execute(paths[1], "UPDATE customers SET status='inactive' WHERE id=2")
    execute(paths[2], "UPDATE customers SET name='Demo Changed' WHERE id=3")
    assert 1 not in rows(paths[0])
    assert rows(paths[1])[2]["status"] == "inactive"
    assert rows(paths[2])[3]["name"] == "Demo Changed"
    assert rows(paths[0])[2] == original[2]
    assert rows(paths[1])[1] == original[1]
    assert rows(paths[2])[1] == original[1]
    assert rows(source) == original


def test_reset_restores_rows_and_schema():
    paths = initialize_demo_databases()
    source, _ = configured_demo_paths(settings)
    original_bytes = source.read_bytes()
    execute(paths[0], "DELETE FROM customers")
    execute(paths[1], "DROP TABLE customers")
    execute(paths[2], "CREATE TABLE extra (id INTEGER)")
    assert reset_sandboxes(source, paths) == paths
    for path in paths:
        assert rows(path) == rows(source)
        with closing(sqlite3.connect(path)) as connection:
            assert not connection.execute(
                "SELECT name FROM sqlite_master WHERE name='extra'"
            ).fetchall()
    assert source.read_bytes() == original_bytes


def test_initialization_is_idempotent():
    paths = initialize_demo_databases()
    source, _ = configured_demo_paths(settings)
    original_bytes = source.read_bytes()
    assert create_demo_database(source) == source
    assert initialize_demo_databases() == paths
    assert source.read_bytes() == original_bytes
    assert len(rows(source)) == 3


def test_rehearsal_resets_before_every_run():
    initialize_demo_databases()
    source, paths = configured_demo_paths(settings)
    original = rows(source)
    execute(paths[0], "DROP TABLE customers")
    task = Task(description="Delete inactive customers")
    for _ in range(2):
        runs = run_agents(task, settings)
        assert len(runs) == 3
        assert all(len(run.changes) == 1 for run in runs)
        assert all(run.changes[0].before["status"] == "inactive" for run in runs)
        assert all(1 not in rows(path) for path in paths)
        assert all(rows(path)[2]["email"].startswith("synthetic_") for path in paths)
        assert rows(source) == original


def test_refuses_unmanaged_source(tmp_path):
    source = tmp_path / "existing.db"
    execute(source, "CREATE TABLE production_data (id INTEGER)")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="unmanaged"):
        create_demo_database(source)
    with pytest.raises(ValueError, match="unmanaged"):
        create_sandbox_databases(source, [tmp_path / f"sandbox{i}.db" for i in range(3)])
    assert source.read_bytes() == original


def test_refuses_unmanaged_destination_before_reset():
    paths = initialize_demo_databases()
    source, _ = configured_demo_paths(settings)
    execute(paths[0], "DELETE FROM customers")
    with closing(sqlite3.connect(paths[2])) as connection:
        connection.execute("PRAGMA application_id=0")
    original = paths[2].read_bytes()
    with pytest.raises(ValueError, match="unmanaged"):
        reset_sandboxes(source, paths)
    assert rows(paths[0]) == {}  # Earlier copies were not reset before validation failed.
    assert paths[2].read_bytes() == original


def test_distinct_paths_required():
    paths = initialize_demo_databases()
    source, _ = configured_demo_paths(settings)
    for invalid in ([source, paths[1], paths[2]], [paths[0]] * 3, paths[:2]):
        with pytest.raises(ValueError, match="distinct"):
            create_sandbox_databases(source, invalid)


def test_rejects_production_alias_before_creating_demo(monkeypatch):
    monkeypatch.setattr(settings, "demo_source_database_url", settings.database_url)
    with pytest.raises(ValueError, match="production"):
        initialize_demo_databases()
    assert not database_path(settings.database_url).exists()


def test_rejects_hardlinked_destination(tmp_path):
    paths = initialize_demo_databases()
    source, _ = configured_demo_paths(settings)
    alias = tmp_path / "alias.db"
    os.link(source, alias)
    with pytest.raises(ValueError, match="same file"):
        reset_sandboxes(source, [alias, *paths[1:]])


@pytest.mark.parametrize(
    "url", ["postgresql://localhost/demo", "sqlite:///:memory:", "sqlite:///file.db?mode=ro"]
)
def test_only_plain_sqlite_paths(url):
    with pytest.raises(ValueError):
        database_path(url)
