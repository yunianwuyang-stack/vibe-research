"""Characterization tests for the canonical P2 research run engine/domain."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from domain import (
    ArtifactRef,
    AttemptStatus,
    GateStatus,
    RunStatus,
    TaskStatus,
    finish_current_task,
    new_run,
    retry_task,
    run_from_dict,
    run_to_dict,
    start_current_task,
    transition_run,
)
from domain import research_run as research_run_mod

HASH = "a" * 64
HASH_B = "b" * 64

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "backend" / "domain"
ADR_PATH = ROOT / "architecture" / "adr" / "0001-research-run-engine-migration.md"

FORBIDDEN_DOMAIN_IMPORTS = {
    "fastapi",
    "starlette",
    "sqlite3",
    "aiosqlite",
    "sqlalchemy",
    "httpx",
    "openai",
    "anthropic",
    "electron",
}


def test_adr_documents_dual_write_freeze_and_mapping():
    text = ADR_PATH.read_text(encoding="utf-8")
    assert "ResearchRunEngine" in text
    assert "dual-write" in text or "Dual-write" in text
    assert "LegacyWriteFrozen" in text
    assert "workflows" in text and "ResearchRun" in text
    assert "Deletion order" in text or "deletion order" in text.lower()


def test_domain_package_has_no_framework_or_provider_imports():
    offenders: list[str] = []
    for path in DOMAIN_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in FORBIDDEN_DOMAIN_IMPORTS:
                    offenders.append(f"{path.name}:{name}")
    assert offenders == []


def test_run_records_monotonic_events_and_retry_creates_new_attempt():
    run = new_run("project-1", (("analyze", ("evidence",)),))
    run = transition_run(run, RunStatus.RUNNING)
    run = start_current_task(run)
    first_id = run.task("analyze").current_attempt.id
    run = finish_current_task(
        run,
        input_data={"dataset": HASH},
        output_data={},
        artifacts=(),
        gate_passed=False,
        failure_reason="provider timeout",
    )
    run = retry_task(run, "analyze")
    run = transition_run(run, RunStatus.RUNNING)
    run = start_current_task(run)

    task = run.task("analyze")
    assert task.current_attempt.id != first_id
    assert task.current_attempt.number == 2
    assert task.attempts[0].status == AttemptStatus.BLOCKED
    assert [event.aggregate_version for event in run.events] == list(range(1, run.version + 1))


def test_illegal_transition_and_artifact_hash_fail_closed():
    run = new_run("project-1", (("analyze", ()),))
    with pytest.raises(ValueError, match="illegal run transition"):
        transition_run(run, RunStatus.COMPLETED)
    with pytest.raises(ValueError, match="SHA-256"):
        ArtifactRef("artifact", "table", "artifact://table", "not-a-hash", "1")


def test_successful_task_records_content_addressed_artifact_and_completes_run():
    run = transition_run(new_run("project-1", (("analyze", ("accepted",)),)), RunStatus.RUNNING)
    run = start_current_task(run)
    artifact = ArtifactRef("artifact-1", "table", "artifact://table", HASH, "table/v1", (HASH,))
    run = finish_current_task(
        run,
        input_data={"source": HASH},
        output_data={"rows": 3},
        artifacts=(artifact,),
        gate_passed=True,
    )
    assert run.status == RunStatus.COMPLETED
    assert run.artifacts == (artifact,)
    assert run.task("analyze").attempts[0].artifact_ids == (artifact.id,)


def test_dict_roundtrip_preserves_aggregate_identity_and_events():
    run = transition_run(new_run("project-9", (("t1", ("g1",)), ("t2", ()))), RunStatus.RUNNING)
    run = start_current_task(run)
    artifact = ArtifactRef("art-1", "note", "artifact://note", HASH_B, "note/v1")
    run = finish_current_task(
        run,
        input_data={"q": HASH},
        output_data={"ok": True},
        artifacts=(artifact,),
        gate_passed=True,
    )
    restored = run_from_dict(run_to_dict(run))
    assert restored.id == run.id
    assert restored.version == run.version
    assert restored.status == run.status
    assert restored.current_task == run.current_task
    assert len(restored.events) == len(run.events)
    assert restored.artifacts[0].sha256 == HASH_B


def test_gate_failure_blocks_run_and_marks_gate_failed():
    run = transition_run(new_run("project-2", (("analyze", ("evidence",)), ("write", ()))), RunStatus.RUNNING)
    run = start_current_task(run)
    run = finish_current_task(
        run,
        input_data={"dataset": HASH},
        output_data={},
        artifacts=(),
        gate_passed=False,
        failure_reason="missing corpus",
    )
    task = run.task("analyze")
    assert run.status == RunStatus.BLOCKED
    assert task.status == TaskStatus.BLOCKED
    assert task.gates[0].status == GateStatus.FAILED
    assert task.current_attempt.status == AttemptStatus.BLOCKED


def test_cancel_from_paused_is_terminal():
    run = new_run("project-3", (("analyze", ()),))
    run = transition_run(run, RunStatus.CANCELLED)
    assert run.status == RunStatus.CANCELLED
    with pytest.raises(ValueError, match="illegal run transition"):
        transition_run(run, RunStatus.RUNNING)


def test_finish_without_start_auto_creates_attempt_and_can_complete():
    """Current domain ABI auto-materializes an attempt on finish if missing.

    This is characterized intentionally so engine ports cannot silently change
    attempt identity semantics during the dual-write migration.
    """
    run = transition_run(new_run("project-4", (("analyze", ("g",)),)), RunStatus.RUNNING)
    assert run.task("analyze").current_attempt is None
    run = finish_current_task(
        run,
        input_data={"seed": HASH},
        output_data={"ok": True},
        artifacts=(),
        gate_passed=True,
    )
    task = run.task("analyze")
    assert task.current_attempt is not None
    assert task.current_attempt.status == AttemptStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED


def test_schema_version_constant_is_stable_for_migrations():
    assert research_run_mod.SCHEMA_VERSION.startswith("research-run/")


def test_old_to_new_mapping_surface_names_exist_in_domain_api():
    # Freeze the vocabulary the ADR maps from legacy workflow tables.
    for name in [
        "ResearchRun",
        "Task",
        "TaskAttempt",
        "Gate",
        "ArtifactRef",
        "RunEvent",
        "new_run",
        "transition_run",
        "start_current_task",
        "finish_current_task",
        "retry_task",
        "run_to_dict",
        "run_from_dict",
    ]:
        assert hasattr(research_run_mod, name)
