"""Application service: ResearchRunEngine.

Coordinates pure domain transitions with infrastructure ports. This is the
write path that will replace WorkflowEngine after dual-write freeze.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from domain.research_run import (
    ArtifactRef,
    ResearchRun,
    RunStatus,
    finish_current_task,
    new_run,
    retry_task,
    run_to_dict,
    start_current_task,
    transition_run,
)

from services.research_run_ports import (
    ArtifactIntegrityError,
    ArtifactStore,
    Clock,
    EventLog,
    IdFactory,
    RunRepository,
    StaleRunVersion,
    SystemClock,
    UuidFactory,
)


@dataclass
class ResearchRunEngine:
    repository: RunRepository
    artifacts: ArtifactStore
    events: EventLog
    clock: Clock = None  # type: ignore[assignment]
    ids: IdFactory = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.clock is None:
            self.clock = SystemClock()
        if self.ids is None:
            self.ids = UuidFactory()

    def create_run(
        self,
        project_id: str,
        task_specs: Sequence[tuple[str, Sequence[str]]],
        *,
        actor: str = "system",
        run_id: str | None = None,
    ) -> ResearchRun:
        if not project_id:
            raise ValueError("project_id is required")
        if not task_specs:
            raise ValueError("task_specs must not be empty")
        normalized: list[tuple[str, tuple[str, ...]]] = []
        for item in task_specs:
            if not item or not item[0]:
                raise ValueError("each task_spec needs a task name")
            name = str(item[0])
            gates = tuple(str(g) for g in (item[1] if len(item) > 1 else ()))
            normalized.append((name, gates))
        rid = run_id or self.ids.new_id("run_")
        run = new_run(project_id, tuple(normalized), actor=actor, run_id=rid)
        saved = self.repository.save(run, expected_version=0)
        self._project_events(saved, previous_version=0)
        return saved

    def get_run(self, run_id: str) -> ResearchRun:
        run = self.repository.get(run_id)
        if run is None:
            raise KeyError(f"research run not found: {run_id}")
        return run

    def start_task(self, run_id: str, *, expected_version: int, actor: str = "system") -> ResearchRun:
        current = self._load_for_update(run_id, expected_version)
        previous = current.version
        run = current
        if run.status == RunStatus.PAUSED:
            run = transition_run(run, RunStatus.RUNNING, actor=actor)
        elif run.status == RunStatus.BLOCKED:
            # resume is explicit via retry + start; do not auto-unblock
            raise ValueError("cannot start task while run is blocked; retry first")
        run = start_current_task(run, actor=actor)
        return self._persist(run, expected_version=previous)

    def finish_task(
        self,
        run_id: str,
        *,
        expected_version: int,
        input_data: Mapping[str, Any],
        output_data: Mapping[str, Any],
        artifacts: Sequence[ArtifactRef] = (),
        gate_passed: bool,
        actor: str = "system",
        failure_reason: str | None = None,
        require_artifact_blobs: bool = True,
    ) -> ResearchRun:
        current = self._load_for_update(run_id, expected_version)
        previous = current.version
        arts = tuple(artifacts)
        if require_artifact_blobs:
            self._assert_artifacts_present(arts)
        run = finish_current_task(
            current,
            input_data=input_data,
            output_data=output_data,
            artifacts=arts,
            gate_passed=gate_passed,
            actor=actor,
            failure_reason=failure_reason,
        )
        return self._persist(run, expected_version=previous)

    def retry_task(
        self,
        run_id: str,
        task_name: str,
        *,
        expected_version: int,
        actor: str = "system",
    ) -> ResearchRun:
        current = self._load_for_update(run_id, expected_version)
        previous = current.version
        run = retry_task(current, task_name, actor=actor)
        return self._persist(run, expected_version=previous)

    def cancel_run(self, run_id: str, *, expected_version: int, actor: str = "system") -> ResearchRun:
        current = self._load_for_update(run_id, expected_version)
        previous = current.version
        run = transition_run(current, RunStatus.CANCELLED, actor=actor)
        return self._persist(run, expected_version=previous)

    def put_artifact(self, content: bytes, *, content_type: str = "application/octet-stream") -> ArtifactRef:
        return self.artifacts.put(content, content_type=content_type)

    def _load_for_update(self, run_id: str, expected_version: int) -> ResearchRun:
        run = self.repository.get(run_id)
        if run is None:
            raise KeyError(f"research run not found: {run_id}")
        if run.version != expected_version:
            raise StaleRunVersion(
                f"stale run version for {run_id}: expected {expected_version}, stored {run.version}"
            )
        return run

    def _persist(self, run: ResearchRun, *, expected_version: int) -> ResearchRun:
        saved = self.repository.save(run, expected_version=expected_version)
        self._project_events(saved, previous_version=expected_version)
        return saved

    def _project_events(self, run: ResearchRun, *, previous_version: int) -> None:
        payload = run_to_dict(run)
        new_events = [
            e for e in payload.get("events", []) if int(e.get("aggregate_version", 0)) > previous_version
        ]
        if new_events:
            self.events.append(run.id, new_events)

    def _assert_artifacts_present(self, artifacts: Sequence[ArtifactRef]) -> None:
        for art in artifacts:
            if not art.sha256 or len(art.sha256) != 64:
                raise ArtifactIntegrityError(f"artifact {art.id} missing valid sha256")
            if not self.artifacts.exists(art.sha256):
                raise ArtifactIntegrityError(
                    f"artifact content missing for {art.id} sha256={art.sha256}"
                )
