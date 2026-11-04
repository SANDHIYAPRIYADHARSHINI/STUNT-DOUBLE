"""Three deterministic mock agents operating on independent persistent SQLite copies."""

import sqlite3
from contextlib import closing
from typing import Any

from app.config import Settings
from app.db import (
    configured_demo_paths,
    create_demo_database,
    read_customers,
    reset_sandboxes,
    sandbox_lock,
)
from app.models import AgentRun, DatabaseChange, Task
from app.services.privacy_shield import mask_record


def capture_changes(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
) -> list[DatabaseChange]:
    """Capture inserted, updated, and deleted rows by primary key."""
    changes = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old != new:
            operation = "insert" if old is None else "delete" if new is None else "update"
            changes.append(
                DatabaseChange(
                    table="customers", row_id=key, operation=operation, before=old, after=new
                )
            )
    return changes


def run_agents(task: Task, config: Settings) -> list[AgentRun]:
    """Reset demo copies and rehearse a fixed mock plan without touching production."""
    source, paths = configured_demo_paths(config)
    runs = []
    # Serialize resets and execution across threads in this single-worker local demo.
    # TODO: Add Vultr worker isolation and cross-process run coordination.
    with sandbox_lock:
        create_demo_database(source)
        reset_sandboxes(source, paths)
        for index, path in enumerate(paths, start=1):
            with closing(sqlite3.connect(path, timeout=config.agent_timeout_seconds)) as connection:
                with connection:
                    # Mask only the copies, preserving the fake source for future resets.
                    for row in read_customers(connection).values():
                        connection.execute(
                            "UPDATE customers SET name=:name, email=:email, "
                            "phone=:phone WHERE id=:id",
                            mask_record(row),
                        )
                    before = read_customers(connection)
                    # TODO: Integrate Gemma plans with policy checks and hard worker timeouts.
                    sql = ""
                    if (
                        "delete" in task.description.lower()
                        and "inactive" in task.description.lower()
                    ):
                        sql = "DELETE FROM customers WHERE status = 'inactive'"
                        connection.execute(sql)
                    after = read_customers(connection)
                    runs.append(
                        AgentRun(
                            task_id=task.id,
                            agent=f"mock-agent-{index}",
                            sql=sql,
                            changes=capture_changes(before, after),
                        )
                    )
    return runs
