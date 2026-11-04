"""Domain models; review metadata is intentionally in memory for the demo."""

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


def new_id() -> str:
    """Return an opaque identifier."""
    return str(uuid4())


class TaskRequest(BaseModel):
    description: str = Field(
        min_length=1, max_length=10000, pattern=r"\S", examples=["Delete inactive customers"]
    )


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
    status: Literal["completed", "failed", "skipped"] = "completed"
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


class Customer(BaseModel):
    """Clearly fake demo customer, validated before SQLite seeding."""

    id: int
    name: str
    email: str
    phone: str
    status: Literal["active", "inactive"]
    created_at: datetime
    last_active_at: datetime


class SQLOperation(BaseModel):
    """One attempted statement, its observed changes and transaction outcome."""

    sql: str
    status: Literal["completed", "failed", "rolled_back"]
    changes: list[DatabaseChange] = Field(default_factory=list)
    error: str | None = None


class RunResult(AgentRun):
    """Normalized agent output; legacy changes describe the committed net diff."""

    sql_operations: list[SQLOperation] = Field(default_factory=list)
    raw_output: str = ""
    error: str | None = None

    @computed_field
    @property
    def agent_id(self) -> str:
        """Expose the stable provider identity, distinct from this result's id."""
        return self.agent

    @computed_field
    @property
    def inserted_rows(self) -> list[dict[str, Any]]:
        """Return postimages of committed insert events, including transient rows."""
        return [
            change.after
            for operation in self.sql_operations
            if operation.status == "completed"
            for change in operation.changes
            if change.operation == "insert" and change.after is not None
        ]

    @computed_field
    @property
    def updated_rows(self) -> list[DatabaseChange]:
        """Return before/after images of committed update events."""
        return [
            change
            for operation in self.sql_operations
            if operation.status == "completed"
            for change in operation.changes
            if change.operation == "update"
        ]

    @computed_field
    @property
    def deleted_rows(self) -> list[dict[str, Any]]:
        """Return preimages of committed delete events."""
        return [
            change.before
            for operation in self.sql_operations
            if operation.status == "completed"
            for change in operation.changes
            if change.operation == "delete" and change.before is not None
        ]

    @computed_field
    @property
    def affected_row_count(self) -> int:
        """Count distinct row identities touched by committed statement events."""
        return len(
            {
                (change.table, change.row_id)
                for operation in self.sql_operations
                if operation.status == "completed"
                for change in operation.changes
            }
        )
