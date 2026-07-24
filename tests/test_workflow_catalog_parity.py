"""Frontend workflow catalog must expose the product-visible template surface."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
CONFIG = (ROOT / "frontend" / "src" / "workflow-config.tsx").read_text(encoding="utf-8")
ENGINE = (ROOT / "backend" / "services" / "workflow_engine.py").read_text(encoding="utf-8")


def _category_templates(category_id: str) -> list[str]:
    match = re.search(
        rf'id:\s*"{re.escape(category_id)}"[\s\S]*?templates:\s*\[([\s\S]*?)\],',
        MAIN,
    )
    assert match, f"missing template category: {category_id}"
    return re.findall(r'"([a-z0-9_]+)"', match.group(1))


def _engine_templates() -> set[str]:
    return set(re.findall(r'^\s{4}"([a-z0-9_]+)":\s*TemplateDef\(', ENGINE, re.M))


def test_academic_entry_matches_paper_writing_card():
    academic = _category_templates("academic")
    assert academic[0] == "paper_writing"
    assert academic == [
        "paper_writing",
        "thesis_proposal",
        "literature_review",
        "course_paper",
        "course_report",
    ]
    # Branches live inside the paper_writing configuration surface, not as
    # separate top-level academic cards.
    assert "paper_writing_zh" not in academic
    assert "nature_writing" not in academic
    assert "humanities_paper" not in academic


def test_competition_order_matches_product_calendar():
    expected = [
        "comp_tianfu",
        "comp_certcup",
        "comp_mathorcup",
        "comp_teddy",
        "comp_huadong",
        "comp_huazhong",
        "comp_wuyi",
        "comp_zhongqing",
        "comp_yangtze",
        "comp_stats",
        "comp_shuwei",
        "comp_diangong",
        "comp_liaoning",
        "comp_apmcm_zh",
        "comp_shenzhen",
        "comp_huashu",
        "comp_cumcm",
        "comp_huawei",
        "comp_mcm",
        "comp_shuwei_en",
        "comp_apmcm",
        "comp_certcup_en",
    ]
    assert _category_templates("competition") == expected


def test_remaining_categories_cover_assets_project_and_ip():
    assert _category_templates("research") == [
        "idea_discovery",
        "experiment_bridge",
        "auto_review",
        "full_pipeline",
    ]
    assert _category_templates("assets") == ["paper_from_assets"]
    assert _category_templates("communication") == ["paper_slides", "paper_poster"]
    assert _category_templates("one_sentence") == ["grad_project"]
    assert _category_templates("ip") == [
        "software_copyright",
        "copyright_material",
        "patent_disclosure",
    ]


def test_all_visible_templates_are_registered_in_engine():
    visible: list[str] = []
    for category in (
        "research",
        "academic",
        "competition",
        "assets",
        "communication",
        "one_sentence",
        "ip",
    ):
        visible.extend(_category_templates(category))
    # Internal paper-writing branches must remain engine-registered even when
    # they are not separate academic cards.
    for branch in ("paper_writing_zh", "nature_writing", "humanities_paper"):
        if branch not in visible:
            visible.append(branch)
    engine = _engine_templates()
    missing = [item for item in visible if item not in engine]
    assert not missing, f"UI templates missing from engine: {missing}"


def test_communication_templates_resolve_to_slides_and_poster_skills():
    import sys
    import tempfile
    from pathlib import Path as P

    sys.path.insert(0, str(ROOT / "backend"))
    from services.workflow_engine import TEMPLATES, _resolve_template
    from services.workflow_options import normalize_workflow_params

    assert "paper_slides" in TEMPLATES
    assert "paper_poster" in TEMPLATES
    slides = _resolve_template(
        "paper_slides",
        normalize_workflow_params("paper_slides", {}),
        P(tempfile.mkdtemp()),
    )
    poster = _resolve_template(
        "paper_poster",
        normalize_workflow_params("paper_poster", {}),
        P(tempfile.mkdtemp()),
    )
    assert [step.skill_name for step in slides.sub_steps] == ["paper-slides"]
    assert slides.sub_steps[0].primary_output == "slides/main.pdf"
    assert [step.skill_name for step in poster.sub_steps] == ["paper-poster"]
    assert poster.sub_steps[0].primary_output == "poster/main.pdf"
    assert "presentation.pptx" in " ".join(slides.sub_steps[0].output_files)
    assert "poster.pptx" in " ".join(poster.sub_steps[0].output_files)


def test_paper_writing_config_defaults_to_chinese_branch_and_exposes_selector():
    assert 'template === "paper_writing" ? "paper_writing_zh"' in CONFIG
    assert 'label="论文写作分支"' in CONFIG or "论文写作分支" in CONFIG
    assert '["general", "通用学术"]' in CONFIG
    assert '["nature", "Nature 顶刊"]' in CONFIG
    assert '["humanities", "人文社科"]' in CONFIG
    assert "paper_slides" in CONFIG
    assert "paper_poster" in CONFIG
    assert "会议幻灯片参数" in CONFIG
    assert "会议海报参数" in CONFIG
    assert "导出可编辑 PPTX" in CONFIG


def test_full_pipeline_defaults_to_english_writing_tail():
    """Oracle full_pipeline writing steps are English unless language=zh."""
    import sys
    import tempfile
    from pathlib import Path as P

    sys.path.insert(0, str(ROOT / "backend"))
    from services.workflow_engine import _resolve_template
    from services.workflow_options import normalize_workflow_params

    params = normalize_workflow_params("full_pipeline", {})
    assert params["language"] == "en"
    skills = [
        step.skill_name
        for step in _resolve_template("full_pipeline", params, P(tempfile.mkdtemp())).sub_steps
    ]
    assert "paper-plan" in skills
    assert "paper-write" in skills
    assert "paper-plan-zh" not in skills
    assert "paper-write-zh" not in skills


def test_paper_writing_branch_params_resolve_to_internal_skill_chains():
    """API clients may send paper_writing + paper_branch instead of concrete ids."""
    import sys
    import tempfile
    from pathlib import Path as P

    sys.path.insert(0, str(ROOT / "backend"))
    from services.workflow_engine import _resolve_template
    from services.workflow_options import normalize_workflow_params

    root = P(tempfile.mkdtemp())
    zh = [
        step.skill_name
        for step in _resolve_template(
            "paper_writing",
            normalize_workflow_params("paper_writing", {"language": "zh"}),
            root,
        ).sub_steps
    ]
    assert "paper-plan-zh" in zh
    assert "paper-write-zh" in zh

    nature = [
        step.skill_name
        for step in _resolve_template(
            "paper_writing",
            normalize_workflow_params("paper_writing", {"paper_branch": "nature", "language": "en"}),
            root,
        ).sub_steps
    ]
    assert "paper-write-nature" in nature
    assert "nature-figure" in nature

    humanities = [
        step.skill_name
        for step in _resolve_template(
            "paper_writing",
            normalize_workflow_params(
                "paper_writing",
                {
                    "paper_branch": "humanities",
                    "language": "zh",
                    "output_format": "docx",
                    "subject_domain": "literature",
                    "word_count_target": 8000,
                    "skip_figures": True,
                    "skip_analysis": True,
                    "skip_drawio": True,
                },
            ),
            root,
        ).sub_steps
    ]
    assert "humanities-plan" in humanities
    assert "humanities-write" in humanities
    assert "docx-export" in humanities

def test_production_catalog_marks_paper_write_as_unverified_host_scaffold():
    """paper-write may exist as offline host scaffold only with honesty marker."""
    import re
    from pathlib import Path
    from services import host_domain_builders as builders

    host_src = Path(__file__).resolve().parents[1] / "backend" / "services" / "workflow_engine.py"
    text = host_src.read_text(encoding="utf-8")
    m = re.search(r"host_steps\s*=\s*\{([\s\S]*?)\}", text)
    assert m is not None
    assert "paper-write" in m.group(1)
    builder_src = Path(builders.__file__).read_text(encoding="utf-8")
    assert "all_unverified_host_scaffold" in builder_src
    assert hasattr(builders, "build_paper_write")

