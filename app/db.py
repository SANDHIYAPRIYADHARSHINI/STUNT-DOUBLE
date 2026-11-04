"""SQLite-only helpers for disposable synthetic sandbox databases."""

import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from app.services.privacy_shield import mask_record


def database_path(url: str) -> Path:
    """Validate a file-backed SQLite URL and return its absolute path."""
    parsed = make_url(url)
    if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise ValueError("Only file-backed SQLite databases are supported")
    return Path(parsed.database).resolve()


def create_fresh_sandbox_copy(destination: Path) -> None:
    """Copy a synthetic, privacy-masked fixture into a disposable SQLite file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Never connect to DATABASE_URL: production/source adapters are intentionally absent.
    # TODO: Add reviewed Vultr isolation and a privacy-safe snapshot adapter.
    with closing(sqlite3.connect(":memory:")) as source:
        source.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, "
            "phone TEXT, active INTEGER)"
        )
        for row in (
            {
                "id": 1,
                "name": "Demo One",
                "email": "one@example.invalid",
                "phone": "0001",
                "active": 0,
            },
            {
                "id": 2,
                "name": "Demo Two",
                "email": "two@example.invalid",
                "phone": "0002",
                "active": 1,
            },
        ):
            masked = mask_record(row)
            source.execute(
                "INSERT INTO customers VALUES (:id, :name, :email, :phone, :active)", masked
            )
        source.commit()
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target)


def read_customers(connection: sqlite3.Connection) -> dict[int, dict]:
    """Read synthetic customers for before/after row comparison."""
    connection.row_factory = sqlite3.Row
    return {
        row["id"]: dict(row) for row in connection.execute("SELECT * FROM customers ORDER BY id")
    }
