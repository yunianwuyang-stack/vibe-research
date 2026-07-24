from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


async def _project(db_path: Path) -> str:
    import services.research_contracts as contracts
    import services.state_store as store
    store.DB_PATH = db_path
    await store.init_db()
    return (await contracts.create_contract("P6 profiles", "Can execution be verified?", "authorized corpus"))["id"]


def test_math_execution_never_promotes_llm_only(tmp_path, monkeypatch):
    import services.scientific_execution as scientific
    import services.state_store as store
    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    monkeypatch.setattr(scientific, "WORKSPACES_DIR", tmp_path / "workspaces")
    result = asyncio.run(scientific.execute_math(project_id, {
        "claim": "x = x", "verifier": "llm", "artifact": "looks valid", "replayable": True,
    }))
    assert result["status"] == "unverified"
    assert Path(result["receipt_path"]).is_file()


def test_formal_math_requires_replayable_artifact_and_counterexample_refutes(tmp_path, monkeypatch):
    import services.scientific_execution as scientific
    import services.state_store as store
    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    monkeypatch.setattr(scientific, "WORKSPACES_DIR", tmp_path / "workspaces")
    proved = asyncio.run(scientific.execute_math(project_id, {
        "claim": "x = x", "verifier": "lean", "artifact": "proof", "replayable": True,
    }))
    assert proved["status"] == "proved"
    refuted = asyncio.run(scientific.execute_math(project_id, {
        "claim": "x > x", "verifier": "lean", "artifact": "proof", "replayable": True,
        "counterexample": {"x": 1},
    }))
    assert refuted["status"] == "refuted"


def test_qualitative_admission_rejects_generated_participants(tmp_path, monkeypatch):
    import services.scientific_execution as scientific
    import services.state_store as store
    db = tmp_path / "vibe.db"
    project_id = asyncio.run(_project(db))
    store.DB_PATH = db
    monkeypatch.setattr(scientific, "WORKSPACES_DIR", tmp_path / "workspaces")
    payload = {"source_uri": "https://example.test/open-corpus", "source_sha256": "a" * 64,
        "rights": {"license": "CC-BY", "allowed_use": "research", "retention": "permanent"},
        "coding_scheme_version": "v1", "negative_cases": ["case-1"],
        "reflexivity_note": "Researcher position recorded", "generated_participants": True}
    with pytest.raises(ValueError, match="fictional participant"):
        asyncio.run(scientific.admit_qualitative(project_id, payload))
    payload["generated_participants"] = False
    admitted = asyncio.run(scientific.admit_qualitative(project_id, payload))
    assert admitted["status"] == "accepted" and len(admitted["lineage_sha256"]) == 64
