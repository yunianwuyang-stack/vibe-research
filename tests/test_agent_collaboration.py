"""Multi-agent collaboration: honest fail without credentials + durable report."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_collaboration_honest_fail_without_credentials_persists_report(tmp_path, monkeypatch):
    import services.state_store as store
    import services.research_contracts as contracts
    import services.agent_collaboration as collab
    import services.llm_client as llm

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    old_db = store.DB_PATH
    old_ws = collab.WORKSPACES_DIR
    store.DB_PATH = tmp_path / "collab.db"
    collab.WORKSPACES_DIR = workspace

    async def boom(agent: str, prompt: str, timeout: int = 300) -> str:
        raise Exception(f"未配置 {agent} 的 API 密钥，请先在设置页面配置")

    monkeypatch.setattr(llm, "call_llm", boom)

    async def go():
        await store.init_db()
        project = await contracts.create_contract(
            "Multi-agent study",
            "Can multi-agent collaboration fail honestly without keys?",
            "peer reviewed",
        )
        result = await collab.start(
            project["id"],
            "Coordinate executor, reviewer, and editor on dual-clean gate packaging",
            roles=["executor", "reviewer", "editor_ai"],
            cli_adapters=[],
            timeout_seconds=30,
        )
        assert result["status"] == "failed"
        assert result["report_path"]
        assert result["report_sha256"]
        assert len(result["steps"]) == 3
        assert all(step["status"] == "failed" for step in result["steps"])
        assert all(
            "密钥" in (step.get("error") or "")
            or "key" in (step.get("error") or "").lower()
            or "未配置" in (step.get("error") or "")
            for step in result["steps"]
        )
        report_path = workspace / project["id"] / result["report_path"]
        assert report_path.is_file()
        raw = report_path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == result["report_sha256"]
        document = json.loads(raw.decode("utf-8"))
        assert document["status"] == "failed"
        assert document["generator"].startswith("vibe.agent-collaboration")
        listed = await collab.list_collaborations(project["id"])
        assert listed and listed[0]["id"] == result["id"]

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        collab.WORKSPACES_DIR = old_ws


def test_collaboration_completes_when_roles_return_real_text(tmp_path, monkeypatch):
    import services.state_store as store
    import services.research_contracts as contracts
    import services.agent_collaboration as collab
    import services.llm_client as llm

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    old_db = store.DB_PATH
    old_ws = collab.WORKSPACES_DIR
    store.DB_PATH = tmp_path / "collab-ok.db"
    collab.WORKSPACES_DIR = workspace

    async def fake(agent: str, prompt: str, timeout: int = 300) -> str:
        return f"{agent} contribution for: {prompt[:40]}"

    monkeypatch.setattr(llm, "call_llm", fake)

    async def go():
        await store.init_db()
        project = await contracts.create_contract("Ok multi", "Does multi-agent complete?", "criteria")
        result = await collab.start(
            project["id"],
            "Build claim-evidence packaging with independent review",
            roles=["executor", "reviewer"],
            cli_adapters=[],
            timeout_seconds=20,
        )
        assert result["status"] == "completed"
        assert all(step["status"] == "completed" for step in result["steps"])
        assert all(step.get("output_sha256") for step in result["steps"])
        report_path = workspace / project["id"] / result["report_path"]
        assert report_path.is_file()
        assert hashlib.sha256(report_path.read_bytes()).hexdigest() == result["report_sha256"]

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        collab.WORKSPACES_DIR = old_ws
