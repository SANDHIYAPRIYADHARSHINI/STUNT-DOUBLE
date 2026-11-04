"""Compare observations by row identity and complete before/after values."""

import json
from collections import defaultdict

from app.models import DatabaseChange
from app.schemas import DiffComparison


def compare_changes(agent_changes: list[list[DatabaseChange]]) -> DiffComparison:
    """Classify three independent observations, counting each agent once per change."""
    if len(agent_changes) != 3:
        raise ValueError("Exactly three agent observations are required")
    rows: dict[tuple[str, int], dict[str, tuple[DatabaseChange, set[int]]]] = defaultdict(dict)
    for index, changes in enumerate(agent_changes):
        for change in changes:
            variants = rows[(change.table, change.row_id)]
            signature = json.dumps(change.model_dump(), sort_keys=True)
            if signature not in variants:
                variants[signature] = (change, set())
            variants[signature][1].add(index)
    result = DiffComparison(affected_row_count=len(rows))
    for variants in rows.values():
        for change, supporters in variants.values():
            if len(variants) > 1:
                result.conflicting_changes.append(change)
            elif len(supporters) == 3:
                result.unanimous_changes.append(change)
            else:
                result.partial_agreement_changes.append(change)
    return result
