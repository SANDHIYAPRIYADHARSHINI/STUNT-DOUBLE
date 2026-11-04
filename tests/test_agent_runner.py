"""Three-agent results, statement observations, configurable plans and failures."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass

import pytest

from app.config import settings
from app.db import configured_demo_paths, read_customers
from app.main import app
from app.models import RunResult, Task
from app.services.agent_runner import AgentPlan, MockAgent, get_agents, run_agents


@dataclass
class StubAgent:
    """Configurable deterministic provider, with no connection access."""

    agent_id: str
    statements: list[str]

    def plan(self, task: Task) -> AgentPlan:
        """Return test statements with a mock raw response."""
        return AgentPlan(sql_operations=self.statements, raw_output="stub response")


def test_default_agents_and_isolation():
    task = Task(description="Delete inactive customers.")
    results = run_agents(task, settings)
    assert all(isinstance(result, RunResult) for result in results)
    assert [result.agent_id for result in results] == [f"mock-agent-{i}" for i in range(1, 4)]
    assert len({result.id for result in results}) == 3
    assert all(result.task_id == task.id and result.status == "completed" for result in results)
    assert [result.affected_row_count for result in results] == [1, 1, 3]
    assert [len(result.deleted_rows) for result in results] == [1, 1, 3]
    assert results[0].sql == results[1].sql == "DELETE FROM customers WHERE status = 'inactive'"
    assert results[2].sql == "DELETE FROM customers"
    assert all(result.raw_output and not result.error for result in results)
    assert all(not result.inserted_rows and not result.updated_rows for result in results)
    source, paths = configured_demo_paths(settings)
    for path, count in zip([source, *paths], [3, 2, 2, 0], strict=True):
        with closing(sqlite3.connect(path)) as connection:
            assert len(read_customers(connection)) == count
    assert results[0].deleted_rows[0]["email"].startswith("synthetic_")


def test_api_roundtrip_returns_all_normalized_results(client):
    task = client.post("/tasks", json={"description": "Delete inactive customers."}).json()
    response = client.post("/sandbox/run", json={"task_id": task["id"]})
    assert response.status_code == 201
    run = response.json()
    fetched = client.get(f"/sandbox/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == run
    assert [agent["affected_row_count"] for agent in run["agents"]] == [1, 1, 3]
    for result in run["agents"]:
        assert {
            "agent_id",
            "task_id",
            "sql_operations",
            "inserted_rows",
            "updated_rows",
            "deleted_rows",
            "affected_row_count",
            "status",
            "raw_output",
        } <= result.keys()
        assert result["sql_operations"][0]["status"] == "completed"
        assert result["task_id"] == task["id"]
    assert run["diffs"]["affected_row_count"] == 3
    assert len(run["diffs"]["unanimous_changes"]) == 1
    assert len(run["diffs"]["partial_agreement_changes"]) == 2
    assert run["risk"]["level"] == "critical"
    assert run["status"] == "completed"


def test_insert_update_delete_events_are_captured_even_with_no_net_change():
    statements = [
        "INSERT INTO customers SELECT 99, name, email, phone, status, created_at, "
        "last_active_at FROM customers WHERE id=2",
        "UPDATE customers SET status='inactive' WHERE id=99",
        "DELETE FROM customers WHERE id=99",
    ]
    providers = [StubAgent(f"stub-{i}", statements) for i in range(3)]
    for result in run_agents(Task(description="test"), settings, providers):
        assert result.status == "completed"
        assert (
            len(result.inserted_rows) == len(result.updated_rows) == len(result.deleted_rows) == 1
        )
        assert result.inserted_rows[0]["id"] == 99
        assert result.updated_rows[0].before["status"] == "active"
        assert result.updated_rows[0].after["status"] == "inactive"
        assert result.deleted_rows[0]["status"] == "inactive"
        assert result.affected_row_count == 1
        assert result.changes == []  # Consensus compares the final committed state.
        assert [operation.sql for operation in result.sql_operations] == statements
        assert [len(operation.changes) for operation in result.sql_operations] == [1, 1, 1]
        assert result.raw_output == "stub response"


def test_failed_agent_rolls_back_and_does_not_stop_other_agents():
    providers = [
        MockAgent("safe-1"),
        StubAgent(
            "broken",
            [
                "DELETE FROM customers WHERE status='inactive'",
                "DELETE FROM missing_table",
            ],
        ),
        MockAgent("safe-3"),
    ]
    results = run_agents(Task(description="Delete inactive customers"), settings, providers)
    assert [result.status for result in results] == ["completed", "failed", "completed"]
    failed = results[1]
    assert failed.error
    assert [operation.status for operation in failed.sql_operations] == ["rolled_back", "failed"]
    assert len(failed.sql_operations[0].changes) == 1
    assert failed.sql_operations[1].error
    assert failed.changes == failed.deleted_rows == []
    assert failed.affected_row_count == 0
    _, paths = configured_demo_paths(settings)
    with closing(sqlite3.connect(paths[1])) as connection:
        assert len(read_customers(connection)) == 3


@pytest.mark.parametrize(
    "statement",
    [
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA application_id=0",
        "DROP TABLE customers",
        "COMMIT",
        "SELECT load_extension('anything')",
    ],
)
def test_provider_sql_cannot_escape_customer_dml(statement):
    results = run_agents(
        Task(description="test"), settings, [StubAgent(f"stub-{i}", [statement]) for i in range(3)]
    )
    assert all(result.status == "failed" and result.error for result in results)
    assert all(result.affected_row_count == 0 for result in results)


def test_unsupported_task_is_explicitly_skipped(client):
    task = client.post("/tasks", json={"description": "Show revenue"}).json()
    run = client.post("/sandbox/run", json={"task_id": task["id"]}).json()
    assert run["status"] == "skipped"
    assert all(
        agent["status"] == "skipped"
        and agent["sql_operations"] == []
        and agent["raw_output"].startswith("Unsupported")
        for agent in run["agents"]
    )


def test_api_provider_configuration_and_failed_status(client):
    class FailingProvider:
        agent_id = "broken-provider"

        def plan(self, task: Task) -> AgentPlan:
            """Simulate a model adapter failure before any SQL exists."""
            raise RuntimeError("mock unavailable")

    providers = [FailingProvider(), MockAgent("safe-2"), MockAgent("safe-3")]
    app.dependency_overrides[get_agents] = lambda: providers
    try:
        task = client.post("/tasks", json={"description": "Delete inactive customers"}).json()
        run = client.post("/sandbox/run", json={"task_id": task["id"]}).json()
        assert run["status"] == "failed"
        assert run["agents"][0]["error"] == "RuntimeError: mock unavailable"
        assert [agent["status"] for agent in run["agents"]] == ["failed", "completed", "completed"]
        assert run["risk"]["level"] == "critical"
        assert any("incomplete" in warning for warning in run["risk"]["warnings"])
    finally:
        app.dependency_overrides.clear()


def test_three_unique_providers_are_required():
    task = Task(description="Delete inactive customers")
    for providers in ([], [MockAgent("same")] * 3):
        with pytest.raises(ValueError, match="Exactly three"):
            run_agents(task, settings, providers)
