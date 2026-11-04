"""Configurable mock plans, isolated SQLite execution and normalized observations."""

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.db import (
    configured_demo_paths,
    create_demo_database,
    read_customers,
    reset_sandboxes,
    sandbox_lock,
)
from app.models import DatabaseChange, RunResult, SQLOperation, Task
from app.services.privacy_shield import mask_record


class AgentPlan(BaseModel):
    """Provider output without database handles or filesystem access."""

    sql_operations: list[str] = Field(default_factory=list)
    raw_output: str


class RehearsalAgent(Protocol):
    """Replaceable plan provider; only the runner can execute sandbox SQL."""

    agent_id: str

    def plan(self, task: Task) -> AgentPlan:
        """Propose SQL for the supplied task without opening a database."""
        ...


@dataclass(frozen=True)
class MockAgent:
    """Deterministic safe or intentionally overbroad delete planner."""

    agent_id: str
    dangerous_delete: bool = False

    def plan(self, task: Task) -> AgentPlan:
        """Return constant SQL for the supported task; never interpolate user text."""
        text = task.description.lower()
        if "delete" not in text or "inactive" not in text:
            return AgentPlan(
                raw_output="Unsupported task: mock only supports deleting inactive customers."
            )
        sql = "DELETE FROM customers"
        if not self.dangerous_delete:
            sql += " WHERE status = 'inactive'"
        return AgentPlan(sql_operations=[sql], raw_output=f"Mock proposed: {sql}")


def get_agents() -> Sequence[RehearsalAgent]:
    """Provide three independent planners; override this FastAPI dependency to configure."""
    # TODO: Replace plan providers with Gemma/LLM adapters using the AgentPlan contract.
    # Keep SQL execution and sandbox credentials outside the model adapter.
    return (
        MockAgent("mock-agent-1"),
        MockAgent("mock-agent-2"),
        MockAgent("mock-agent-3", dangerous_delete=True),
    )


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


def _authorize(
    action: int, table: str | None, column: str | None, database: str | None, trigger: str | None
) -> int:
    # Limit current providers to customer DML: no ATTACH, filesystem functions, DDL,
    # explicit COMMIT/ROLLBACK, PRAGMA, or metadata writes can escape the transaction.
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if (
        action
        in {
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
        }
        and table == "customers"
        and database == "main"
    ):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _execute_agent(agent: RehearsalAgent, task: Task, path: Path, config: Settings) -> RunResult:
    result = RunResult(task_id=task.id, agent=agent.agent_id)
    try:
        plan = agent.plan(task)
        result.raw_output = plan.raw_output
        if not plan.sql_operations:
            result.status = "skipped"
            return result
        with closing(sqlite3.connect(path, timeout=config.agent_timeout_seconds)) as connection:
            # Prepare privacy-masked baseline separately; only agent mutations enter its diff.
            with connection:
                for row in read_customers(connection).values():
                    connection.execute(
                        "UPDATE customers SET name=:name, email=:email, phone=:phone WHERE id=:id",
                        mask_record(row),
                    )
            baseline = read_customers(connection)
            connection.execute("BEGIN")
            connection.set_authorizer(_authorize)
            try:
                for sql in plan.sql_operations:
                    operation = SQLOperation(sql=sql, status="failed")
                    result.sql_operations.append(operation)
                    before = read_customers(connection)
                    try:
                        connection.execute(sql)
                        after = read_customers(connection)
                        operation.changes = capture_changes(before, after)
                        operation.status = "completed"
                    except Exception as exc:
                        operation.error = str(exc)
                        raise
                final = read_customers(connection)
            except Exception:
                connection.set_authorizer(None)
                connection.rollback()
                for operation in result.sql_operations:
                    if operation.status == "completed":
                        operation.status = "rolled_back"
                raise
            else:
                connection.set_authorizer(None)
                try:
                    connection.commit()
                except Exception:
                    connection.rollback()
                    for operation in result.sql_operations:
                        operation.status = "rolled_back"
                    raise
                result.changes = capture_changes(baseline, final)
    except Exception as exc:
        # One provider's failure must not discard other agents' results.
        result.status = "failed"
        result.error = f"{type(exc).__name__}: {exc}"
    result.sql = ";\n".join(operation.sql for operation in result.sql_operations)
    return result


def run_agents(
    task: Task, config: Settings, agents: Sequence[RehearsalAgent] | None = None
) -> list[RunResult]:
    """Reset three copies and execute independently with separate transactions/results."""
    providers = tuple(get_agents() if agents is None else agents)
    if len(providers) != 3 or len({agent.agent_id for agent in providers}) != 3:
        raise ValueError("Exactly three agents with distinct agent IDs are required")
    source, paths = configured_demo_paths(config)
    # TODO: Move each execution to a restricted Vultr worker with hard timeouts and
    # cross-process coordination. Current lock supports a single local API worker.
    with sandbox_lock:
        create_demo_database(source)
        reset_sandboxes(source, paths)
        return [
            _execute_agent(agent, task, path, config)
            for agent, path in zip(providers, paths, strict=True)
        ]
