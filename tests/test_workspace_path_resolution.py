"""Editor/artifacts must open the durable workspace_dir, not a stale process root."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_editor_follows_persisted_workspace_after_workspaces_dir_rebind(tmp_path, monkeypatch):
    import services.editor_ai as editor_ai
    import services.state_store as store
    import services.workflow_engine as engine
    from services.workspace_paths import resolve_workflow_workspace

    first_root = tmp_path / "用户A" / "workspaces"
    second_root = tmp_path / "用户B" / "workspaces"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)

    store.DB_PATH = tmp_path / "用户A" / "db" / "vibe.db"
    store.DB_PATH.parent.mkdir(parents=True)
    engine.WORKSPACES_DIR = first_root
    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", first_root)
    monkeypatch.setattr("config.WORKSPACES_DIR", first_root)
    monkeypatch.setattr("config.DB_PATH", store.DB_PATH)

    async def go():
        await store.init_db()
        wf_id = await engine.create_new_workflow(
            "idea_discovery",
            "持久工作区路径",
            {"topic": "workspace resolution"},
            False,
        )
        created = first_root / wf_id
        assert created.is_dir()
        # Simulate a later process whose WORKSPACES_DIR points elsewhere while
        # the ledger still records the original absolute workspace.
        monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", second_root)
        monkeypatch.setattr("config.WORKSPACES_DIR", second_root)
        engine.WORKSPACES_DIR = second_root

        resolved = resolve_workflow_workspace(wf_id)
        assert resolved == created.resolve()
        assert resolved != (second_root / wf_id).resolve()

        await editor_ai.save_file(wf_id, "paper/main.md", "# durable path\n")
        target = created / "paper" / "main.md"
        assert target.is_file()
        assert "durable path" in target.read_text(encoding="utf-8")
        # Must not create a shadow workspace under the rebound root.
        assert not (second_root / wf_id / "paper" / "main.md").exists()

        files = editor_ai.list_files(wf_id)
        assert any(item.get("path") == "paper/main.md" or item.get("path", "").endswith("paper/main.md") for item in files) or any(
            "main.md" in str(item) for item in files
        )

    asyncio.run(go())


def test_artifacts_router_uses_persisted_workspace(tmp_path, monkeypatch):
    import services.state_store as store
    import services.workflow_engine as engine
    from routers.artifacts import _workspace

    root = tmp_path / "workspaces"
    root.mkdir()
    store.DB_PATH = tmp_path / "db" / "vibe.db"
    store.DB_PATH.parent.mkdir(parents=True)
    engine.WORKSPACES_DIR = root
    monkeypatch.setattr("config.WORKSPACES_DIR", root)
    monkeypatch.setattr("config.DB_PATH", store.DB_PATH)

    async def go():
        await store.init_db()
        wf_id = await engine.create_new_workflow(
            "grad_project",
            "Artifacts path",
            {"note": "path"},
            False,
        )
        # Point default root at an empty tree; resolution must still hit ledger path.
        monkeypatch.setattr("config.WORKSPACES_DIR", tmp_path / "other")
        workspace = _workspace(wf_id)
        assert workspace == (root / wf_id).resolve()
        assert workspace.is_dir()

    asyncio.run(go())


def test_export_and_docx_follow_persisted_workspace(tmp_path, monkeypatch):
    """Export ZIP + DOCX must open the ledger workspace after WORKSPACES_DIR rebind."""
    import services.state_store as store
    import services.workflow_engine as engine
    from routers.workflows import _workflow_workspace_path
    from services.workspace_paths import resolve_workflow_workspace

    first_root = tmp_path / "用户导出A" / "workspaces"
    second_root = tmp_path / "用户导出B" / "workspaces"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)

    store.DB_PATH = tmp_path / "用户导出A" / "db" / "vibe.db"
    store.DB_PATH.parent.mkdir(parents=True)
    engine.WORKSPACES_DIR = first_root
    monkeypatch.setattr("config.WORKSPACES_DIR", first_root)
    monkeypatch.setattr("config.DB_PATH", store.DB_PATH)

    async def go():
        await store.init_db()
        wf_id = await engine.create_new_workflow(
            "idea_discovery",
            "导出路径",
            {"topic": "export path"},
            False,
        )
        created = first_root / wf_id
        paper = created / "paper"
        paper.mkdir(parents=True, exist_ok=True)
        (paper / "main.md").write_text("# export durable\n\n正文证据。\n", encoding="utf-8")

        monkeypatch.setattr("config.WORKSPACES_DIR", second_root)
        engine.WORKSPACES_DIR = second_root

        resolved = resolve_workflow_workspace(wf_id)
        assert resolved == created.resolve()
        via_router = _workflow_workspace_path(wf_id)
        assert via_router == created.resolve()
        assert (via_router / "paper" / "main.md").is_file()
        # Shadow path under rebound root must stay empty.
        assert not (second_root / wf_id).exists()

    asyncio.run(go())
