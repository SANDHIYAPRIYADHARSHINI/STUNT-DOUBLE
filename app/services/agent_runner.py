"""Three deterministic mock agents, each operating on its own disposable copy."""

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.db import create_fresh_sandbox_copy, database_path, read_customers
from app.models import AgentRun, DatabaseChange, Task


def capture_changes(before: dict[int, dict], after: dict[int, dict]) -> list[DatabaseChange]:
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
    """Rehearse a fixed mock plan; natural language is never interpreted as SQL."""
    urls = [
        config.sandbox_database_url_1,
        config.sandbox_database_url_2,
        config.sandbox_database_url_3,
    ]
    paths = [database_path(url) for url in urls]
    if len(set(paths)) != 3 or database_path(config.database_url) in paths:
        raise ValueError("Sandbox paths must be distinct from each other and the source database")
    runs = []
    for index, path in enumerate(paths, start=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique per-run directories avoid concurrent rehearsal collisions.
        with TemporaryDirectory(prefix="rehearsal-", dir=path.parent) as directory:
            sandbox = Path(directory) / path.name
            create_fresh_sandbox_copy(sandbox)
            with closing(
                sqlite3.connect(sandbox, timeout=config.agent_timeout_seconds)
            ) as connection:
                before = read_customers(connection)
                # TODO: Integrate Gemma/LLM plans with SQL policy checks and hard worker timeouts.
                # Fixed mock intentionally demonstrates only this supported task.
                sql = ""
                if "delete" in task.description.lower() and "inactive" in task.description.lower():
                    sql = "DELETE FROM customers WHERE active = 0"
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
