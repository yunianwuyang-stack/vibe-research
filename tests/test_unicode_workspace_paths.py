"""Unicode workspace paths must survive create → artifact → archive flows."""
from __future__ import annotations

import asyncio
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_unicode_workspace_supports_create_artifact_and_safe_zip(tmp_path, monkeypatch):
    import services.state_store as store
    import services.workflow_engine as engine
    import services.editor_ai as editor_ai
    from services.safe_archive import extract_zip, safe_filename
    from services.docx_tool_loader import get_markdown_to_docx

    root = tmp_path / "Agent验收 空格" / "博士生-路径"
    root.mkdir(parents=True)
    store.DB_PATH = root / "unicode.db"
    engine.WORKSPACES_DIR = root / "workspaces"
    engine.WORKSPACES_DIR.mkdir()
    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", engine.WORKSPACES_DIR)
    monkeypatch.setattr(editor_ai, "RUNTIME_DRAWIO", ROOT / "runtime" / "draw.io")
    pandoc = ROOT / "runtime" / "pandoc" / "pandoc.exe"
    if pandoc.is_file():
        monkeypatch.setattr(editor_ai, "PANDOC_BIN", str(pandoc))

    async def go():
        await store.init_db()
        wf_id = await engine.create_new_workflow(
            "one_sentence_project",
            "Unicode 博士生路径验证",
            {"note": "中文与空格"},
            False,
        )
        workspace = engine.WORKSPACES_DIR / wf_id
        assert " " not in str(workspace) or workspace.is_dir()
        assert (workspace / "CLAUDE.md").is_file()
        content = (workspace / "CLAUDE.md").read_text(encoding="utf-8")
        assert "Unicode 博士生路径验证" in content

        paper = workspace / "paper"
        paper.mkdir(exist_ok=True)
        md = paper / "main.md"
        md.write_text("# Unicode 路径\n\n这是一条含中文与空格父目录的验证段落。\n", encoding="utf-8")
        converter = get_markdown_to_docx()
        assert converter is not None
        docx = paper / "main.docx"
        await asyncio.to_thread(converter, md, docx, None, workspace, "python")
        assert docx.is_file() and docx.stat().st_size > 1000

        compiled = await editor_ai.compile_paper(wf_id, source_md="")
        assert compiled["status"] == "completed", compiled
        assert (workspace / compiled["manifest"]["path"]).is_file()

        # Safe archive + filename rules remain valid under Unicode parents.
        archive_path = root / "资料包.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.write(docx, arcname="paper/main.docx")
            archive.writestr("说明.txt", "中文说明")
        extracted = root / "解压目录"
        names = extract_zip(archive_path, extracted)
        assert "paper/main.docx" in names
        assert (extracted / "paper" / "main.docx").is_file()
        assert safe_filename("报告 终稿.docx") == "报告 终稿.docx"

    asyncio.run(go())
