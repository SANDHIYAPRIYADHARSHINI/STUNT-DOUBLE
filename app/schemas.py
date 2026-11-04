"""API contracts for rehearsal and non-writing approval endpoints."""

from pydantic import BaseModel, Field

from app.models import DatabaseChange, RiskReport, RunResult


class SandboxRequest(BaseModel):
    task_id: str


class RunReference(BaseModel):
    run_id: str


class DiffComparison(BaseModel):
    unanimous_changes: list[DatabaseChange] = Field(default_factory=list)
    partial_agreement_changes: list[DatabaseChange] = Field(default_factory=list)
    conflicting_changes: list[DatabaseChange] = Field(default_factory=list)
    affected_row_count: int = 0


class SandboxRun(BaseModel):
    id: str
    task_id: str
    status: str = "completed"
    agents: list[RunResult]
    diffs: DiffComparison
    risk: RiskReport


class ApplyResult(BaseModel):
    run_id: str
    status: str
    production_writes_enabled: bool = False
