"""Explicit review with non-writing apply/rollback stubs."""

from datetime import UTC, datetime

from app.models import ApprovalDecision
from app.schemas import ApplyResult
from app.services import store


def record_decision(decision: ApprovalDecision) -> ApprovalDecision:
    """Store an explicit decision and a demo audit event for an existing run."""
    with store.lock:
        if decision.run_id not in store.runs:
            raise KeyError(decision.run_id)
        store.decisions[decision.run_id] = decision.model_copy(deep=True)
        store.audit_log.append(
            {
                "run_id": decision.run_id,
                "action": decision.decision,
                "reviewer": decision.reviewer,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    return decision


def apply_approved(run_id: str) -> ApplyResult:
    """Require explicit approval, then report that production writes are disabled."""
    with store.lock:
        if run_id not in store.runs:
            raise KeyError(run_id)
        decision = store.decisions.get(run_id)
        if decision is None or decision.decision != "approve":
            raise PermissionError("Explicit human approval is required")
        store.audit_log.append(
            {
                "run_id": run_id,
                "action": "apply_blocked",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    # TODO: Reviewed transactional production adapter, durable preimages and authenticated review.
    return ApplyResult(run_id=run_id, status="disabled_no_production_writes")


def rollback(run_id: str) -> ApplyResult:
    """Report no applied change; this scaffold never writes to production."""
    with store.lock:
        if run_id not in store.runs:
            raise KeyError(run_id)
        store.audit_log.append(
            {
                "run_id": run_id,
                "action": "rollback_noop",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    return ApplyResult(run_id=run_id, status="nothing_applied")
