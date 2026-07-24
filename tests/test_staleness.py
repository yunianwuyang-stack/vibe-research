from __future__ import annotations

import pytest

from application.ports import ConcurrencyConflict
from application.staleness import DependencyLedger


def _graph() -> DependencyLedger:
    ledger = DependencyLedger()
    ledger.link("source", "claim"); ledger.link("claim", "paper"); ledger.link("other", "unrelated")
    return ledger


def test_upstream_change_marks_only_transitive_downstream_nodes_stale() -> None:
    ledger = _graph(); assert ledger.change_upstream("source", 1) == 2
    assert ledger.is_stale("claim") and ledger.is_stale("paper")
    assert not ledger.is_stale("source") and not ledger.is_stale("unrelated")


def test_revalidation_requires_clean_parents_and_clears_only_selected_node() -> None:
    ledger = _graph(); ledger.change_upstream("source", 1)
    with pytest.raises(ValueError): ledger.revalidate("paper")
    ledger.revalidate("claim"); ledger.revalidate("paper")
    assert not ledger.is_stale("claim") and not ledger.is_stale("paper")


def test_rollback_retains_append_only_audit_history() -> None:
    ledger = _graph(); ledger.rollback("claim", "contradictory result")
    ledger.revalidate("claim")
    assert [event.kind for event in ledger.events()] == ["rollback", "revalidated"]
    assert ledger.events()[0].detail == "contradictory result"


def test_concurrent_version_conflict_preserves_existing_state() -> None:
    ledger = _graph(); ledger.change_upstream("source", 1)
    with pytest.raises(ConcurrencyConflict): ledger.change_upstream("source", 1)
    assert ledger.is_stale("claim")
