"""Process-local review state; restart clears all runs and decisions."""

from threading import RLock

from app.models import ApprovalDecision, Task
from app.schemas import SandboxRun

lock = RLock()
tasks: dict[str, Task] = {}
runs: dict[str, SandboxRun] = {}
decisions: dict[str, ApprovalDecision] = {}
audit_log: list[dict[str, str]] = []
