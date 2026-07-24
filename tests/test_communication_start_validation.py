"""paper_slides/paper_poster can start from workspace paper/ artifacts."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_slides_and_poster_start_with_workspace_paper(tmp_path):
    import services.state_store as store
    import services.workflow_engine as engine
    import routers.workflows as workflows

    store.DB_PATH = tmp_path / "comm.db"
    engine.WORKSPACES_DIR = tmp_path / "workspaces"
    engine.WORKSPACES_DIR.mkdir()
    workflows.WORKSPACES_DIR = engine.WORKSPACES_DIR

    async def go():
        await store.init_db()
        tex = "\\documentclass{article}\\begin{document}Hi\\end{document}\n"
        pdf = b"%PDF-1.4\n%%EOF\n"
        for template in ("paper_slides", "paper_poster"):
            wf_id = await engine.create_new_workflow(template, f"Comm {template}", {}, False)
            ws = engine.WORKSPACES_DIR / wf_id
            paper = ws / "paper"
            paper.mkdir(parents=True, exist_ok=True)
            (paper / "main.tex").write_text(tex, encoding="utf-8")
            (paper / "main.pdf").write_bytes(pdf)
            await workflows._validate_start_inputs(wf_id)

            wf_id2 = await engine.create_new_workflow(template, f"Missing {template}", {}, False)
            try:
                await workflows._validate_start_inputs(wf_id2)
                raise AssertionError("expected missing-paper validation error")
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 400

    asyncio.run(go())
