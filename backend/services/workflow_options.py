"""Workflow configuration contract shared by the API and execution engine.

The desktop UI exposes many template-specific controls.  Keeping their defaults
and validation here prevents a visually selected option from becoming an
untyped, ignored value in ``workflows.params``.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import HTTPException


COMPETITIONS: dict[str, dict[str, Any]] = {
    "comp_tianfu": {"label": "天府杯", "language": "zh", "pages": 30, "month": "3月"},
    "comp_certcup": {"label": "认证杯", "language": "zh", "pages": 35, "month": "4-5月"},
    "comp_mathorcup": {"label": "MathorCup", "language": "zh", "pages": 30, "month": "4月"},
    "comp_teddy": {"label": "泰迪杯", "language": "zh", "pages": 40, "month": "4月"},
    "comp_huadong": {"label": "华东杯", "language": "zh", "pages": 30, "month": "4-5月"},
    "comp_huazhong": {"label": "华中杯", "language": "zh", "pages": 30, "month": "4-5月"},
    "comp_wuyi": {"label": "五一杯", "language": "zh", "pages": 30, "month": "5月"},
    "comp_zhongqing": {"label": "中青杯", "language": "zh", "pages": 30, "month": "5月"},
    "comp_yangtze": {"label": "长三角", "language": "zh", "pages": 30, "month": "5月"},
    "comp_stats": {"label": "统计建模大赛", "language": "zh", "pages": 30, "month": "5月"},
    "comp_shuwei": {"label": "数维杯", "language": "zh", "pages": 30, "month": "5月"},
    "comp_diangong": {"label": "电工杯", "language": "zh", "pages": 30, "month": "5-6月"},
    "comp_liaoning": {"label": "辽宁省/东三省", "language": "zh", "pages": 30, "month": "6月"},
    "comp_apmcm_zh": {"label": "亚太赛中文 (APMCM)", "language": "zh", "pages": 25, "month": "6月"},
    "comp_shenzhen": {"label": "深圳杯", "language": "zh", "pages": 30, "month": "7-9月"},
    "comp_huashu": {"label": "华数杯", "language": "zh", "pages": 30, "month": "8月"},
    "comp_cumcm": {"label": "国赛 (CUMCM)", "language": "zh", "pages": 30, "month": "9月"},
    "comp_huawei": {"label": "华为杯", "language": "zh", "pages": 50, "month": "9月"},
    "comp_mcm": {"label": "美赛 (MCM/ICM)", "language": "en", "pages": 25, "month": "2月"},
    "comp_shuwei_en": {"label": "数维杯国际赛", "language": "en", "pages": 25, "month": "11月"},
    "comp_apmcm": {"label": "亚太 (APMCM)", "language": "en", "pages": 25, "month": "11月"},
    "comp_certcup_en": {"label": "小美赛 (认证杯国际)", "language": "en", "pages": 25, "month": "12月"},
}

ALIASES = {
    "dev": "grad_project",  # legacy one-sentence project card id
    # software_copyright and copyright_material are distinct IP products:
    # inventory four-pack from real code vs form/manual pack. Do not collapse.
}

COMMON_DEFAULTS: dict[str, Any] = {
    "skip_improvement_loop": True,
}

PAPER_DEFAULTS: dict[str, Any] = {
    **COMMON_DEFAULTS,
    "language": "zh",
    "output_format": "pdf",
    "paper_type": "journal",
    "column_layout": "double",
    "max_pages": 15,
    "figure_style": "default",
    "outline_mode": "auto",
    "skip_figures": False,
    "skip_analysis": False,
    "skip_drawio": False,
    "flowchart_engine": "html",
}

DEFAULTS: dict[str, dict[str, Any]] = {
    "idea_discovery": deepcopy(COMMON_DEFAULTS),
    "experiment_bridge": deepcopy(COMMON_DEFAULTS),
    # Oracle full_pipeline writing tail is English unless the user overrides.
    "full_pipeline": {**PAPER_DEFAULTS, "language": "en", "paper_branch": "general", "TARGET_VENUE": "ICLR"},
    "paper_writing": {**PAPER_DEFAULTS, "language": "en", "TARGET_VENUE": "ICLR", "max_pages": 9},
    "paper_writing_zh": deepcopy(PAPER_DEFAULTS),
    "nature_writing": {**PAPER_DEFAULTS, "language": "en", "figure_style": "nature"},
    "humanities_paper": {
        **COMMON_DEFAULTS,
        "output_format": "docx",
        "language": "zh",
        "subject_domain": "literature",
        "word_count_target": 8000,
        "skip_figures": True,
        "skip_analysis": True,
        "skip_drawio": True,
        "flowchart_engine": "html",
    },
    "thesis_proposal": {**COMMON_DEFAULTS, "language": "zh", "degree_level": "master", "output_format": "docx", "skip_drawio": False, "flowchart_engine": "html"},
    "literature_review": {**COMMON_DEFAULTS, "language": "zh", "output_format": "docx", "target_paper_count": 20, "cn_en_ratio": "1:1"},
    "course_paper": {**COMMON_DEFAULTS, "language": "zh", "output_format": "docx", "subject_domain": "cs", "word_count_target": 8000, "skip_figures": True, "skip_analysis": True, "skip_drawio": False, "flowchart_engine": "html"},
    "course_report": {**COMMON_DEFAULTS, "language": "zh", "output_format": "docx", "subject_domain": "cs", "word_count_target": 10000, "skip_figures": True, "skip_analysis": True, "skip_drawio": False, "flowchart_engine": "html"},
    "paper_from_assets": {**COMMON_DEFAULTS, "paper_type_target": "academic_zh", "output_format": "pdf", "language": "zh", "flowchart_engine": "html", "figure_style": "default"},
    "paper_slides": {
        **COMMON_DEFAULTS,
        "language": "en",
        "output_format": "pdf",
        "talk_minutes": 12,
        "aspect_ratio": "16:9",
        "latex_engine": "pdflatex",
        "include_speaker_notes": True,
        "include_pptx": True,
    },
    "paper_poster": {
        **COMMON_DEFAULTS,
        "language": "en",
        "output_format": "pdf",
        "poster_size": "A0",
        "orientation": "landscape",
        "latex_engine": "pdflatex",
        "include_pptx": True,
        "include_svg": True,
    },
    "auto_review": {**COMMON_DEFAULTS, "output_format": "markdown", "language": "zh", "max_rounds": 4, "target_score": 6},
    "grad_project": {
        **COMMON_DEFAULTS,
        "project_type": "fullstack",
        "tech_frontend": "React",
        "tech_backend": "FastAPI",
        "tech_db": "SQLite",
        "tech_lang": "Python",
        "design_style": "auto",
        "feature_requirements": "",
        "skip_report": True,
    },
    "one_sentence_project": {
        **COMMON_DEFAULTS,
        "project_type": "fullstack",
        "tech_frontend": "React",
        "tech_backend": "FastAPI",
        "tech_db": "SQLite",
        "tech_lang": "Python",
        "design_style": "auto",
        "feature_requirements": "",
        "skip_report": True,
    },
    "copyright_material": {**COMMON_DEFAULTS, "software_version": "V1.0"},
    "software_copyright": {**COMMON_DEFAULTS, "software_version": "V1.0"},
    "patent_disclosure": deepcopy(COMMON_DEFAULTS),
}
for _template, _competition in COMPETITIONS.items():
    DEFAULTS[_template] = {
        **COMMON_DEFAULTS,
        "competition": _template.removeprefix("comp_"),
        "language": _competition["language"],
        "max_pages": _competition["pages"],
        "output_format": "pdf",
        "flowchart_engine": "html",
        "rich_mode": False,
        "tools": "python",
        "min_figures": "auto",
        "min_tables": "auto",
        "min_models": "auto",
        "figure_style": "default",
        "validation_mode": "strict",
        "require_competition_input": _template != "comp_stats",
    }


ENUMS: dict[str, set[str]] = {
    "language": {"zh", "en"},
    "output_format": {"pdf", "docx", "markdown", "latex"},
    "flowchart_engine": {"html", "drawio"},
    "figure_style": {"default", "nature"},
    "validation_mode": {"strict", "fast"},
    "paper_type": {"bachelor", "master", "journal"},
    "column_layout": {"single", "double"},
    "outline_mode": {"auto", "input", "upload"},
    "paper_type_target": {"academic_zh", "academic_en", "competition", "course", "nature"},
    "paper_branch": {"general", "nature", "humanities"},
    "subject_domain": {"cs", "humanities", "economics", "engineering", "literature", "history", "philosophy", "sociology", "communication", "cultural_studies", "education", "law", "art", "politics"},
    "project_type": {"fullstack", "frontend", "cli", "script"},
    "design_style": {"auto", "minimal", "tech", "colorful", "elegant", "retro", "custom"},
    "TARGET_VENUE": {"ICLR", "NeurIPS", "ICML"},
    "aspect_ratio": {"16:9", "4:3"},
    "poster_size": {"A0", "A1"},
    "orientation": {"landscape", "portrait"},
    "latex_engine": {"pdflatex", "xelatex"},
}

BOOL_FIELDS = {
    "skip_improvement_loop", "skip_report", "skip_figures", "skip_analysis",
    "skip_drawio", "rich_mode", "user_outline", "has_uploaded_materials",
    "require_competition_input", "include_speaker_notes", "include_pptx",
    "include_svg",
}
INT_RANGES = {
    "max_pages": (1, 200),
    "target_paper_count": (1, 500),
    "word_count_target": (1000, 200000),
    "max_rounds": (1, 12),
    "target_score": (1, 10),
    "min_figures": (0, 200),
    "min_tables": (0, 100),
    "min_models": (0, 50),
    "talk_minutes": (3, 60),
}
TEXT_FIELDS = {
    "custom_requirements", "format_text", "user_outline_text", "problem_id",
    "custom_title", "problem_statement", "supplemental_notes", "template_profile",
    "research_question", "inclusion_criteria", "software_name", "software_version",
    "case_name", "design_style_custom", "feature_requirements", "tech_frontend",
    "tech_backend", "tech_db", "tech_lang", "tools", "degree_level", "cn_en_ratio",
}
LIST_FIELDS = {"template_files", "input_groups"}


def _invalid(field: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"工作流参数 {field} {message}")


def _normalize_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    limit = 50_000 if field in {"custom_requirements", "user_outline_text", "problem_statement"} else 10_000
    if len(text) > limit:
        raise _invalid(field, f"长度不能超过 {limit} 个字符")
    return text


def _canonical_paper_template(template: str, values: dict[str, Any] | None) -> str:
    """Map paper_writing + branch/language onto the internal template id."""
    if template != "paper_writing":
        return template
    raw = values or {}
    branch = str(raw.get("paper_branch") or "").strip().lower()
    language = str(raw.get("language") or "").strip().lower()
    if branch == "nature":
        return "nature_writing"
    if branch == "humanities":
        return "humanities_paper"
    if language == "zh":
        return "paper_writing_zh"
    return "paper_writing"


def normalize_workflow_params(template: str, values: dict[str, Any] | None) -> dict[str, Any]:
    """Apply template defaults and validate every UI-controlled parameter."""
    raw = values or {}
    template = str(template or "").strip()
    template = ALIASES.get(template, template)
    template = _canonical_paper_template(template, raw if isinstance(raw, dict) else None)
    if template not in DEFAULTS:
        raise HTTPException(status_code=422, detail=f"未知工作流模板: {template}")
    if values is not None and not isinstance(values, dict):
        raise HTTPException(status_code=422, detail="params 必须是对象")
    result = deepcopy(DEFAULTS[template])
    if len(raw) > 120:
        raise HTTPException(status_code=422, detail="工作流参数过多")
    for field, value in raw.items():
        if field in BOOL_FIELDS:
            if not isinstance(value, bool):
                raise _invalid(field, "必须是布尔值")
            result[field] = value
        elif field in ENUMS:
            normalized = str(value).strip()
            if normalized not in ENUMS[field]:
                raise _invalid(field, f"必须是 {', '.join(sorted(ENUMS[field]))} 之一")
            result[field] = normalized
        elif field in INT_RANGES:
            if value == "auto" and field in {"min_figures", "min_tables", "min_models"}:
                result[field] = "auto"
                continue
            if isinstance(value, bool):
                raise _invalid(field, "必须是整数")
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise _invalid(field, "必须是整数") from exc
            low, high = INT_RANGES[field]
            if not low <= number <= high:
                raise _invalid(field, f"必须在 {low} 到 {high} 之间")
            result[field] = number
        elif field in TEXT_FIELDS:
            result[field] = _normalize_text(value, field)
        elif field == "template_file":
            result[field] = _normalize_text(value, field)
        elif field in LIST_FIELDS:
            if not isinstance(value, list) or len(value) > 200:
                raise _invalid(field, "必须是最多 200 项的数组")
            result[field] = [str(item).strip() for item in value if str(item).strip()]
        else:
            # Preserve extension parameters used by installed skills, but keep
            # them JSON-safe and bounded rather than silently discarding them.
            if isinstance(value, str):
                result[field] = _normalize_text(value, field)
            elif isinstance(value, (bool, int, float)) or value is None:
                result[field] = value
            elif isinstance(value, list) and len(value) <= 200:
                result[field] = value
            elif isinstance(value, dict) and len(value) <= 100:
                result[field] = value
            else:
                raise _invalid(field, "包含不支持的值")

    # Closing figures usually implies no analysis plot pipeline. Explicit
    # skip_analysis always wins so paper_from_assets can gap-fill RESULTS
    # without forcing figure skills (Claude-only paper-figure is not host).
    if result.get("skip_figures") and "skip_analysis" not in raw:
        result["skip_analysis"] = True
    if result.get("skip_drawio"):
        result.pop("flowchart_engine", None)
    if result.get("output_format") == "docx" and result.get("paper_type") != "journal":
        result["column_layout"] = "single"
    if template in COMPETITIONS:
        result["competition"] = template.removeprefix("comp_")
        result["language"] = COMPETITIONS[template]["language"]
    # Keep thesis-proposal skill vocabulary stable: UI historically used
    # bachelor/master/doctoral while SKILL.md reads undergraduate/master/doctoral.
    if template == "thesis_proposal":
        degree = str(result.get("degree_level") or "master").strip().lower()
        result["degree_level"] = {
            "bachelor": "undergraduate",
            "undergrad": "undergraduate",
            "undergraduate": "undergraduate",
            "master": "master",
            "masters": "master",
            "phd": "doctoral",
            "doctoral": "doctoral",
            "doctor": "doctoral",
        }.get(degree, degree)
    return result


# Product-visible template families (Vibe Research surfaces + preserved app packs).
# Order matches the desktop new-workflow category rail.
FAMILY_TEMPLATES: dict[str, list[str]] = {
    "research": ["idea_discovery", "experiment_bridge", "auto_review", "full_pipeline"],
    "academic": [
        "paper_writing",
        "thesis_proposal",
        "literature_review",
        "course_paper",
        "course_report",
    ],
    "competition": list(COMPETITIONS.keys()),
    "assets": ["paper_from_assets"],
    "communication": ["paper_slides", "paper_poster"],
    "one_sentence": ["grad_project"],
    "ip": ["software_copyright", "copyright_material", "patent_disclosure"],
}

OPTION_SETS: dict[str, list[dict[str, Any]]] = {
    "paper_types_zh": [
        {"value": "bachelor", "label": "本科毕业论文", "defaultPages": 25},
        {"value": "master", "label": "硕士学位论文", "defaultPages": 55},
        {"value": "journal", "label": "期刊论文", "defaultPages": 15},
    ],
    "venues_en": [
        {"value": "ICLR", "label": "ICLR", "defaultPages": 9},
        {"value": "NeurIPS", "label": "NeurIPS", "defaultPages": 9},
        {"value": "ICML", "label": "ICML", "defaultPages": 8},
    ],
    "paper_from_assets_target_types": [
        {"value": "academic_zh", "label": "学术论文（中文）"},
        {"value": "academic_en", "label": "学术论文（英文）"},
        {"value": "competition", "label": "竞赛论文（数模 / 认证杯等）"},
        {"value": "course", "label": "课程论文 / 课程报告"},
        {"value": "nature", "label": "Nature / SCI 期刊风格"},
    ],
    "course_subject_domains": [
        {"value": "cs", "label": "计算机科学"},
        {"value": "humanities", "label": "人文社科"},
        {"value": "economics", "label": "经济管理"},
        {"value": "engineering", "label": "工程技术"},
    ],
    "humanities_subject_domains": [
        {"value": "literature", "label": "文学 / 比较文学"},
        {"value": "history", "label": "历史学"},
        {"value": "philosophy", "label": "哲学"},
        {"value": "sociology", "label": "社会学"},
        {"value": "communication", "label": "新闻传播"},
        {"value": "cultural_studies", "label": "文化研究"},
        {"value": "education", "label": "教育学"},
        {"value": "law", "label": "法学"},
        {"value": "art", "label": "艺术学"},
        {"value": "politics", "label": "政治学"},
    ],
    "project_types": [
        {"value": "fullstack", "label": "全栈 Web 应用"},
        {"value": "frontend", "label": "纯前端页面"},
        {"value": "cli", "label": "命令行工具"},
        {"value": "script", "label": "Python 脚本"},
    ],
    "ui_controls": [
        {"value": "upload", "label": "资料上传"},
        {"value": "template", "label": "格式模板"},
        {"value": "format", "label": "输出格式"},
        {"value": "review", "label": "审查模式"},
        {"value": "checkpoint", "label": "人工检查点"},
        {"value": "improvement_loop", "label": "论文改进循环"},
    ],
}


def catalog() -> dict[str, Any]:
    """Return a secret-free, serializable configuration catalogue."""
    # Lazy import avoids circular import; production catalog excludes host
    # content scaffolds as production scientific backends (P1-PS-004).
    try:
        from services.workflow_engine import production_skill_catalog
        production = production_skill_catalog()
    except Exception as exc:  # pragma: no cover
        production = {
            "mode": "production",
            "host_content_scaffolds_excluded": True,
            "error": f"production_catalog_unavailable:{type(exc).__name__}",
            "templates": {},
        }
    return {
        "version": 2,
        "families": {key: list(value) for key, value in FAMILY_TEMPLATES.items()},
        "competitions": [{"id": key, **value} for key, value in COMPETITIONS.items()],
        "defaults": deepcopy(DEFAULTS),
        "aliases": dict(ALIASES),
        "enum_options": {key: sorted(value) for key, value in ENUMS.items()},
        "option_sets": deepcopy(OPTION_SETS),
        "bool_fields": sorted(BOOL_FIELDS),
        "text_fields": sorted(TEXT_FIELDS),
        "list_fields": sorted(LIST_FIELDS),
        "production": production,
        "production_catalog_has_no_host_content_scaffolds": bool(
            production.get("host_content_scaffolds_excluded")
        ),
    }
