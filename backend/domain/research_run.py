"""Framework-free domain model for the canonical research run.

The run is the only mutable aggregate used by the new research path. HTTP,
SQLite, Electron and provider SDKs are deliberately absent from this module.
All state changes return a new immutable aggregate and append an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


SCHEMA_VERSION = "research-run/v2"
_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")


class RunStatus(str, Enum):
    PAUSED = "paused"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AttemptStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class GateStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class ArtifactRef:
    """Immutable, content-addressed output consumed by a task attempt."""

    id: str
    kind: str
    uri: str
    sha256: str
    schema_version: str
    input_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.kind.strip() or not self.uri.strip():
            raise ValueError("artifact id, kind and uri are required")
        if not self.schema_version.strip():
            raise ValueError("artifact schema_version is required")
        _sha256(self.sha256, "artifact sha256")
        for value in self.input_hashes:
            _sha256(value, "artifact input hash")


@dataclass(frozen=True)
class Gate:
    name: str
    required: bool = True
    status: GateStatus = GateStatus.PENDING
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("gate name is required")
        if not isinstance(self.status, GateStatus):
            raise ValueError("invalid gate status")


@dataclass(frozen=True)
class TaskAttempt:
    id: str
    number: int
    status: AttemptStatus
    input: Mapping[str, Any]
    output: Mapping[str, Any]
    artifact_ids: tuple[str, ...]
    started_at: str
    finished_at: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("attempt number must be positive")
        if not self.id.strip():
            raise ValueError("attempt id is required")
        if not isinstance(self.status, AttemptStatus):
            raise ValueError("invalid attempt status")


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    position: int
    status: TaskStatus
    gates: tuple[Gate, ...]
    attempts: tuple[TaskAttempt, ...] = ()
    output: Mapping[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("task id and name are required")
        if self.position < 0:
            raise ValueError("task position must not be negative")
        if not isinstance(self.status, TaskStatus):
            raise ValueError("invalid task status")
        if len({gate.name for gate in self.gates}) != len(self.gates):
            raise ValueError("task gate names must be unique")
        if tuple(sorted(item.number for item in self.attempts)) != tuple(item.number for item in self.attempts):
            raise ValueError("task attempts must be ordered")

    @property
    def current_attempt(self) -> TaskAttempt | None:
        return self.attempts[-1] if self.attempts else None


@dataclass(frozen=True)
class RunEvent:
    id: str
    event_type: str
    actor: str
    aggregate_version: int
    payload: Mapping[str, Any]
    occurred_at: str

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.event_type.strip() or not self.actor.strip():
            raise ValueError("event id, type and actor are required")
        if self.aggregate_version < 1:
            raise ValueError("event aggregate_version must be positive")


@dataclass(frozen=True)
class ResearchRun:
    id: str
    project_id: str
    status: RunStatus
    current_task: str | None
    version: int
    tasks: tuple[Task, ...]
    events: tuple[RunEvent, ...]
    artifacts: tuple[ArtifactRef, ...] = ()
    schema_version: str = SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.project_id.strip():
            raise ValueError("run id and project_id are required")
        if self.version < 1:
            raise ValueError("run version must be positive")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported run schema: {self.schema_version}")
        if not self.tasks:
            raise ValueError("a research run requires at least one task")
        if len({task.name for task in self.tasks}) != len(self.tasks):
            raise ValueError("task names must be unique")
        if self.current_task is not None and self.current_task not in {task.name for task in self.tasks}:
            raise ValueError("current_task must reference a task")

    def task(self, name: str) -> Task:
        for task in self.tasks:
            if task.name == name:
                return task
        raise KeyError(name)

    def mark_stale(self, reason: str, *, actor: str = "system") -> "ResearchRun":
        if not reason.strip():
            raise ValueError("stale reason is required")
        return self._replace(
            event_type="run_marked_stale",
            actor=actor,
            payload={"reason": reason.strip()},
        )

    def _replace(
        self,
        *,
        status: RunStatus | None = None,
        current_task: str | None | object = _UNSET,
        tasks: tuple[Task, ...] | None = None,
        artifacts: tuple[ArtifactRef, ...] | None = None,
        event_type: str,
        actor: str,
        payload: Mapping[str, Any],
    ) -> "ResearchRun":
        next_version = self.version + 1
        event = RunEvent(
            id=_id("evt"),
            event_type=event_type,
            actor=actor,
            aggregate_version=next_version,
            payload=dict(payload),
            occurred_at=_now(),
        )
        chosen_task = self.current_task if current_task is _UNSET else current_task
        return replace(
            self,
            status=status or self.status,
            current_task=chosen_task,  # type: ignore[arg-type]
            version=next_version,
            tasks=tasks or self.tasks,
            artifacts=artifacts or self.artifacts,
            events=(*self.events, event),
            updated_at=event.occurred_at,
        )


def new_run(
    project_id: str,
    task_specs: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    actor: str = "system",
    run_id: str | None = None,
) -> ResearchRun:
    """Create the canonical paused run and its version-one task graph."""

    if not task_specs:
        raise ValueError("task_specs must not be empty")
    tasks = tuple(
        Task(
            id=_id("task"),
            name=name,
            position=index,
            status=TaskStatus.PENDING,
            gates=tuple(Gate(gate_name) for gate_name in gates),
        )
        for index, (name, gates) in enumerate(task_specs)
    )
    timestamp = _now()
    return ResearchRun(
        id=run_id or _id("run"),
        project_id=project_id,
        status=RunStatus.PAUSED,
        current_task=tasks[0].name,
        version=1,
        tasks=tasks,
        events=(
            RunEvent(
                id=_id("evt"),
                event_type="run_created",
                actor=actor,
                aggregate_version=1,
                payload={"schema_version": SCHEMA_VERSION, "task_count": len(tasks)},
                occurred_at=timestamp,
            ),
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def transition_run(run: ResearchRun, target: RunStatus, *, actor: str = "system") -> ResearchRun:
    allowed = {
        RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.CANCELLED},
        RunStatus.RUNNING: {RunStatus.PAUSED, RunStatus.BLOCKED, RunStatus.COMPLETED, RunStatus.CANCELLED},
        RunStatus.BLOCKED: {RunStatus.PAUSED, RunStatus.CANCELLED},
        RunStatus.COMPLETED: set(),
        RunStatus.CANCELLED: set(),
    }
    if target not in allowed[run.status]:
        raise ValueError(f"illegal run transition: {run.status.value}->{target.value}")
    return run._replace(
        status=target,
        event_type="run_transitioned",
        actor=actor,
        payload={"from": run.status.value, "to": target.value},
    )


def start_current_task(run: ResearchRun, *, actor: str = "system") -> ResearchRun:
    if run.status != RunStatus.RUNNING:
        raise ValueError("a task can start only while the run is running")
    if run.current_task is None:
        raise ValueError("run has no current task")
    task = run.task(run.current_task)
    if task.status not in {TaskStatus.PENDING, TaskStatus.BLOCKED}:
        return run
    attempt = TaskAttempt(
        id=_id("attempt"),
        number=len(task.attempts) + 1,
        status=AttemptStatus.RUNNING,
        input={},
        output={},
        artifact_ids=(),
        started_at=_now(),
    )
    updated_task = replace(task, status=TaskStatus.RUNNING, attempts=(*task.attempts, attempt), failure_reason=None)
    tasks = tuple(updated_task if item.name == task.name else item for item in run.tasks)
    return run._replace(
        tasks=tasks,
        event_type="task_attempt_started",
        actor=actor,
        payload={"task": task.name, "attempt": attempt.number},
    )


def finish_current_task(
    run: ResearchRun,
    *,
    input_data: Mapping[str, Any],
    output_data: Mapping[str, Any],
    artifacts: tuple[ArtifactRef, ...],
    gate_passed: bool,
    actor: str = "system",
    failure_reason: str | None = None,
) -> ResearchRun:
    if run.current_task is None:
        raise ValueError("run has no current task")
    task = run.task(run.current_task)
    active_run = run
    if task.status == TaskStatus.PENDING:
        if run.status == RunStatus.PAUSED:
            active_run = replace(run, status=RunStatus.RUNNING)
        active_run = start_current_task(active_run, actor=actor)
        task = active_run.task(run.current_task)
    if task.status != TaskStatus.RUNNING or task.current_attempt is None:
        raise ValueError("current task has no running attempt")

    attempt = task.current_attempt
    terminal = AttemptStatus.COMPLETED if gate_passed else AttemptStatus.BLOCKED
    completed_attempt = replace(
        attempt,
        status=terminal,
        input=dict(input_data),
        output=dict(output_data),
        artifact_ids=tuple(item.id for item in artifacts),
        finished_at=_now(),
        failure_reason=failure_reason,
    )
    task_status = TaskStatus.COMPLETED if gate_passed else TaskStatus.BLOCKED
    updated_task = replace(
        task,
        status=task_status,
        attempts=(*task.attempts[:-1], completed_attempt),
        output=dict(output_data),
        failure_reason=failure_reason,
        gates=tuple(
            replace(gate, status=GateStatus.PASSED if gate_passed else GateStatus.FAILED, reason=failure_reason)
            for gate in task.gates
        ),
    )
    tasks = tuple(updated_task if item.name == task.name else item for item in active_run.tasks)
    if not gate_passed:
        return active_run._replace(
            status=RunStatus.BLOCKED,
            tasks=tasks,
            artifacts=tuple({item.id: item for item in (*active_run.artifacts, *artifacts)}.values()),
            event_type="task_blocked",
            actor=actor,
            payload={"task": task.name, "reason": failure_reason or "gate_failed"},
        )

    next_task = next((item for item in tasks if item.position > task.position and item.status == TaskStatus.PENDING), None)
    return active_run._replace(
        status=RunStatus.PAUSED if next_task else RunStatus.COMPLETED,
        current_task=next_task.name if next_task else None,
        tasks=tasks,
        artifacts=tuple({item.id: item for item in (*active_run.artifacts, *artifacts)}.values()),
        event_type="task_completed",
        actor=actor,
        payload={"task": task.name, "next_task": next_task.name if next_task else None},
    )


def retry_task(run: ResearchRun, task_name: str, *, actor: str = "system") -> ResearchRun:
    task = run.task(task_name)
    if task.status not in {TaskStatus.BLOCKED, TaskStatus.CANCELLED}:
        raise ValueError("only a blocked or cancelled task can be retried")
    if run.status not in {RunStatus.BLOCKED, RunStatus.PAUSED}:
        raise ValueError("run must be blocked or paused before retry")
    updated_task = replace(task, status=TaskStatus.PENDING, failure_reason=None)
    tasks = tuple(updated_task if item.name == task_name else item for item in run.tasks)
    return run._replace(
        status=RunStatus.PAUSED,
        current_task=task_name,
        tasks=tasks,
        event_type="task_retry_requested",
        actor=actor,
        payload={"task": task_name, "next_attempt": len(task.attempts) + 1},
    )


def run_to_dict(run: ResearchRun) -> dict[str, Any]:
    """Stable API-independent serialization used by adapters and tests."""

    def attempt_dict(attempt: TaskAttempt) -> dict[str, Any]:
        return {
            "id": attempt.id,
            "number": attempt.number,
            "status": attempt.status.value,
            "input": dict(attempt.input),
            "output": dict(attempt.output),
            "artifact_ids": list(attempt.artifact_ids),
            "started_at": attempt.started_at,
            "finished_at": attempt.finished_at,
            "failure_reason": attempt.failure_reason,
        }

    def task_dict(task: Task) -> dict[str, Any]:
        attempt = task.current_attempt
        return {
            "id": task.id,
            "name": task.name,
            "status": task.status.value,
            "position": task.position,
            "input": dict(attempt.input) if attempt else {},
            "output": dict(task.output),
            "artifacts": list(attempt.artifact_ids) if attempt else [],
            "provenance": [],
            "gate": {
                "required": [gate.name for gate in task.gates if gate.required],
                "results": {gate.name: gate.status.value for gate in task.gates},
            },
            "attempts": [attempt_dict(item) for item in task.attempts],
            "attempt_count": len(task.attempts),
            "failure_reason": task.failure_reason,
        }

    return {
        "id": run.id,
        "project_id": run.project_id,
        "schema_version": run.schema_version,
        "status": run.status.value,
        "current_task": run.current_task,
        "current_step": run.current_task,
        "version": run.version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "tasks": [task_dict(task) for task in run.tasks],
        "steps": [task_dict(task) for task in run.tasks],
        "artifacts": [
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "uri": artifact.uri,
                "sha256": artifact.sha256,
                "schema_version": artifact.schema_version,
                "input_hashes": list(artifact.input_hashes),
            }
            for artifact in run.artifacts
        ],
        "events": [
            {
                "id": event.id,
                "type": event.event_type,
                "actor": event.actor,
                "aggregate_version": event.aggregate_version,
                "payload": dict(event.payload),
                "occurred_at": event.occurred_at,
            }
            for event in run.events
        ],
    }


def run_from_dict(data: Mapping[str, Any]) -> ResearchRun:
    """Rehydrate the canonical aggregate without involving delivery adapters."""

    def parse_attempt(item: Mapping[str, Any]) -> TaskAttempt:
        return TaskAttempt(
            id=str(item["id"]), number=int(item["number"]), status=AttemptStatus(str(item["status"])),
            input=dict(item.get("input", {})), output=dict(item.get("output", {})),
            artifact_ids=tuple(str(value) for value in item.get("artifact_ids", ())),
            started_at=str(item["started_at"]),
            finished_at=str(item["finished_at"]) if item.get("finished_at") is not None else None,
            failure_reason=str(item["failure_reason"]) if item.get("failure_reason") is not None else None,
        )

    tasks = tuple(
        Task(
            id=str(item["id"]), name=str(item["name"]), position=int(item["position"]),
            status=TaskStatus(str(item["status"])),
            gates=tuple(
                Gate(name=str(name), required=str(name) in set(item.get("gate", {}).get("required", ())), status=GateStatus(str(status)))
                for name, status in item.get("gate", {}).get("results", {}).items()
            ),
            attempts=tuple(parse_attempt(value) for value in item.get("attempts", ()) if isinstance(value, Mapping)),
            output=dict(item.get("output", {})),
            failure_reason=str(item["failure_reason"]) if item.get("failure_reason") is not None else None,
        )
        for item in data.get("tasks", data.get("steps", ()))
    )
    artifacts = tuple(
        ArtifactRef(
            id=str(item["id"]), kind=str(item["kind"]), uri=str(item["uri"]),
            sha256=str(item["sha256"]), schema_version=str(item["schema_version"]),
            input_hashes=tuple(str(value) for value in item.get("input_hashes", ())),
        )
        for item in data.get("artifacts", ())
    )
    events = tuple(
        RunEvent(
            id=str(item["id"]), event_type=str(item.get("type", item.get("event_type"))),
            actor=str(item["actor"]), aggregate_version=int(item["aggregate_version"]),
            payload=dict(item.get("payload", {})), occurred_at=str(item["occurred_at"]),
        )
        for item in data.get("events", ())
    )
    return ResearchRun(
        id=str(data["id"]), project_id=str(data["project_id"]), status=RunStatus(str(data["status"])),
        current_task=data.get("current_task", data.get("current_step")), version=int(data["version"]),
        tasks=tasks, events=events, artifacts=artifacts,
        schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        created_at=str(data["created_at"]), updated_at=str(data["updated_at"]),
    )
