"""Domain models; review metadata is intentionally in memory for the demo."""

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    """Return an opaque identifier."""
    return str(uuid4())


class TaskRequest(BaseModel):
    description: str = Field(min_length=1, max_length=10000, pattern=r"\S")


class Task(BaseModel):
    id: str = Field(default_factory=new_id)
    description: str
    status: Literal["pending", "rehearsed"] = "pending"
    agent_run_ids: list[str] = Field(default_factory=list)


class RowDiff(BaseModel):
    table: str
    row_id: int
    operation: Literal["insert", "update", "delete"]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class DatabaseChange(RowDiff):
    """An observed row change, never an executable SQL command."""


class AgentRun(BaseModel):
    id: str = Field(default_factory=new_id)
    task_id: str
    agent: str
    status: Literal["completed", "failed"] = "completed"
    sql: str = ""
    changes: list[DatabaseChange] = Field(default_factory=list)


class RiskReport(BaseModel):
    score: int
    level: Literal["low", "medium", "high", "critical"]
    warnings: list[str]
    blast_radius: int
    prompt_injection_flags: list[str]


class ApprovalDecision(BaseModel):
    run_id: str
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=200, pattern=r"\S")
    reason: str = Field(default="", max_length=2000)
