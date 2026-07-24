"""Ports for ResearchRunEngine infrastructure isolation.

Domain code must not import these ports. Application services depend on the
protocols; adapters (SQLite, filesystem, etc.) implement them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from domain.research_run import ArtifactRef, ResearchRun, run_from_dict, run_to_dict


class StaleRunVersion(RuntimeError):
    """Optimistic concurrency failure: expected version did not match stored."""


class ArtifactIntegrityError(RuntimeError):
    """Artifact content missing or hash mismatch."""


class LegacyWriteFrozen(RuntimeError):
    """Legacy WorkflowEngine write path is frozen after dual-write cutover."""


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class IdFactory(Protocol):
    def new_id(self, prefix: str = "") -> str: ...


@runtime_checkable
class RunRepository(Protocol):
    def get(self, run_id: str) -> ResearchRun | None: ...

    def save(self, run: ResearchRun, *, expected_version: int | None = None) -> ResearchRun: ...

    def list_by_project(self, project_id: str) -> list[ResearchRun]: ...


@runtime_checkable
class ArtifactStore(Protocol):
    def put(self, content: bytes, *, content_type: str = "application/octet-stream") -> ArtifactRef: ...

    def get(self, sha256: str) -> bytes: ...

    def exists(self, sha256: str) -> bool: ...


@runtime_checkable
class EventLog(Protocol):
    def append(self, run_id: str, events: list[Mapping[str, Any]]) -> None: ...

    def list(self, run_id: str) -> list[dict[str, Any]]: ...


@dataclass
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class UuidFactory:
    def new_id(self, prefix: str = "") -> str:
        value = uuid4().hex
        return f"{prefix}{value}" if prefix else value


@dataclass
class InMemoryRunRepository:
    """Test/dev adapter with optimistic version checks."""

    _runs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, run_id: str) -> ResearchRun | None:
        raw = self._runs.get(run_id)
        if raw is None:
            return None
        return run_from_dict(raw)

    def save(self, run: ResearchRun, *, expected_version: int | None = None) -> ResearchRun:
        existing = self._runs.get(run.id)
        if expected_version is not None:
            current_version = 0 if existing is None else int(existing.get("version", 0))
            if current_version != expected_version:
                raise StaleRunVersion(
                    f"stale run version for {run.id}: expected {expected_version}, stored {current_version}"
                )
        # store a detached copy
        self._runs[run.id] = run_to_dict(run)
        return run_from_dict(self._runs[run.id])

    def list_by_project(self, project_id: str) -> list[ResearchRun]:
        out: list[ResearchRun] = []
        for raw in self._runs.values():
            if raw.get("project_id") == project_id:
                out.append(run_from_dict(raw))
        return sorted(out, key=lambda r: r.created_at)


@dataclass
class InMemoryArtifactStore:
    _blobs: dict[str, bytes] = field(default_factory=dict)

    def put(self, content: bytes, *, content_type: str = "application/octet-stream") -> ArtifactRef:
        import hashlib

        digest = hashlib.sha256(content).hexdigest()
        self._blobs[digest] = content
        return ArtifactRef(
            id=digest[:16],
            kind="blob",
            uri=f"memory://{digest}",
            sha256=digest,
            schema_version="artifact/v1",
        )

    def get(self, sha256: str) -> bytes:
        if sha256 not in self._blobs:
            raise ArtifactIntegrityError(f"artifact content missing for sha256={sha256}")
        return self._blobs[sha256]

    def exists(self, sha256: str) -> bool:
        return sha256 in self._blobs


@dataclass
class InMemoryEventLog:
    _events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def append(self, run_id: str, events: list[Mapping[str, Any]]) -> None:
        bucket = self._events.setdefault(run_id, [])
        for event in events:
            bucket.append(dict(event))

    def list(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(run_id, []))
