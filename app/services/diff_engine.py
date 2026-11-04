"""Explain row-level agreement, competing values and differences in change scope."""

import json
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from app.models import DatabaseChange, RunResult
from app.schemas import ChangeVariant, ComparedChange, DiffComparison


def _material_values(change: DatabaseChange) -> dict[str, Any]:
    before, after = change.before, change.after
    if change.operation == "insert":
        if before is not None or after is None:
            raise ValueError("Insert observations require only an after image")
        return after
    if change.operation == "delete":
        if before is None or after is not None:
            raise ValueError("Delete observations require only a before image")
        return before
    if before is None or after is None:
        raise ValueError("Update observations require before and after images")
    # Presence flags distinguish a missing field from a field explicitly set to NULL.
    return {
        field: {
            "before_present": field in before,
            "before": before.get(field),
            "after_present": field in after,
            "after": after.get(field),
        }
        for field in sorted(before.keys() | after.keys())
        if field not in before or field not in after or before[field] != after[field]
    }


def compare_changes(runs: Sequence[RunResult]) -> DiffComparison:
    """Classify three agents' committed net changes and estimate all touched-row scope.

    Different variants on one row take precedence over majority agreement. A lone
    change conflicts with unchanged observations; two identical changes with no
    competing variant are partial agreement. Failed/skipped agents are unavailable,
    never evidence that a row was intentionally left unchanged.
    """
    if len(runs) != 3 or len({run.agent_id for run in runs}) != 3:
        raise ValueError("Exactly three results with distinct agent IDs are required")
    if len({run.task_id for run in runs}) != 1:
        raise ValueError("All agent results must belong to the same task")
    # Row -> material signature -> (representative observation, supporting agents).
    rows: dict[tuple[str, int], dict[str, tuple[DatabaseChange, set[str]]]] = defaultdict(dict)
    touched_union: set[tuple[str, int]] = set()
    completed = {run.agent_id for run in runs if run.status == "completed"}
    unavailable = sorted(run.agent_id for run in runs if run.status != "completed")
    result = DiffComparison(agent_statuses={run.agent_id: run.status for run in runs})
    if unavailable:
        result.warnings.append("Incomplete observations from: " + ", ".join(unavailable))
    for run in runs:
        touched: set[tuple[str, int]] = set()
        if run.status == "completed":
            for change in run.changes:
                values = _material_values(change)
                if change.operation == "update" and not values:
                    continue
                identity = (change.table, change.row_id)
                touched.add(identity)
                signature = json.dumps(
                    {"operation": change.operation, "values": values},
                    sort_keys=True,
                    allow_nan=False,
                )
                variants = rows[identity]
                if signature not in variants:
                    variants[signature] = (change, set())
                variants[signature][1].add(run.agent_id)
            # Include transient committed changes in blast radius, not final-state consensus.
            for operation in run.sql_operations:
                if operation.status == "completed":
                    touched.update((change.table, change.row_id) for change in operation.changes)
        result.affected_row_count_per_agent[run.agent_id] = len(touched)
        touched_union.update(touched)
    result.affected_row_count = len(rows)
    result.maximum_affected_row_count = max(result.affected_row_count_per_agent.values())
    result.blast_radius_estimate = len(touched_union)
    for identity in sorted(rows):
        variants = rows[identity]
        observers = set().union(*(agents for _, agents in variants.values()))
        unchanged = sorted(completed - observers)
        for signature in sorted(variants):
            change, supporters = variants[signature]
            if len(variants) > 1:
                classification = "conflicting"
                reason = (
                    "Agents observed different operations or changed field values for this row."
                )
            elif len(supporters) == 3:
                classification = "unanimous"
                reason = "All three agents made the same material row change."
            elif len(supporters) == 2:
                classification = "partial_agreement"
                reason = (
                    "Two agents made the same material row change; the third did not confirm it."
                )
            else:
                classification = "conflicting"
                reason = "Only one agent made this change; its affected-row scope is unconfirmed."
            if unchanged:
                reason += " No net change from: " + ", ".join(unchanged) + "."
            if unavailable:
                reason += " Unavailable observations: " + ", ".join(unavailable) + "."
            entry = ComparedChange(
                **change.model_dump(),
                classification=classification,
                agent_ids=sorted(supporters),
                unchanged_agent_ids=unchanged,
                unavailable_agent_ids=unavailable,
                changed_fields=sorted(_material_values(change)),
                reason=reason,
                competing_changes=[
                    ChangeVariant(change=other, agent_ids=sorted(agents))
                    for key, (other, agents) in sorted(variants.items())
                    if key != signature
                ],
            )
            getattr(result, classification + "_changes").append(entry)
    return result
