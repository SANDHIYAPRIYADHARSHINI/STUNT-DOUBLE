"""Synchronous local rehearsal endpoints."""

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models import new_id
from app.schemas import SandboxRequest, SandboxRun
from app.services import store
from app.services.agent_runner import run_agents
from app.services.diff_engine import compare_changes
from app.services.risk_analyzer import analyze_risk

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.post("/run", response_model=SandboxRun, status_code=201)
def start_run(request: SandboxRequest) -> SandboxRun:
    """Rehearse a task on three independent synthetic databases."""
    with store.lock:
        if request.task_id not in store.tasks:
            raise HTTPException(404, "Task not found")
        task = store.tasks[request.task_id].model_copy(deep=True)
    try:
        agents = run_agents(task, settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    diffs = compare_changes([agent.changes for agent in agents])
    risk = analyze_risk(
        [agent.sql for agent in agents],
        diffs.affected_row_count,
        bool(diffs.conflicting_changes or diffs.partial_agreement_changes),
        task.description,
        settings.max_affected_rows,
    )
    run = SandboxRun(id=new_id(), task_id=task.id, agents=agents, diffs=diffs, risk=risk)
    with store.lock:
        store.runs[run.id] = run
        store.tasks[task.id].status = "rehearsed"
        store.tasks[task.id].agent_run_ids.extend(agent.id for agent in agents)
    return run


@router.get("/runs/{run_id}", response_model=SandboxRun)
def get_run(run_id: str) -> SandboxRun:
    """Return captured row diffs and risk signals."""
    with store.lock:
        if run_id not in store.runs:
            raise HTTPException(404, "Run not found")
        return store.runs[run_id].model_copy(deep=True)
