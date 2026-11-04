"""API contracts for rehearsal and non-writing approval endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models import DatabaseChange, RiskReport, RunResult


class SandboxRequest(BaseModel):
    task_id: str


class RunReference(BaseModel):
    run_id: str


class ChangeVariant(BaseModel):
    """A competing row observation and its supporting agents."""

    change: DatabaseChange
    agent_ids: list[str]


class ComparedChange(DatabaseChange):
    """Classified row change with evidence, without choosing a correct outcome."""

    classification: Literal["unanimous", "partial_agreement", "conflicting"]
    agent_ids: list[str]
    unchanged_agent_ids: list[str] = Field(default_factory=list)
    unavailable_agent_ids: list[str] = Field(default_factory=list)
    changed_fields: list[str]
    reason: str
    competing_changes: list[ChangeVariant] = Field(default_factory=list)


class DiffComparison(BaseModel):
    unanimous_changes: list[ComparedChange] = Field(default_factory=list)
    partial_agreement_changes: list[ComparedChange] = Field(default_factory=list)
    conflicting_changes: list[ComparedChange] = Field(default_factory=list)
    affected_row_count_per_agent: dict[str, int] = Field(default_factory=dict)
    maximum_affected_row_count: int = 0
    blast_radius_estimate: int = 0
    affected_row_count: int = 0
    agent_statuses: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


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
