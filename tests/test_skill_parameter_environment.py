"""Workflow UI options must reach skills as both SKILL_* and direct env aliases."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_skill_parameter_environment_exports_competition_and_academic_aliases():
    from services.claude_runner import _skill_parameter_environment

    env = _skill_parameter_environment(
        {
            "tools": "python",
            "problem_id": "A",
            "custom_title": "自拟题",
            "language": "en",
            "subject_domain": "literature",
            "degree_level": "undergraduate",
            "cn_en_ratio": "1:1",
            "target_paper_count": 20,
            "format_text": "正文小四宋体",
            "paper_type_target": "academic_zh",
            "paper_branch": "humanities",
            "rich_mode": True,
            "validation_mode": "fast",
            "min_figures": "auto",
            "min_tables": 4,
            "max_pages": 30,
            "competition": "cumcm",
        }
    )

    assert env["TOOLS"] == "python"
    assert env["PROBLEM_ID"] == "A"
    assert env["CUSTOM_TITLE"] == "自拟题"
    assert env["LANGUAGE"] == "en"
    assert env["SUBJECT_DOMAIN"] == "literature"
    assert env["DEGREE_LEVEL"] == "undergraduate"
    assert env["CN_EN_RATIO"] == "1:1"
    assert env["TARGET_PAPER_COUNT"] == "20"
    assert env["FORMAT_TEXT"] == "正文小四宋体"
    assert env["PAPER_TYPE_TARGET"] == "academic_zh"
    assert env["PAPER_BRANCH"] == "humanities"
    assert env["RICH_MODE"] == "1"
    assert env["VALIDATION_MODE"] == "fast"
    assert env["FAST_MODE"] == "1"
    assert env["MAX_PAGES"] == "30"
    assert env["MIN_TABLES"] == "4"
    assert env["COMPETITION"] == "cumcm"
    # "auto" is intentionally omitted so shell checks do not treat it as a bound.
    assert "MIN_FIGURES" not in env
    # Historical namespace remains available for third-party skills.
    assert env["SKILL_TOOLS"] == "python"
    assert env["SKILL_PROBLEM_ID"] == "A"


def test_workflow_config_exposes_humanities_language_and_readiness_gate():
    source = (ROOT / "frontend" / "src" / "workflow-config.tsx").read_text(encoding="utf-8")
    assert "中文（默认，引用 GB/T 7714）" in source
    assert "English（APA / Chicago / MLA）" in source
    assert "readiness" in source
    assert "disabled={busy || !readiness.ok}" in source
    assert '["undergraduate", "本科"]' in source
    assert 'degree_level' in source and "undergraduate" in source


def test_competition_config_exposes_tools_and_latex_output():
    source = (ROOT / "frontend" / "src" / "workflow-config.tsx").read_text(encoding="utf-8")
    assert 'label="建模工具"' in source
    assert '["python", "Python（默认）"]' in source
    assert '["matlab", "MATLAB"]' in source
    assert '["python+matlab", "Python + MATLAB"]' in source
    assert 'set("tools", value)' in source
    assert '["latex", "LaTeX（编译为 PDF）"]' in source



def test_thesis_proposal_degree_level_aliases_normalize():
    from services.workflow_options import normalize_workflow_params

    params = normalize_workflow_params("thesis_proposal", {"degree_level": "bachelor"})
    assert params["degree_level"] == "undergraduate"
    params = normalize_workflow_params("thesis_proposal", {"degree_level": "phd"})
    assert params["degree_level"] == "doctoral"
