"""Consensus and conflict classification."""

import pytest

from app.models import DatabaseChange
from app.services.diff_engine import compare_changes


def change(value=0):
    """Build a synthetic update observation."""
    return DatabaseChange(
        table="customers",
        row_id=1,
        operation="update",
        before={"active": 1},
        after={"active": value},
    )


def test_unanimous():
    result = compare_changes([[change()], [change()], [change()]])
    assert len(result.unanimous_changes) == 1
    assert result.affected_row_count == 1
    assert not result.conflicting_changes


def test_partial():
    result = compare_changes([[change()], [change()], []])
    assert len(result.partial_agreement_changes) == 1
    assert not result.unanimous_changes


def test_conflicting():
    result = compare_changes([[change()], [change()], [change(2)]])
    assert len(result.conflicting_changes) == 2
    assert not result.unanimous_changes
    assert not result.partial_agreement_changes
    assert result.affected_row_count == 1


def test_duplicates_do_not_add_votes():
    result = compare_changes([[change(), change(), change()], [], []])
    assert not result.unanimous_changes
    assert len(result.partial_agreement_changes) == 1


def test_three_agents_required():
    with pytest.raises(ValueError):
        compare_changes([[]])
