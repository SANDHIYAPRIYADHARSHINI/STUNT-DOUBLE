"""Human review endpoints; no production writes are implemented."""

from fastapi import APIRouter, HTTPException

from app.models import ApprovalDecision
from app.schemas import ApplyResult, RunReference
from app.services.approval_service import apply_approved, record_decision, rollback

router = APIRouter(prefix="/approval", tags=["approval"])


@router.post("", response_model=ApprovalDecision)
def decide(decision: ApprovalDecision) -> ApprovalDecision:
    """Record an approve or reject decision."""
    try:
        return record_decision(decision)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc


@router.post("/apply", response_model=ApplyResult)
def apply(request: RunReference) -> ApplyResult:
    """Check approval and return the disabled production adapter status."""
    try:
        return apply_approved(request.run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/rollback", response_model=ApplyResult)
def undo(request: RunReference) -> ApplyResult:
    """Return the non-writing rollback stub result."""
    try:
        return rollback(request.run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc
