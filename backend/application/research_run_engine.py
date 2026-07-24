"""The sole application entry point for creating and advancing research runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from domain.research_run import (
    ArtifactRef,
    ResearchRun,
    RunStatus,
    finish_current_task,
    new_run,
    retry_task,
    run_to_dict,
    transition_run,
)

from .ports import ResearchRunRepository


@dataclass(frozen=True)
class RunAdvance:
    """Application-level command; delivery adapters map HTTP/IPC to this type."""

    run_id: str
    task_name: str
    input_data: dict[str, Any]
    artifacts: list[dict[str, Any]]
    provenance: list[dict[str, Any]]
    gate_passed: bool
    failure_reason: str | None = None
    actor: str = "system"


class ResearchRunEngine:
    """Own all lifecycle mutations for a canonical research run.

    The engine deliberately knows only the repository port and the pure
    aggregate.  SQLite, FastAPI, Electron, filesystem paths, and model SDKs
    stay behind adapters.
    """

    def __init__(
        self,
        repository: ResearchRunRepository,
        *,
        default_task_specs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> None:
        if not default_task_specs:
            raise ValueError("default_task_specs must not be empty")
        self.repository = repository
        self.default_task_specs = default_task_specs

    def create(
        self,
        project_id: str,
        *,
        task_specs: tuple[tuple[str, tuple[str, ...]], ...] | None = None,
        actor: str = "system",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.repository.project_exists(project_id):
            raise KeyError(f"research project not found: {project_id}")
        run = new_run(
            project_id,
            task_specs or self.default_task_specs,
            actor=actor,
            run_id=run_id,
        )
        with self.repository.transaction():
            self.repository.create_run(run)
        return run_to_dict(run)

    def read(self, run_id: str) -> dict[str, Any]:
        return run_to_dict(self.repository.get_run(run_id))

    def list_for_project(self, project_id: str) -> dict[str, Any]:
        if not self.repository.project_exists(project_id):
            raise KeyError(f"research project not found: {project_id}")
        runs = self.repository.list_runs(project_id)
        serialized = [run_to_dict(run) for run in runs]
        preferred = next(
            (
                run
                for run in serialized
                if run["status"] in {"running", "paused", "blocked"}
            ),
            serialized[0] if serialized else None,
        )
        return {
            "project_id": project_id,
            "runs": [
                {
                    "id": run["id"],
                    "project_id": run["project_id"],
                    "status": run["status"],
                    "current_step": run["current_task"],
                    "created_at": run["created_at"],
                    "updated_at": run["updated_at"],
                    "version": run["version"],
                }
                for run in serialized
            ],
            "active": preferred,
            "count": len(serialized),
        }

    def resume(self, run_id: str, *, actor: str = "system") -> dict[str, Any]:
        return self._transition(run_id, RunStatus.RUNNING, actor=actor)

    def cancel(self, run_id: str, reason: str, *, actor: str = "system") -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("cancel reason is required")
        run = self.repository.get_run(run_id)
        updated = transition_run(
            run,
            RunStatus.CANCELLED,
            actor=actor,
        )
        updated = updated._replace(
            event_type="run_cancelled",
            actor=actor,
            payload={"reason": reason},
        )
        self._save(run, updated)
        return run_to_dict(updated)

    def retry(self, run_id: str, task_name: str, *, actor: str = "system") -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        updated = retry_task(run, task_name, actor=actor)
        self._save(run, updated)
        return run_to_dict(updated)

    def advance(self, command: RunAdvance) -> dict[str, Any]:
        run = self.repository.get_run(command.run_id)
        if run.current_task != command.task_name:
            raise ValueError("step is not current")

        artifact_refs: tuple[ArtifactRef, ...] = ()
        if command.gate_passed:
            artifact_refs = self._verified_artifacts(
                run.project_id,
                command.artifacts,
                command.provenance,
            )
        updated = finish_current_task(
            run,
            input_data=command.input_data,
            output_data={
                "status": "completed" if command.gate_passed else "blocked",
                "next": self._next_task_name(run, command.task_name) if command.gate_passed else None,
            },
            artifacts=artifact_refs,
            gate_passed=command.gate_passed,
            actor=command.actor,
            failure_reason=command.failure_reason,
        )
        next_task = updated.current_task
        if next_task is not None:
            output = dict(updated.task(command.task_name).output)
            output["next"] = next_task
            updated = self._replace_task_output(updated, command.task_name, output)
        self._save(run, updated)
        return run_to_dict(updated)

    def _transition(self, run_id: str, target: RunStatus, *, actor: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        updated = transition_run(run, target, actor=actor)
        self._save(run, updated)
        return run_to_dict(updated)

    def _save(self, original: ResearchRun, updated: ResearchRun) -> None:
        with self.repository.transaction():
            self.repository.save_run(updated, expected_version=original.version)

    def _verified_artifacts(
        self,
        project_id: str,
        artifacts: list[dict[str, Any]],
        provenance: list[dict[str, Any]],
    ) -> tuple[ArtifactRef, ...]:
        ids = [str(item.get("id", "")).strip() for item in artifacts]
        if not ids or any(not item for item in ids):
            raise ValueError("artifacts and provenance are required")
        if len(ids) != len(set(ids)):
            raise ValueError("artifact identifiers must be unique")
        rows = self.repository.verified_artifacts(project_id, ids)
        if len(rows) != len(ids):
            raise ValueError("only server-verified project artifacts may pass a gate")
        known_provenance = {str(row["provenance"]) for row in rows}
        requested_provenance = {
            str(item.get("source", item.get("provenance", ""))).strip()
            for item in provenance
        }
        if not requested_provenance or not requested_provenance.issubset(known_provenance):
            raise ValueError("provenance must match verified artifact records")
        by_id = {str(row["id"]): row for row in rows}
        return tuple(
            ArtifactRef(
                id=artifact_id,
                kind=str(by_id[artifact_id]["kind"]),
                uri=str(by_id[artifact_id]["provenance"]),
                sha256=str(by_id[artifact_id]["sha256"]),
                schema_version="research-artifact/v1",
            )
            for artifact_id in ids
        )

    def _next_task_name(self, run: ResearchRun, task_name: str) -> str | None:
        task = run.task(task_name)
        return next((item.name for item in run.tasks if item.position > task.position), None)

    @staticmethod
    def _replace_task_output(run: ResearchRun, task_name: str, output: dict[str, Any]) -> ResearchRun:
        from dataclasses import replace

        task = run.task(task_name)
        updated_task = replace(task, output=output)
        return replace(
            run,
            tasks=tuple(updated_task if item.name == task_name else item for item in run.tasks),
        )


class InMemoryResearchRunRepository:
    """Small deterministic adapter for domain/application tests."""

    def __init__(self, projects: Iterable[str] = ()) -> None:
        self.projects = set(projects)
        self.runs: dict[str, ResearchRun] = {}

    from contextlib import contextmanager

    @contextmanager
    def transaction(self):
        snapshot = dict(self.runs)
        try:
            yield
        except Exception:
            self.runs = snapshot
            raise

    def project_exists(self, project_id: str) -> bool:
        return project_id in self.projects

    def create_run(self, run: ResearchRun) -> None:
        if run.id in self.runs:
            raise ValueError("run already exists")
        self.runs[run.id] = run

    def get_run(self, run_id: str) -> ResearchRun:
        try:
            return self.runs[run_id]
        except KeyError as error:
            raise KeyError(f"research run not found: {run_id}") from error

    def save_run(self, run: ResearchRun, expected_version: int) -> None:
        current = self.get_run(run.id)
        if current.version != expected_version:
            raise RuntimeError("research run version changed")
        self.runs[run.id] = run

    def list_runs(self, project_id: str) -> list[ResearchRun]:
        return sorted(
            (run for run in self.runs.values() if run.project_id == project_id),
            key=lambda run: (run.updated_at, run.created_at, run.id),
            reverse=True,
        )

    def verified_artifacts(self, project_id: str, artifact_ids: list[str]) -> list[dict[str, Any]]:
        return []
