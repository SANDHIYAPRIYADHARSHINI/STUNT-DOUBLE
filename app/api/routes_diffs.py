"""Consensus diff endpoint."""

from fastapi import APIRouter

from app.api.routes_sandbox import get_run
from app.schemas import DiffComparison

router = APIRouter(prefix="/diffs", tags=["diffs"])


@router.get("/{run_id}", response_model=DiffComparison)
def get_diffs(run_id: str) -> DiffComparison:
    """Return unanimous, partial and conflicting observations."""
    return get_run(run_id).diffs
