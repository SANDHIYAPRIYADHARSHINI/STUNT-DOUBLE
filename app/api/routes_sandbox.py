"""Synchronous local rehearsal endpoints."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.models import new_id
from app.schemas import SandboxRequest, SandboxRun, SandboxRunSummary
from app.services import store
from app.services.agent_runner import RehearsalAgent, get_agents, run_agents
from app.services.diff_engine import compare_changes
from app.services.risk_analyzer import analyze_risk
from app.services.run_summary import summarize_run

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.post("/run", response_model=SandboxRun, status_code=201)
def start_run(
    request: SandboxRequest, providers: Annotated[Sequence[RehearsalAgent], Depends(get_agents)]
) -> SandboxRun:
    """Rehearse a task on three independent synthetic databases."""
    with store.lock:
        if request.task_id not in store.tasks:
            raise HTTPException(404, "Task not found")
        task = store.tasks[request.task_id].model_copy(deep=True)
    try:
        agents = run_agents(task, settings, providers)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    diffs = compare_changes(agents)
    risk = analyze_risk(
        [agent.sql for agent in agents],
        diffs.blast_radius_estimate,
        bool(diffs.conflicting_changes or diffs.partial_agreement_changes),
        task.description,
        settings.max_affected_rows,
    )
    status = (
        "failed"
        if any(agent.status == "failed" for agent in agents)
        else ("skipped" if all(agent.status == "skipped" for agent in agents) else "completed")
    )
    if status == "failed":
        risk.warnings.append("Agent execution failed; observations are incomplete")
        risk.score = max(risk.score, 80)
        risk.level = "critical"
    task_snapshot = task.model_copy(
        deep=True,
        update={
            "status": "rehearsed",
            "agent_run_ids": [agent.id for agent in agents],
        },
    )
    run = SandboxRun(
        id=new_id(),
        task_id=task.id,
        task=task_snapshot,
        status=status,
        agents=agents,
        diffs=diffs,
        risk=risk,
    )
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


@router.get(
    "/runs/{run_id}/summary",
    response_model=SandboxRunSummary,
    summary="View a compact rehearsal comparison",
)
def get_run_summary(run_id: str) -> SandboxRunSummary:
    """Return task details, agent counts, agreement groups and blast radius without row images."""
    return summarize_run(get_run(run_id))
