"""Build compact, read-only demo summaries from stored rehearsal observations."""

from collections import defaultdict

from app.schemas import (
    AgentSummary,
    AgreementGroup,
    ComparisonSummary,
    SandboxRun,
    SandboxRunSummary,
)


def summarize_run(run: SandboxRun) -> SandboxRunSummary:
    """Summarize observed agreement and scope without selecting a correct plan."""
    diffs = run.diffs
    entries = [
        *diffs.unanimous_changes,
        *diffs.partial_agreement_changes,
        *diffs.conflicting_changes,
    ]
    # Each classified entry is already one distinct material variant. Matching
    # membership sets mean matching net changes, including an empty change set.
    groups: dict[tuple[int, ...], list[str]] = defaultdict(list)
    unavailable = []
    for agent in run.agents:
        if agent.status != "completed":
            unavailable.append(agent.agent_id)
            continue
        signature = tuple(
            index for index, entry in enumerate(entries) if agent.agent_id in entry.agent_ids
        )
        groups[signature].append(agent.agent_id)
    agreement_groups = [AgreementGroup(agent_ids=sorted(ids)) for ids in groups.values()]
    agreement_groups.sort(key=lambda group: group.agent_ids)
    classification = "no_changes"
    if unavailable:
        classification = "incomplete"
    elif diffs.conflicting_changes:
        classification = "conflicting"
    elif diffs.partial_agreement_changes:
        classification = "partial_agreement"
    elif diffs.unanimous_changes:
        classification = "unanimous"
    message = {
        "conflicting": "Agents produced conflicting changes. Compare their row-level differences.",
        "partial_agreement": "Two agents agree on changes that the third did not confirm.",
        "unanimous": "All three agents made the same material changes.",
        "incomplete": "Some agents failed or skipped execution; the comparison is incomplete.",
        "no_changes": "The agents produced no net database changes.",
    }[classification]
    matching = [group for group in agreement_groups if len(group.agent_ids) == 2]
    if matching:
        message += " " + " and ".join(matching[0].agent_ids) + " made identical net changes."
    message += " Production writes are disabled."
    return SandboxRunSummary(
        run_id=run.id,
        task=run.task.model_copy(deep=True),
        status=run.status,
        agents=[
            AgentSummary(
                run_result_id=agent.id,
                agent_id=agent.agent_id,
                status=agent.status,
                affected_row_count=diffs.affected_row_count_per_agent[agent.agent_id],
                inserted_row_count=len(agent.inserted_rows),
                updated_row_count=len(agent.updated_rows),
                deleted_row_count=len(agent.deleted_rows),
                sql_operations=[operation.sql for operation in agent.sql_operations],
                error=agent.error,
            )
            for agent in run.agents
        ],
        comparison=ComparisonSummary(
            classification=classification,
            unanimous_change_count=len(diffs.unanimous_changes),
            partial_agreement_change_count=len(diffs.partial_agreement_changes),
            conflicting_change_count=len(diffs.conflicting_changes),
            agreement_groups=agreement_groups,
            unavailable_agent_ids=sorted(unavailable),
            affected_row_count_per_agent=diffs.affected_row_count_per_agent.copy(),
            maximum_affected_row_count=diffs.maximum_affected_row_count,
            blast_radius_estimate=diffs.blast_radius_estimate,
            warnings=diffs.warnings.copy(),
        ),
        message=message,
    )
