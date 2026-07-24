"""Workspace artifact listing and competition LaTeX asset staging."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_list_artifacts_includes_workspace_deliverables(tmp_path, monkeypatch):
    from routers import artifacts as artifacts_router

    wf_id = "artifact01"
    workspace = tmp_path / wf_id
    (workspace / "paper").mkdir(parents=True)
    (workspace / "paper" / "main.pdf").write_bytes(b"%PDF-1.4 test" + b"0" * 600)
    (workspace / "uploads").mkdir()
    (workspace / "uploads" / "input.txt").write_text("hello", encoding="utf-8")
    (workspace / "_tmp").mkdir()
    (workspace / "_tmp" / "noise.log").write_text("skip", encoding="utf-8")

    monkeypatch.setattr(
        artifacts_router,
        "resolve_workflow_workspace",
        lambda workflow_id, require_exists=True: workspace,
    )

    result = asyncio.run(artifacts_router.list_artifacts(wf_id))
    paths = {item["path"] for item in result}
    assert "paper/main.pdf" in paths
    assert "uploads/input.txt" in paths
    assert "_tmp/noise.log" not in paths


def test_stage_competition_latex_assets_copies_missing_cls(tmp_path, monkeypatch):
    import services.workflow_engine as workflow_engine

    skills = tmp_path / "skills"
    template_dir = skills / "comp-paper-zh" / "templates" / "huawei"
    template_dir.mkdir(parents=True)
    (template_dir / "gmcmthesis.cls").write_text("% cls", encoding="utf-8")
    (template_dir / "logo.pdf").write_bytes(b"%PDF")
    (template_dir / "main.tex").write_text("should-not-overwrite", encoding="utf-8")

    workspace = tmp_path / "ws"
    paper = workspace / "paper"
    paper.mkdir(parents=True)
    slash = chr(92)
    (paper / "main.tex").write_text(slash + "documentclass{gmcmthesis}" + chr(10), encoding="utf-8")

    monkeypatch.setattr(workflow_engine, "SKILLS_DIR", skills)
    staged = workflow_engine._HostStepRunner._stage_competition_latex_assets(
        workspace,
        template="comp_huawei",
        skill_name="comp-compile-zh",
        params={"competition": "huawei"},
    )
    assert "gmcmthesis.cls" in staged
    assert (paper / "gmcmthesis.cls").is_file()
    assert (paper / "logo.pdf").is_file()
    assert (paper / "main.tex").read_text(encoding="utf-8").startswith(slash + "documentclass")


def test_sanitize_latex_source_fixes_hyperref_backticks_and_texttt():
    import services.workflow_engine as workflow_engine

    host = workflow_engine._HostStepRunner
    sample = (
        "\\documentclass{mcmthesis}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage[hidelinks]{hyperref}\n"
        "\\usepackage{listings}\n"
        "See `main.py` and \\texttt{constraint_audit.py}.\n"
        "\\usepackage[super]{gbt7714}\n"
    )
    cleaned = host._sanitize_latex_source_text(sample)
    assert cleaned.count("\\usepackage{hyperref}") == 1
    assert "\\hypersetup{hidelinks}" in cleaned
    assert "\\texttt{main.py}" in cleaned
    assert "\\texttt{constraint\\_audit.py}" in cleaned
    assert "\\usepackage{gbt7714}" in cleaned


def test_pdf_compile_success_rejects_nonzero_exit_even_with_pdf(tmp_path):
    import services.workflow_engine as workflow_engine

    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"0" * 800)
    host = workflow_engine._HostStepRunner
    # P1 fail-closed: artifact existence must not mask nonzero compiler exit.
    assert not host._pdf_compile_success(
        pdf, 1, "Missing $ inserted.\nOutput written on main.pdf (12 pages)."
    )
    assert not host._pdf_compile_success(
        tmp_path / "missing.pdf",
        1,
        "Fatal error occurred, no output PDF file produced!",
    )
    assert host._pdf_compile_success(pdf, 0, "Output written on main.pdf (12 pages).")


def test_docx_format_check_without_target_is_blocked(tmp_path):
    import asyncio
    import services.workflow_engine as workflow_engine

    host = workflow_engine._HostStepRunner
    result = asyncio.run(host._run_docx_format_check(tmp_path))
    assert result["success"] is False
    assert result.get("returncode") == 2
    assert result.get("root_cause") == "DOCX_CHECK_WITHOUT_TARGET"
    report = tmp_path / "DOCX_FORMAT_CHECK_REPORT.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "blocked" in text.lower()
    assert "不得记 success" in text


def test_apply_docx_columns_is_best_effort_without_python_docx(tmp_path, monkeypatch):
    import services.workflow_engine as workflow_engine

    out = tmp_path / "paper.docx"
    out.write_bytes(b"PK" + b"0" * 600)

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("forced missing python-docx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    # Must not raise — column styling is cosmetic.
    workflow_engine._HostStepRunner._apply_docx_columns(out, "double")
    assert out.is_file()


def test_compile_failure_preserves_main_tex(tmp_path):
    """Nonzero compile must fail closed and leave paper/main.tex untouched."""
    import asyncio
    import services.workflow_engine as workflow_engine

    workspace = tmp_path / "ws"
    paper = workspace / "paper"
    paper.mkdir(parents=True)
    main_tex = paper / "main.tex"
    original = "\\documentclass{article}\\begin{document}hello\\end{document}\n"
    main_tex.write_text(original, encoding="utf-8")
    # Stale/broken PDF must not flip success when compiler returns nonzero.
    (paper / "main.pdf").write_bytes(b"%PDF-1.4 " + b"0" * 800)

    async def _fake_run(cmd, cwd=None, env=None):
        return 1, "", "Emergency stop.\n! Missing $ inserted.\n"

    host = workflow_engine._HostStepRunner
    # paper-compile uses _run_process; monkeypatch the classmethod.
    host._run_process = classmethod(lambda cls, *a, **k: _fake_run(*a, **k))  # type: ignore[method-assign]

    result = asyncio.run(host._run_paper_compile(workspace, skill_name="paper-compile"))
    assert result["success"] is False
    assert result.get("root_cause") == "PDF_COMPILE_NONZERO_EXIT"
    assert main_tex.read_text(encoding="utf-8") == original


def test_required_upstream_missing_blocks_without_success(tmp_path):
    """Missing upstream primary outputs must surface for paper-compile."""
    import services.workflow_engine as workflow_engine

    class _Step:
        skill_name = "paper-compile"
        display_name = "Paper Compile"
        primary_outputs = ["paper/main.pdf"]

    class _Tmpl:
        sub_steps = []

    workspace = tmp_path / "ws"
    workspace.mkdir()
    # No paper/main.tex → upstream missing for paper-compile.
    missing = workflow_engine._missing_upstream_primary_outputs(
        _Tmpl(), _Step(), workspace
    )
    assert missing
    assert any("paper/main.tex" in item for item in missing)
    # Satisfied when artifact exists.
    paper = workspace / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("x", encoding="utf-8")
    assert workflow_engine._missing_upstream_primary_outputs(_Tmpl(), _Step(), workspace) == []

