"""Risk report endpoint."""

from fastapi import APIRouter

from app.api.routes_sandbox import get_run
from app.models import RiskReport

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/{run_id}", response_model=RiskReport)
def get_risk(run_id: str) -> RiskReport:
    """Return risk level, warnings, blast radius and injection flags."""
    return get_run(run_id).risk
