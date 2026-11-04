"""API contracts for rehearsal and non-writing approval endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models import DatabaseChange, RiskReport, RunResult, Task


class SandboxRequest(BaseModel):
    task_id: str = Field(description="Copy the id returned by POST /tasks")


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
    task: Task
    status: Literal["completed", "failed", "skipped"] = "completed"
    production_writes_enabled: Literal[False] = False
    agents: list[RunResult]
    diffs: DiffComparison
    risk: RiskReport


class ApplyResult(BaseModel):
    run_id: str
    status: str
    production_writes_enabled: bool = False


class AgentSummary(BaseModel):
    """Compact result suitable for an agent card in a demo UI."""

    run_result_id: str
    agent_id: str
    status: Literal["completed", "failed", "skipped"]
    affected_row_count: int
    inserted_row_count: int
    updated_row_count: int
    deleted_row_count: int
    sql_operations: list[str]
    error: str | None = None


class AgreementGroup(BaseModel):
    """Completed agents with identical final material change sets, without judging correctness."""

    agent_ids: list[str]


class ComparisonSummary(BaseModel):
    """Counts refer to classified change variants; blast radius counts distinct rows."""

    classification: Literal[
        "unanimous", "partial_agreement", "conflicting", "incomplete", "no_changes"
    ]
    unanimous_change_count: int
    partial_agreement_change_count: int
    conflicting_change_count: int
    agreement_groups: list[AgreementGroup]
    unavailable_agent_ids: list[str]
    affected_row_count_per_agent: dict[str, int]
    maximum_affected_row_count: int
    blast_radius_estimate: int
    warnings: list[str]


class SandboxRunSummary(BaseModel):
    """Demo-friendly view of a stored rehearsal; contains no execution actions."""

    run_id: str
    task: Task
    status: Literal["completed", "failed", "skipped"]
    agents: list[AgentSummary]
    comparison: ComparisonSummary
    message: str
    production_writes_enabled: Literal[False] = False
