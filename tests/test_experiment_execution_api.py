from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException


async def _project(db_path: Path) -> str:
    import services.state_store as store
    import services.research_contracts as contracts
    import services.p5_research_design as p5

    store.DB_PATH = db_path
    await store.init_db()
    project_id = (await contracts.create_contract("Experiment", "Does treatment change outcome?", "numeric observations"))["id"]
    await p5.save_design(project_id, {"theoretical": False, "empirical": True, "falsifier": "null effect"}, "experimental_ml", {"baseline": "baseline", "ablation_plan": "ablation", "evaluation_metric": "score", "falsification_criteria": "null effect"}, "researcher")
    await p5.freeze_prior_art(project_id, "2026-07-19", {}, [{"title":"Prior A","source_url":"https://a.example/paper","similarities":"same","differences":"different","evidence_strength":"strong"},{"title":"Prior B","source_url":"https://b.example/paper","similarities":"same","differences":"different","evidence_strength":"strong"}], "researcher")
    await p5.save_protocol(project_id, {"estimand":"difference","outcome":"score","exposure":"treatment","baseline":"baseline","ablation_plan":"ablation","falsification_criteria":"null effect"}, "exploratory", "researcher")
    await p5.assess_ethics(project_id, {"subjects":"numeric observations","jurisdiction":"local","irb_status":"not_required","consent_status":"not_required","dua_status":"verified","license_status":"verified","pii_categories":[],"allowed_use":"research","retention_deletion":"delete after study"}, "researcher")
    return project_id


def test_experiment_executes_persists_and_replays(tmp_path, monkeypatch):
    import services.experiment_execution as execution
    import services.state_store as store

    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    monkeypatch.setattr(execution, "WORKSPACES_DIR", tmp_path / "workspaces")
    first = asyncio.run(execution.execute(project_id, {"control": [1, 2, 3], "treatment": [3, 4, 5], "seeds": 3, "metric": "score"}))
    assert first["status"] == "completed" and first["statistics"]["passed"] is True
    assert first["statistics"]["execution_evidence"] == {
        "requested_seed_count": 3,
        "observed_seed_count": 3,
        "ablation_executed": True,
        "status": "verified",
    }
    assert first["result"]["difference"] == pytest.approx(2.0)
    assert Path(first["manifest_path"]).is_file() and len(first["manifest_sha256"]) == 64
    async def artifact_status():
        db_handle = await store.get_db()
        try:
            row = await (await db_handle.execute(
                "SELECT status FROM research_artifacts WHERE project_id=? AND kind='experiment.result'",
                (project_id,),
            )).fetchone()
            return row["status"]
        finally:
            await db_handle.close()
    assert asyncio.run(artifact_status()) == "verified"
    restored = asyncio.run(execution.list_runs(project_id))
    assert restored[0]["id"] == first["id"] and restored[0]["result_sha256"] == first["result_sha256"]
    replayed = asyncio.run(execution.replay(first["id"]))
    assert replayed["reproduced"] is True and replayed["replay_of"] == first["id"]


def test_experiment_rejects_invalid_numbers_and_surfaces_timeout(tmp_path, monkeypatch):
    import services.experiment_execution as execution
    import services.state_store as store

    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    monkeypatch.setattr(execution, "WORKSPACES_DIR", tmp_path / "workspaces")
    with pytest.raises(HTTPException, match="NaN or infinity"):
        asyncio.run(execution.execute(project_id, {"control": [1, float("nan")], "treatment": [2, 3], "seeds": 3, "metric": "score"}))

    async def timed_out(self, task_id, command, cwd, timeout):
        return {"returncode": -1, "stdout": "", "stderr": "Process timed out after 0.01s"}

    monkeypatch.setattr(execution.ProcessSupervisor, "run", timed_out)
    failed = asyncio.run(execution.execute(project_id, {"control": [1, 2], "treatment": [2, 3], "seeds": 3, "metric": "score"}, timeout_seconds=.01))
    assert failed["status"] == "failed" and "timed out" in failed["failure_reason"]


def test_single_seed_result_is_retained_but_not_statistics_verified(tmp_path, monkeypatch):
    import services.experiment_execution as execution
    import services.state_store as store

    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    monkeypatch.setattr(execution, "WORKSPACES_DIR", tmp_path / "workspaces")
    result = asyncio.run(execution.execute(project_id, {"control": [1, 2], "treatment": [2, 3], "seeds": 1, "metric": "score"}))
    assert result["status"] == "completed" and result["statistics"]["passed"] is False
    assert "single seed" in result["statistics"]["issues"][0]
