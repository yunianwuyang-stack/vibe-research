"""Dependency-scoped dirty/stale propagation with auditable rollback history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .ports import ConcurrencyConflict


@dataclass(frozen=True)
class LedgerEvent:
    sequence: int
    kind: str
    node_id: str
    detail: str


class DependencyLedger:
    """In-memory reference model for downstream-only invalidation semantics."""

    def __init__(self) -> None:
        self._children: dict[str, set[str]] = {}
        self._parents: dict[str, set[str]] = {}
        self._stale: set[str] = set()
        self._versions: dict[str, int] = {}
        self._events: list[LedgerEvent] = []

    def add_node(self, node_id: str) -> None:
        self._children.setdefault(node_id, set()); self._parents.setdefault(node_id, set()); self._versions.setdefault(node_id, 1)

    def link(self, upstream: str, downstream: str) -> None:
        self.add_node(upstream); self.add_node(downstream)
        self._children[upstream].add(downstream); self._parents[downstream].add(upstream)

    def change_upstream(self, node_id: str, expected_version: int) -> int:
        if self._versions.get(node_id) != expected_version:
            raise ConcurrencyConflict("stale upstream update")
        self._versions[node_id] += 1
        for child in self._descendants(node_id):
            self._stale.add(child); self._append("stale", child, f"upstream changed: {node_id}")
        self._append("changed", node_id, "version incremented")
        return self._versions[node_id]

    def revalidate(self, node_id: str) -> None:
        if any(parent in self._stale for parent in self._parents.get(node_id, ())):
            raise ValueError("cannot revalidate while an upstream dependency is stale")
        self._stale.discard(node_id); self._append("revalidated", node_id, "validation refreshed")

    def rollback(self, node_id: str, reason: str) -> None:
        self._stale.add(node_id); self._append("rollback", node_id, reason)

    def is_stale(self, node_id: str) -> bool: return node_id in self._stale
    def events(self) -> tuple[LedgerEvent, ...]: return tuple(self._events)

    def _descendants(self, node_id: str) -> set[str]:
        found: set[str] = set(); pending = list(self._children.get(node_id, ()))
        while pending:
            candidate = pending.pop()
            if candidate not in found:
                found.add(candidate); pending.extend(self._children.get(candidate, ()))
        return found

    def _append(self, kind: str, node_id: str, detail: str) -> None:
        self._events.append(LedgerEvent(len(self._events) + 1, kind, node_id, detail))
