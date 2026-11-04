"""Material row consensus, scope differences, provenance and blast-radius accounting."""

import pytest

from app.models import DatabaseChange, RunResult, SQLOperation
from app.services.diff_engine import compare_changes


def change(value=0, row_id=1, table="customers"):
    """Build a synthetic update observation."""
    return DatabaseChange(
        table=table,
        row_id=row_id,
        operation="update",
        before={"active": 1},
        after={"active": value},
    )


def compare(observations):
    """Wrap three final observations in normalized agent results."""
    return compare_changes(
        [
            RunResult(task_id="task", agent=f"agent-{index}", changes=changes)
            for index, changes in enumerate(observations, start=1)
        ]
    )


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_unanimous_for_all_operations(operation):
    observation = DatabaseChange(
        table="customers",
        row_id=1,
        operation=operation,
        before=None if operation == "insert" else {"status": "active"},
        after=None if operation == "delete" else {"status": "inactive"},
    )
    result = compare([[observation], [observation], [observation]])
    assert len(result.unanimous_changes) == 1
    entry = result.unanimous_changes[0]
    assert entry.classification == "unanimous"
    assert entry.agent_ids == ["agent-1", "agent-2", "agent-3"]
    assert entry.changed_fields == ["status"]
    assert result.affected_row_count == result.blast_radius_estimate == 1
    assert not result.conflicting_changes
    assert not result.partial_agreement_changes


def test_partial_requires_two_agents():
    result = compare([[change()], [change()], []])
    entry = result.partial_agreement_changes[0]
    assert entry.agent_ids == ["agent-1", "agent-2"]
    assert entry.unchanged_agent_ids == ["agent-3"]
    assert not result.unanimous_changes
    assert not result.conflicting_changes


def test_conflicting_values_take_precedence_over_majority():
    result = compare([[change()], [change()], [change(2)]])
    assert len(result.conflicting_changes) == 2
    assert not result.unanimous_changes
    assert not result.partial_agreement_changes
    assert result.affected_row_count == 1
    assert {tuple(entry.agent_ids) for entry in result.conflicting_changes} == {
        ("agent-1", "agent-2"),
        ("agent-3",),
    }
    assert all(entry.competing_changes and entry.reason for entry in result.conflicting_changes)


def test_delete_versus_update():
    deleted = DatabaseChange(table="customers", row_id=1, operation="delete", before={"active": 1})
    result = compare([[deleted], [change()], [change()]])
    assert {entry.operation for entry in result.conflicting_changes} == {"update", "delete"}
    assert all(
        entry.competing_changes[0].change.operation != entry.operation
        for entry in result.conflicting_changes
    )
    assert result.blast_radius_estimate == 1


def test_extra_deletions_are_scope_conflicts():
    def deleted(key: int) -> DatabaseChange:
        """Create a row deletion from the fake baseline."""
        return DatabaseChange(
            table="customers",
            row_id=key,
            operation="delete",
            before={"id": key, "status": "inactive" if key == 1 else "active"},
        )

    result = compare([[deleted(1)], [deleted(1)], [deleted(1), deleted(2), deleted(3)]])
    assert [entry.row_id for entry in result.unanimous_changes] == [1]
    assert [entry.row_id for entry in result.conflicting_changes] == [2, 3]
    assert result.partial_agreement_changes == []
    assert all(
        entry.agent_ids == ["agent-3"] and entry.unchanged_agent_ids == ["agent-1", "agent-2"]
        for entry in result.conflicting_changes
    )
    assert result.affected_row_count_per_agent == {"agent-1": 1, "agent-2": 1, "agent-3": 3}
    assert result.maximum_affected_row_count == result.blast_radius_estimate == 3


def test_duplicates_do_not_add_votes_or_counts():
    result = compare([[change(), change(), change()], [], []])
    assert not result.unanimous_changes
    assert not result.partial_agreement_changes
    assert len(result.conflicting_changes) == 1
    assert result.affected_row_count_per_agent["agent-1"] == 1


def test_table_and_primary_key_are_both_part_of_identity():
    result = compare([[change()], [change(table="orders")], [change(row_id=2)]])
    assert len(result.conflicting_changes) == 3
    assert result.maximum_affected_row_count == 1
    assert result.blast_radius_estimate == 3


