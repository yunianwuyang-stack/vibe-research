"""Full-pipeline terminal assurance must leave a durable workspace artifact."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_write_assurance_artifact_is_atomic_and_readable(tmp_path):
    from services.workflow_engine import _write_assurance_artifact

    workspace = tmp_path / "ws"
    workspace.mkdir()
    envelope = {
        "format_version": "assurance-envelope/v1",
        "status": "BLOCKED",
        "submission_ready": False,
        "gates": [{"id": "final_submission", "status": "BLOCKED"}],
        "verifier_version": "vibe-assurance/1.0",
    }
    path = _write_assurance_artifact(workspace, envelope)
    assert path == workspace / "ASSURANCE_ENVELOPE.json"
    assert path.is_file()
    assert not path.with_suffix(".json.tmp").exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["submission_ready"] is False
    assert loaded["status"] == "BLOCKED"
    assert loaded["verifier_version"] == "vibe-assurance/1.0"


def test_full_pipeline_assurance_blocks_without_project_and_persists(tmp_path):
    from services.workflow_engine import (
        _evaluate_full_pipeline_assurance,
        _write_assurance_artifact,
    )

    workspace = tmp_path / "pipeline"
    workspace.mkdir()

    async def go():
        envelope = await _evaluate_full_pipeline_assurance(
            {"project_id": "", "id": "wf-no-project"},
            workspace,
        )
        assert envelope["submission_ready"] is False
        assert envelope["status"] == "BLOCKED"
        assert envelope["findings"]
        path = _write_assurance_artifact(workspace, envelope)
        assert path.is_file()
        disk = json.loads(path.read_text(encoding="utf-8"))
        assert disk["submission_ready"] is False
        # Gate failure is an auditable product signal, not a silent pass.
        assert any(
            item.get("code") in {"missing_project", "assurance_evaluation_error", "missing_research_project"}
            or "project" in str(item.get("message", "")).lower()
            or "project" in str(item.get("code", "")).lower()
            for item in disk.get("findings", [])
        ) or disk["status"] == "BLOCKED"

    asyncio.run(go())


def test_full_pipeline_host_steps_skip_drawio_and_improvement(tmp_path):
    """Host offline path must drop improvement loop and skip drawio/html figures."""
    import tempfile

    from services.workflow_engine import _resolve_template, _runtime_skip_reason

    params = {
        "language": "en",
        "paper_branch": "general",
        "skip_drawio": True,
        "skip_improvement_loop": True,
    }
    tmpl = _resolve_template("full_pipeline", params, Path(tempfile.mkdtemp()))
    names = [step.skill_name for step in tmpl.sub_steps]
    assert "research-lit" in names
    assert "experiment-bridge" in names
    assert "paper-plan" in names
    assert "paper-write" in names
    assert "paper-compile" in names
    assert "auto-paper-improvement-loop" not in names
    assert "auto-paper-improvement-docx" not in names
    # drawio resolves to html engine by default; skip_drawio covers both at runtime
    figure_skills = [n for n in names if n in {"paper-figure-drawio", "paper-figure-html"}]
    for skill in figure_skills:
        reason = _runtime_skip_reason(skill, params)
        assert reason and "关闭" in reason
    assert _runtime_skip_reason("paper-write", params) is None
