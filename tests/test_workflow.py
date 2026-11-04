"""End-to-end mock rehearsal and production-write boundary tests."""

import pytest

from app.config import settings
from app.models import Task
from app.services import store
from app.services.agent_runner import capture_changes, run_agents


def rehearse(client):
    """Create and rehearse a synthetic deletion task."""
    task = client.post("/tasks", json={"description": "Delete inactive customers"})
    assert task.status_code == 201
    response = client.post("/sandbox/run", json={"task_id": task.json()["id"]})
    assert response.status_code == 201
    return task.json()["id"], response.json()


def test_full_workflow_without_production_writes(client, tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    source.write_bytes(b"source must never be opened or modified")
    monkeypatch.setattr(settings, "require_human_approval", False)
    task_id, run = rehearse(client)
    reference = {"run_id": run["id"]}
    assert len(run["agents"]) == 3
    assert len({agent["id"] for agent in run["agents"]}) == 3
    assert len(run["diffs"]["unanimous_changes"]) == 1
    assert run["diffs"]["unanimous_changes"][0]["before"]["email"].startswith("synthetic_")
    assert client.get(f"/tasks/{task_id}").json()["status"] == "rehearsed"
    assert len(client.get(f"/tasks/{task_id}").json()["agent_run_ids"]) == 3
    for route in ("sandbox/runs", "diffs", "risk"):
        assert client.get(f"/{route}/{run['id']}").status_code == 200
    assert client.post("/approval/apply", json=reference).status_code == 403
    for decision in ("reject", "approve"):
        response = client.post(
            "/approval", json={**reference, "decision": decision, "reviewer": "demo"}
        )
        assert response.status_code == 200
        applied = client.post("/approval/apply", json=reference)
        if decision == "reject":
            assert applied.status_code == 403
        else:
            assert applied.status_code == 200
            assert applied.json()["status"] == "disabled_no_production_writes"
            assert applied.json()["production_writes_enabled"] is False
    assert client.post("/approval/rollback", json=reference).json()["status"] == "nothing_applied"
    assert source.read_bytes() == b"source must never be opened or modified"
    assert not list(tmp_path.rglob("sandbox.db"))
    assert store.audit_log


@pytest.mark.parametrize("route", ["tasks", "sandbox/runs", "diffs", "risk"])
def test_unknown_get_is_404(client, route):
    assert client.get(f"/{route}/missing").status_code == 404


@pytest.mark.parametrize("route", ["approval/apply", "approval/rollback"])
def test_unknown_review_run_is_404(client, route):
    assert client.post(f"/{route}", json={"run_id": "missing"}).status_code == 404


def test_invalid_requests(client):
    assert client.post("/tasks", json={"description": "   "}).status_code == 422
    assert client.post("/sandbox/run", json={"task_id": "missing"}).status_code == 404
    assert (
        client.post(
            "/approval", json={"run_id": "missing", "decision": "approve", "reviewer": "demo"}
        ).status_code
        == 404
    )


def test_overlapping_paths_are_rejected(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_database_url_1", settings.database_url)
    with pytest.raises(ValueError):
        run_agents(Task(description="Delete inactive customers"), settings)


def test_unsupported_task_is_noop(client):
    task = client.post("/tasks", json={"description": "arbitrary SQL; DROP TABLE customers"}).json()
    response = client.post("/sandbox/run", json={"task_id": task["id"]}).json()
    assert response["diffs"]["affected_row_count"] == 0
    assert all(agent["sql"] == "" for agent in response["agents"])


def test_capture_insert_update_delete():
    before = {1: {"id": 1}, 2: {"id": 2, "active": 1}}
    after = {2: {"id": 2, "active": 0}, 3: {"id": 3}}
    assert [change.operation for change in capture_changes(before, after)] == [
        "delete",
        "update",
        "insert",
    ]
