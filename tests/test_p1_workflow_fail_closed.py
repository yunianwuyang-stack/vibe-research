"""P1.3 workflow fail-closed negative cases (P1-PS-001..005).

These tests pin production scientific honesty:
- nonzero compile cannot be success
- host scaffolds must preserve existing main.tex
- empty docx targets block format-check
- production catalog does not advertise host content scaffolds
- missing upstream primary artifacts fail closed
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from services import host_domain_builders as domain
from services import workflow_options
from services.workflow_engine import (
    HOST_CONTENT_SCAFFOLD_SKILLS,
    _HostStepRunner,
    _missing_upstream_primary_outputs,
    production_catalog_has_no_host_content_scaffolds,
    production_skill_catalog,
)


def test_compile_nonzero_not_success_even_if_pdf_exists(tmp_path: Path) -> None:
    """P1-PS-001 / REQ-P1-01: rc!=0 must not be treated as compile success."""
    pdf = tmp_path / "main.pdf"
    # Signature is (output, rc, combined_log); PDF must be >=500 bytes for success.
    pdf.write_bytes(b"%PDF" + b"0" * 600)
    assert _HostStepRunner._pdf_compile_success(pdf, 1, "fake log") is False
    assert _HostStepRunner._pdf_compile_success(pdf, 0, "ok") is True
    assert _HostStepRunner._pdf_compile_success(tmp_path / "missing.pdf", 0, "ok") is False


def test_fallback_host_paper_scaffold_preserves_main_tex(tmp_path: Path) -> None:
    """P1-PS-002 / REQ-P1-02: host paper scaffold must not overwrite manuscripts."""
    paper = tmp_path / "paper"
    paper.mkdir()
    marker = "%EXISTING_MAIN_CONTENT_MUST_STAY"
    body = (
        marker
        + "\n\\documentclass{article}\n\\begin{document}keep me\\end{document}\n"
    )
    main = paper / "main.tex"
    main.write_text(body, encoding="utf-8")
    before = main.read_text(encoding="utf-8")

    out = domain.build_paper_write(tmp_path, title="Preserve Me", language="en")
    after = main.read_text(encoding="utf-8")

    assert before == after
    assert marker in after
    assert out.get("preserved_main_tex") is True
    assert out.get("host_scaffold_wrote_main_tex") is False
    assert out.get("verification") == "all_unverified_host_scaffold"


def test_docx_check_without_targets_blocked(tmp_path: Path) -> None:
    """P1-PS-003 / REQ-P1-05: empty targets must block, not succeed."""
    result = asyncio.run(_HostStepRunner._run_docx_format_check(tmp_path, None))
    assert result["success"] is False
    assert result.get("status") == "blocked"
    assert result.get("root_cause") == "DOCX_CHECK_WITHOUT_TARGET"
    assert "no Markdown targets" in str(result.get("stderr", ""))


def test_production_catalog_has_no_host_content_scaffolds() -> None:
    """P1-PS-004 / REQ-P1-04: production catalog excludes host content scaffolds."""
    assert production_catalog_has_no_host_content_scaffolds() is True
    catalog = production_skill_catalog()
    assert catalog["host_content_scaffolds_excluded"] is True
    assert "novelty-check" in catalog["host_content_scaffold_skills"]
    for tmpl in catalog["templates"].values():
        for step in tmpl["steps"]:
            if step["skill_name"] in HOST_CONTENT_SCAFFOLD_SKILLS:
                assert step.get("host_scaffold_allowed") is False
                assert step.get("executor") == "agent_broker_required"

    ui_catalog = workflow_options.catalog()
    assert ui_catalog.get("production_catalog_has_no_host_content_scaffolds") is True
    assert "production" in ui_catalog
    for tmpl in ui_catalog["production"]["templates"].values():
        for step in tmpl["steps"]:
            if step["skill_name"] in HOST_CONTENT_SCAFFOLD_SKILLS:
                assert step.get("host_scaffold_allowed") is False


def test_required_upstream_missing_blocks_step(tmp_path: Path) -> None:
    """P1-PS-005 / REQ-P1-03: missing upstream primary artifacts fail closed."""

    class _SD:
        def __init__(self, skill_name: str) -> None:
            self.skill_name = skill_name

    missing_compile = _missing_upstream_primary_outputs(None, _SD("paper-compile"), tmp_path)
    assert "paper/main.tex" in missing_compile

    missing_write = _missing_upstream_primary_outputs(None, _SD("paper-write"), tmp_path)
    assert "PAPER_PLAN.md" in missing_write

    missing_bridge = _missing_upstream_primary_outputs(None, _SD("experiment-bridge"), tmp_path)
    assert missing_bridge

    main = tmp_path / "paper" / "main.tex"
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text("% ok\n", encoding="utf-8")
    assert _missing_upstream_primary_outputs(None, _SD("paper-compile"), tmp_path) == []
