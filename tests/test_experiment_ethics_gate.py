from __future__ import annotations

import asyncio
from pathlib import Path


async def _project(db_path: Path) -> str:
    import services.research_contracts as contracts
    import services.state_store as store
    store.DB_PATH = db_path
    await store.init_db()
    return (await contracts.create_contract("P6 rights", "Can protected data run?", "sensitive marker"))["id"]


def test_dataset_is_blocked_before_workspace_without_verified_rights(tmp_path, monkeypatch):
    import services.experiment_execution as execution
    import services.state_store as store
    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(execution, "WORKSPACES_DIR", workspace)
    result = asyncio.run(execution.execute(project_id, {
        "control": [90123, 90124], "treatment": [90125, 90126], "seeds": 2,
        "metric": "private-score", "dataset_ref": "dataset:restricted",
        "execution_purpose": "publication",
    }))
    assert result["status"] == "blocked"
    assert result.get("reason_codes") == ["consent_unverified"] or "ethics_or_data_rights_not_verified" in result.get("p5_gate", {}).get("findings", [])
    assert not workspace.exists()
    serialized = str(result)
    assert "90123" not in serialized and "private-score" not in serialized