def test_update_compares_changed_fields_not_unchanged_columns():
    first = DatabaseChange(
        table="customers",
        row_id=1,
        operation="update",
        before={"status": "active", "name": "Demo A"},
        after={"status": "inactive", "name": "Demo A"},
    )
    second = first.model_copy(
        update={
            "before": {"status": "active", "name": "Demo B"},
            "after": {"status": "inactive", "name": "Demo B"},
        }
    )
    entry = compare([[first], [second], [first]]).unanimous_changes[0]
    assert entry.changed_fields == ["status"]


def test_different_changed_field_sets_conflict():
    first = change()
    second = first.model_copy(update={"after": {"active": 0, "name": "Demo Changed"}})
    assert len(compare([[first], [second], []]).conflicting_changes) == 2


def test_missing_field_differs_from_null():
    first = DatabaseChange(
        table="customers",
        row_id=1,
        operation="update",
        before={"phone": "fake"},
        after={"phone": None},
    )
    second = first.model_copy(update={"after": {}})
    assert len(compare([[first], [second], [first]]).conflicting_changes) == 2


def test_insert_values_are_order_independent():
    first = DatabaseChange(
        table="customers", row_id=1, operation="insert", after={"name": "Demo", "status": "active"}
    )
    second = first.model_copy(update={"after": {"status": "active", "name": "Demo"}})
    assert len(compare([[first], [second], [first]]).unanimous_changes) == 1


def test_delete_preimages_must_match():
    first = DatabaseChange(
        table="customers", row_id=1, operation="delete", before={"status": "active"}
    )
    second = first.model_copy(update={"before": {"status": "inactive"}})
    assert len(compare([[first], [second], [first]]).conflicting_changes) == 2


def test_failed_and_skipped_agents_are_not_unchanged_votes():
    for status in ("failed", "skipped"):
        runs = [RunResult(task_id="task", agent=f"a{i}", changes=[change()]) for i in range(3)]
        runs[2].status = status
        result = compare_changes(runs)
        assert not result.unanimous_changes
        entry = result.partial_agreement_changes[0]
        assert entry.unavailable_agent_ids == ["a2"]
        assert entry.unchanged_agent_ids == []
        assert result.affected_row_count_per_agent["a2"] == 0
        assert result.warnings


def test_transient_events_affect_blast_radius_without_net_consensus():
    inserted = DatabaseChange(table="customers", row_id=99, operation="insert", after={"id": 99})
    runs = [RunResult(task_id="task", agent=f"a{i}") for i in range(3)]
    runs[0].sql_operations = [SQLOperation(sql="mock", status="completed", changes=[inserted])]
    runs[1].sql_operations = [SQLOperation(sql="mock", status="rolled_back", changes=[inserted])]
    result = compare_changes(runs)
    assert result.affected_row_count == 0
    assert result.affected_row_count_per_agent == {"a0": 1, "a1": 0, "a2": 0}
    assert result.maximum_affected_row_count == result.blast_radius_estimate == 1
    assert not result.unanimous_changes and not result.conflicting_changes


def test_noop_updates_and_empty_results():
    noop = change(1)
    result = compare([[noop], [], []])
    assert (
        result.affected_row_count
        == result.maximum_affected_row_count
        == result.blast_radius_estimate
        == 0
    )
    assert not result.conflicting_changes


def test_three_unique_agents_and_one_task_required():
    with pytest.raises(ValueError, match="Exactly three"):
        compare_changes([])
    with pytest.raises(ValueError, match="distinct"):
        compare_changes([RunResult(task_id="task", agent="same")] * 3)
    with pytest.raises(ValueError, match="same task"):
        compare_changes([RunResult(task_id=str(i), agent=str(i)) for i in range(3)])


def test_invalid_observations_rejected():
    invalid = DatabaseChange(table="customers", row_id=1, operation="delete", after={"id": 1})
    with pytest.raises(ValueError, match="before image"):
        compare([[invalid], [], []])


def test_results_are_deterministic_and_inputs_unchanged():
    observations = [[change(row_id=2), change()], [change()], [change(2)]]
    original = [[entry.model_dump() for entry in changes] for changes in observations]
    first = compare(observations).model_dump()
    assert compare([list(reversed(changes)) for changes in observations]).model_dump() == first
    assert [[entry.model_dump() for entry in changes] for changes in observations] == original
