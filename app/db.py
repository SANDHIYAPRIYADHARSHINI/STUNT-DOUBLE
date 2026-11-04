"""Owned demo SQLite databases and independent, resettable sandbox copies."""

import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from sqlalchemy.engine import make_url

from app.models import Customer

if TYPE_CHECKING:
    from app.config import Settings

# Identifies databases created by this demo; never adopt an arbitrary existing file.
DEMO_APPLICATION_ID = 1398035780
sandbox_lock = RLock()
DEMO_CUSTOMERS = (
    Customer(
        id=1,
        name="Demo Maya Patel",
        email="maya.patel@example.invalid",
        phone="+1-202-555-0101",
        status="inactive",
        created_at="2024-01-15T09:00:00Z",
        last_active_at="2024-06-20T12:00:00Z",
    ),
    Customer(
        id=2,
        name="Demo Oliver Reed",
        email="oliver.reed@example.invalid",
        phone="+1-202-555-0102",
        status="active",
        created_at="2024-03-10T10:00:00Z",
        last_active_at="2026-10-30T14:30:00Z",
    ),
    Customer(
        id=3,
        name="Demo Aisha Khan",
        email="aisha.khan@example.invalid",
        phone="+1-202-555-0103",
        status="active",
        created_at="2025-07-01T08:00:00Z",
        last_active_at="2026-11-01T16:15:00Z",
    ),
)


def database_path(url: str) -> Path:
    """Validate a local file-backed SQLite URL and return its absolute path."""
    parsed = make_url(url)
    if (
        parsed.drivername != "sqlite"
        or not parsed.database
        or parsed.database == ":memory:"
        or parsed.query
        or parsed.host
    ):
        raise ValueError("Only local file-backed SQLite databases are supported")
    return Path(parsed.database).resolve()


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _require_owned(path: Path) -> None:
    try:
        with closing(_readonly(path)) as connection:
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    except sqlite3.Error as exc:
        raise ValueError(f"Not an owned demo database: {path}") from exc
    if application_id != DEMO_APPLICATION_ID:
        raise ValueError(f"Refusing to use an unmanaged database: {path}")


def _validate_paths(source: Path, destinations: list[Path]) -> None:
    paths = [source, *destinations]
    if len(destinations) != 3 or len(set(paths)) != 4:
        raise ValueError("Source and three sandbox paths must all be distinct")
    for index, path in enumerate(paths):
        for other in paths[:index]:
            if path.exists() and other.exists() and path.samefile(other):
                raise ValueError("Database paths must not reference the same file")


def create_demo_database(path: Path) -> Path:
    """Create a fake customer source once, refusing to overwrite unmanaged files."""
    path = path.resolve()
    with sandbox_lock:
        if path.exists():
            _require_owned(path)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents silently adopting a file created by another process.
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(f"PRAGMA application_id = {DEMO_APPLICATION_ID}")
            connection.execute(
                "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "email TEXT NOT NULL, phone TEXT NOT NULL, "
                "status TEXT NOT NULL CHECK (status IN ('active', 'inactive')), "
                "created_at TEXT NOT NULL, last_active_at TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO customers VALUES "
                "(:id, :name, :email, :phone, :status, :created_at, :last_active_at)",
                [customer.model_dump(mode="json") for customer in DEMO_CUSTOMERS],
            )
    return path


def create_fresh_sandbox_copy(source: Path, destination: Path) -> Path:
    """Back up an owned demo source to an independent owned/new SQLite file."""
    source, destination = source.resolve(), destination.resolve()
    with sandbox_lock:
        if source == destination or (
            source.exists() and destination.exists() and source.samefile(destination)
        ):
            raise ValueError("Source and sandbox must be different files")
        _require_owned(source)
        if destination.exists():
            _require_owned(destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb"):
                pass
        with closing(_readonly(source)) as original:
            with closing(sqlite3.connect(destination)) as sandbox:
                original.backup(sandbox)
    return destination


def create_sandbox_databases(source: Path, destinations: list[Path]) -> list[Path]:
    """Create three independent copies, validating every path before any write."""
    source = source.resolve()
    destinations = [path.resolve() for path in destinations]
    with sandbox_lock:
        _validate_paths(source, destinations)
        _require_owned(source)
        for path in destinations:
            if path.exists():
                _require_owned(path)
        return [create_fresh_sandbox_copy(source, path) for path in destinations]


def reset_sandboxes(source: Path, destinations: list[Path]) -> list[Path]:
    """Restore all three sandbox schemas and rows from the unchanged demo source."""
    return create_sandbox_databases(source, destinations)


def read_customers(connection: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """Read customers by primary key for before/after comparison."""
    connection.row_factory = sqlite3.Row
    return {
        row["id"]: dict(row) for row in connection.execute("SELECT * FROM customers ORDER BY id")
    }


def initialize_demo_databases() -> list[Path]:
    """Initialize the configured demo source and reset its three sandbox files."""
    from app.config import settings

    source, destinations = configured_demo_paths(settings)
    with sandbox_lock:
        create_demo_database(source)
        return reset_sandboxes(source, destinations)


def configured_demo_paths(config: "Settings") -> tuple[Path, list[Path]]:
    """Resolve demo paths and reject any alias to the reserved production URL."""
    source = database_path(config.demo_source_database_url)
    destinations = [
        database_path(getattr(config, f"sandbox_database_url_{index}")) for index in range(1, 4)
    ]
    production = database_path(config.database_url)
    _validate_paths(source, destinations)
    for path in [source, *destinations]:
        if path == production or (
            path.exists() and production.exists() and path.samefile(production)
        ):
            raise ValueError("Demo databases must not reference the production database")
    return source, destinations


if __name__ == "__main__":
    for sandbox_path in initialize_demo_databases():
        print(sandbox_path)
