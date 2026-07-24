"""P2.2 ResearchRunEngine ports isolation + fail-closed concurrency tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from domain.research_run import ArtifactRef, RunStatus, TaskStatus
from services.research_run_engine import ResearchRunEngine
from services.research_run_ports import (
    ArtifactIntegrityError,
    InMemoryArtifactStore,
    InMemoryEventLog,
    InMemoryRunRepository,
    StaleRunVersion,
)

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "backend" / "domain"
PORTS = ROOT / "backend" / "services" / "research_run_ports.py"
ENGINE = ROOT / "backend" / "services" / "research_run_engine.py"
HASH = "c" * 64


def _engine() -> ResearchRunEngine:
    return ResearchRunEngine(
        repository=InMemoryRunRepository(),
        artifacts=InMemoryArtifactStore(),
        events=InMemoryEventLog(),
    )


def test_domain_modules_do_not_import_services_or_ports():
    offenders: list[str] = []
    for path in DOMAIN_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                if mod == "services" or mod.startswith("services.") or "research_run_ports" in mod:
                    offenders.append(f"{path.name}:from {mod}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "services" or alias.name.startswith("services."):
                        offenders.append(f"{path.name}:import {alias.name}")
    assert offenders == []


def test_engine_and_ports_exist_as_application_layer():
    assert PORTS.exists()
    assert ENGINE.exists()
    ports_src = PORTS.read_text(encoding="utf-8")
    engine_src = ENGINE.read_text(encoding="utf-8")
    for token in ["RunRepository", "ArtifactStore", "EventLog", "Clock", "IdFactory", "StaleRunVersion"]:
        assert token in ports_src
    assert "class ResearchRunEngine" in engine_src
    assert "expected_version" in engine_src


def test_create_start_finish_happy_path_projects_events():
    eng = _engine()
    run = eng.create_run("proj-a", [("analyze", ("evidence",)), ("write", ())])
    assert run.status == RunStatus.PAUSED
    assert run.version >= 1
    run = eng.start_task(run.id, expected_version=run.version)
    assert run.status == RunStatus.RUNNING
    assert run.task("analyze").status == TaskStatus.RUNNING
    art = eng.put_artifact(b"hello-evidence", content_type="text/plain")
    run = eng.finish_task(
        run.id,
        expected_version=run.version,
        input_data={"src": art.sha256},
        output_data={"rows": 1},
        artifacts=(art,),
        gate_passed=True,
    )
    assert run.current_task == "write"
    assert eng.events.list(run.id)
    assert all(int(e["aggregate_version"]) >= 1 for e in eng.events.list(run.id))


def test_stale_version_fail_closed_on_start():
    eng = _engine()
    run = eng.create_run("proj-b", [("analyze", ())])
    with pytest.raises(StaleRunVersion):
        eng.start_task(run.id, expected_version=run.version - 1 if run.version else -1)
    # actual version still works
    run2 = eng.start_task(run.id, expected_version=run.version)
    assert run2.version > run.version


def test_missing_artifact_blob_fail_closed():
    eng = _engine()
    run = eng.create_run("proj-c", [("analyze", ("g",))])
    run = eng.start_task(run.id, expected_version=run.version)
    ghost = ArtifactRef("ghost", "blob", "memory://ghost", HASH, "artifact/v1")
    with pytest.raises(ArtifactIntegrityError):
        eng.finish_task(
            run.id,
            expected_version=run.version,
            input_data={},
            output_data={},
            artifacts=(ghost,),
            gate_passed=True,
        )


def test_retry_after_gate_failure_creates_new_attempt_via_engine():
    eng = _engine()
    run = eng.create_run("proj-d", [("analyze", ("g",))])
    run = eng.start_task(run.id, expected_version=run.version)
    run = eng.finish_task(
        run.id,
        expected_version=run.version,
        input_data={"x": 1},
        output_data={},
        artifacts=(),
        gate_passed=False,
        failure_reason="gate failed",
    )
    assert run.status == RunStatus.BLOCKED
    first_attempt = run.task("analyze").attempts[0].id
    run = eng.retry_task(run.id, "analyze", expected_version=run.version)
    run = eng.start_task(run.id, expected_version=run.version)
    assert run.task("analyze").current_attempt.id != first_attempt
    assert run.task("analyze").current_attempt.number == 2


def test_repository_save_optimistic_lock():
    repo = InMemoryRunRepository()
    eng = ResearchRunEngine(repository=repo, artifacts=InMemoryArtifactStore(), events=InMemoryEventLog())
    run = eng.create_run("proj-e", [("t", ())])
    # concurrent writer with stale expected version
    with pytest.raises(StaleRunVersion):
        mutated = eng.start_task(run.id, expected_version=run.version)
        # pretend another client still has old version
        eng.start_task(run.id, expected_version=run.version)
