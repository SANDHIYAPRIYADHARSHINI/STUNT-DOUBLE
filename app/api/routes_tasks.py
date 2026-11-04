"""Task creation and status endpoints."""

from fastapi import APIRouter, HTTPException

from app.models import Task, TaskRequest
from app.services import store

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=Task, status_code=201)
def create_task(request: TaskRequest) -> Task:
    """Register a task without executing any database operation."""
    task = Task(description=request.description)
    with store.lock:
        store.tasks[task.id] = task
    return task


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str) -> Task:
    """Return task status and linked agent run identifiers."""
    with store.lock:
        if task_id not in store.tasks:
            raise HTTPException(404, "Task not found")
        return store.tasks[task_id].model_copy(deep=True)
