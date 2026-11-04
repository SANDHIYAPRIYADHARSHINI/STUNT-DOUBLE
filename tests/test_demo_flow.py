"""Frontend-facing demo flow and immutable rehearsal summaries."""

from dataclasses import dataclass

import pytest

from app.main import app
from app.models import Task
from app.services.agent_runner import AgentPlan, MockAgent, get_agents


@dataclass
class NoopAgent:
    """Complete a read-only mock statement with no net mutations."""

    agent_id: str

    def plan(self, task: Task) -> AgentPlan:
        """Provide a deterministic read-only plan."""
        return AgentPlan(sql_operations=["SELECT id FROM customers"], raw_output="mock read")


def start_demo(client, description="Delete inactive customers"):
    """Drive the public create-and-rehearse flow."""
    task_response = client.post("/tasks", json={"description": description})
    assert task_response.status_code == 201
    task = task_response.json()
    response = client.post("/sandbox/run", json={"task_id": task["id"]})
    assert response.status_code == 201
    return task, response.json()


def test_full_demo_flow_and_summary(client):
    task, created = start_demo(client)
    response = client.get(f"/sandbox/runs/{created['id']}")
    assert response.status_code == 200
    run = response.json()
    assert run == created
    assert run["task"]["id"] == run["task_id"] == task["id"]
    assert run["task"]["description"] == "Delete inactive customers"
    assert run["task"]["status"] == "rehearsed"
    assert run["task"]["agent_run_ids"] == [agent["id"] for agent in run["agents"]]
    assert len(run["agents"]) == 3
    summary_response = client.get(f"/sandbox/runs/{run['id']}/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["run_id"] == run["id"]
    assert summary["task"] == run["task"]
    assert summary["status"] == "completed"
    assert summary["production_writes_enabled"] is run["production_writes_enabled"] is False
    comparison = summary["comparison"]
    assert comparison["classification"] == "conflicting"
    assert comparison["agreement_groups"] == [
        {"agent_ids": ["mock-agent-1", "mock-agent-2"]},
        {"agent_ids": ["mock-agent-3"]},
    ]
    assert comparison["unanimous_change_count"] == 1
    assert comparison["partial_agreement_change_count"] == 0
    assert comparison["conflicting_change_count"] == 2
    assert comparison["blast_radius_estimate"] == comparison["maximum_affected_row_count"] == 3
    assert (
        comparison["affected_row_count_per_agent"] == run["diffs"]["affected_row_count_per_agent"]
    )
    assert "mock-agent-1 and mock-agent-2" in summary["message"]
    assert [agent["affected_row_count"] for agent in summary["agents"]] == [1, 1, 3]
    assert [agent["deleted_row_count"] for agent in summary["agents"]] == [1, 1, 3]
    assert all(
        agent["inserted_row_count"] == agent["updated_row_count"] == 0
        for agent in summary["agents"]
    )
    assert all(
        "raw_output" not in agent and "deleted_rows" not in agent for agent in summary["agents"]
    )
    assert summary["agents"][2]["sql_operations"] == ["DELETE FROM customers"]
    assert client.get(f"/sandbox/runs/{run['id']}/summary").json() == summary


def test_earlier_task_snapshot_does_not_change_on_another_rehearsal(client):
    task, first = start_demo(client)
    original_summary = client.get(f"/sandbox/runs/{first['id']}/summary").json()
    second = client.post("/sandbox/run", json={"task_id": task["id"]}).json()
    assert second["id"] != first["id"]
    assert client.get(f"/sandbox/runs/{first['id']}").json() == first
    assert client.get(f"/sandbox/runs/{first['id']}/summary").json() == original_summary
    assert len(client.get(f"/tasks/{task['id']}").json()["agent_run_ids"]) == 6
    assert len(second["task"]["agent_run_ids"]) == 3


def test_skipped_demo_summary_is_incomplete(client):
    _, run = start_demo(client, "Show revenue")
    summary = client.get(f"/sandbox/runs/{run['id']}/summary").json()
    assert summary["status"] == "skipped"
    assert summary["comparison"]["classification"] == "incomplete"
    assert len(summary["comparison"]["unavailable_agent_ids"]) == 3
    assert summary["comparison"]["agreement_groups"] == []
    assert summary["comparison"]["blast_radius_estimate"] == 0


@pytest.mark.parametrize("mode", ["unanimous", "no_changes", "partial_agreement", "failed"])
def test_summary_reports_actual_provider_outcomes(client, mode):
    providers = [MockAgent(f"safe-{i}") for i in range(3)]
    if mode == "no_changes":
        providers = [NoopAgent(f"noop-{i}") for i in range(3)]
    elif mode == "partial_agreement":
        providers[2] = NoopAgent("noop-3")
    elif mode == "failed":

        class FailedAgent:
            agent_id = "failed-3"

            def plan(self, task: Task) -> AgentPlan:
                """Simulate an unavailable provider."""
                raise RuntimeError("mock failure")

        providers[2] = FailedAgent()
    app.dependency_overrides[get_agents] = lambda: providers
    try:
        _, run = start_demo(client)
        summary = client.get(f"/sandbox/runs/{run['id']}/summary").json()
        comparison = summary["comparison"]
        assert comparison["classification"] == ("incomplete" if mode == "failed" else mode)
        if mode == "failed":
            assert summary["status"] == "failed"
            assert comparison["unavailable_agent_ids"] == ["failed-3"]
            assert summary["agents"][2]["error"] == "RuntimeError: mock failure"
            assert comparison["agreement_groups"] == [{"agent_ids": ["safe-0", "safe-1"]}]
        elif mode == "partial_agreement":
            assert comparison["partial_agreement_change_count"] == 1
        else:
            assert len(comparison["agreement_groups"][0]["agent_ids"]) == 3
        assert summary["production_writes_enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_unknown_summary_is_404(client):
    response = client.get("/sandbox/runs/missing/summary")
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


def test_interactive_docs_expose_demo_contract(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    for path in (
        "/tasks",
        "/sandbox/run",
        "/sandbox/runs/{run_id}",
        "/sandbox/runs/{run_id}/summary",
    ):
        assert path in schema["paths"]
    properties = schema["components"]["schemas"]["SandboxRun"]["properties"]
    assert {"task", "agents", "diffs", "production_writes_enabled"} <= properties.keys()
    assert schema["components"]["schemas"]["TaskRequest"]["properties"]["description"][
        "examples"
    ] == ["Delete inactive customers"]
