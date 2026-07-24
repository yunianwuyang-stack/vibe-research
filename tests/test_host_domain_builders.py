"""Unit tests for host_domain_builders (thesis / humanities / course / competition)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services import host_domain_builders as domain  # noqa: E402


def test_literature_review_host_scaffold_is_honest_and_large(tmp_path: Path) -> None:
    ws = tmp_path / "综述工作区"
    ws.mkdir()
    (ws / "user_data").mkdir()
    (ws / "user_data" / "seed.bib").write_text("@article{a,title={Seed}}\n", encoding="utf-8")
    result = domain.build_literature_review(
        ws,
        title="证据原生科研 Agent 文献综述",
        params={"topic": "可审计科研执行", "target_paper_count": 12},
    )
    assert result["success"] is True
    assert result.get("verification") == "all_unverified_host_scaffold"
    pool = (ws / "papers_pool.md").read_text(encoding="utf-8")
    review = ws / "LITERATURE_REVIEW.md"
    assert review.is_file() and review.stat().st_size >= 5000
    text = review.read_text(encoding="utf-8")
    assert "UNVERIFIED_HOST_SCAFFOLD" in text or "待核验" in text
    assert "假 DOI" not in text
    assert "待核验" in pool
    assert "user_data/seed.bib" in pool or "seed.bib" in pool


def test_project_blueprint_host_scaffold(tmp_path: Path) -> None:
    ws = tmp_path / "蓝图工作区"
    ws.mkdir()
    result = domain.build_project_blueprint(
        ws,
        title="一句话做开题到论文",
        params={"one_sentence": "用证据门禁自动完成开题到 PDF"},
    )
    assert result["success"] is True
    for name in ("PROJECT_BLUEPRINT.md", "RESEARCH_CONTRACT_DRAFT.md", "MILESTONES.md"):
        path = ws / name
        assert path.is_file() and path.stat().st_size >= 80


def test_thesis_proposal_writes_markdown_artifacts(tmp_path: Path) -> None:
    ws = tmp_path / "开题工作区"
    ws.mkdir()
    result = domain.build_thesis_proposal(
        ws,
        title="证据原生科研 Agent 开题",
        params={"degree_level": "phd", "topic": "可审计科研执行"},
    )
    assert result["success"] is True
    notes = ws / "literature_notes.md"
    proposal = ws / "PROPOSAL.md"
    assert notes.is_file() and notes.stat().st_size >= 80
    assert proposal.is_file() and proposal.stat().st_size >= 400
    text = proposal.read_text(encoding="utf-8")
    assert "证据原生" in text or "可审计" in text
    assert "技术路线" in text


def test_humanities_plan_and_write_chain(tmp_path: Path) -> None:
    ws = tmp_path / "人文工作区"
    ws.mkdir()
    plan = domain.build_humanities_plan(
        ws,
        title="叙事与证据伦理",
        params={"subject_domain": "literature"},
    )
    paper = domain.build_humanities_paper(
        ws,
        title="叙事与证据伦理",
        params={"subject_domain": "literature"},
    )
    assert plan["success"] and paper["success"]
    assert (ws / "OUTLINE.md").is_file()
    assert (ws / "PAPER_PLAN.md").is_file()
    body = (ws / "HUMANITIES_PAPER.md").read_text(encoding="utf-8")
    assert "问题提出" in body
    assert "OUTLINE" in body or "大纲" in body or len(body) > 300


def test_course_plan_paper_report(tmp_path: Path) -> None:
    ws = tmp_path / "课程工作区"
    ws.mkdir()
    assert domain.build_course_plan(ws, title="分布式系统课程论文")["success"]
    assert domain.build_course_paper(ws, title="分布式系统课程论文", params={"subject_domain": "cs"})["success"]
    assert domain.build_course_report_plan(ws, title="课程项目报告")["success"]
    assert domain.build_course_report(ws, title="课程项目报告")["success"]
    assert (ws / "COURSE_PAPER.md").stat().st_size >= 200
    assert (ws / "COURSE_REPORT.md").stat().st_size >= 100
    assert (ws / "PROJECT_FACTS.md").is_file()


def test_competition_full_host_scaffold(tmp_path: Path) -> None:
    ws = tmp_path / "数模工作区"
    ws.mkdir()
    problem = (
        "某城市共享单车调度问题：给定站点需求与运力约束，"
        "建立优化模型使调度成本最低并分析敏感性。"
    )
    assert domain.build_competition_problem_analysis(
        ws, title="共享单车调度", params={"problem_statement": problem}
    )["success"]
    assert domain.build_competition_modeling(ws)["success"]
    code = domain.build_competition_code(ws)
    assert code["success"] is True
    assert (ws / "code" / "main.py").is_file()
    assert (ws / "RESULTS.md").is_file()
    results_json = ws / "figures" / "all_results.json"
    assert results_json.is_file()
    payload = json.loads(results_json.read_text(encoding="utf-8"))
    assert payload.get("objective") == 1.0
    # Figures ON path: paper-figure before competition paper embeds metrics plot.
    fig = domain.build_paper_figure(ws, title="共享单车调度建模")
    assert fig["success"] is True
    assert (ws / "figures" / "fig_metrics.pdf").is_file()
    paper = domain.build_competition_paper_zh(
        ws, title="共享单车调度建模", template="comp_cumcm"
    )
    assert paper["success"] is True
    assert paper.get("figures_embedded") is True
    main_tex = ws / "paper" / "main.tex"
    assert main_tex.is_file() and main_tex.stat().st_size >= 200
    tex = main_tex.read_text(encoding="utf-8")
    assert "\\begin{document}" in tex
    assert "\\end{document}" in tex
    assert "fig_metrics" in tex
    assert "../figures/fig_metrics.pdf" in tex


def test_paper_plan_analysis_write_chain(tmp_path: Path) -> None:
    ws = tmp_path / "资产论文工作区"
    ws.mkdir()
    assert domain.build_paper_plan(ws, title="Evidence Native Agents")["success"]
    assert domain.build_paper_analysis(ws, title="Evidence Native Agents")["success"]
    fig = domain.build_paper_figure(ws, title="Evidence Native Agents")
    assert fig["success"] is True
    assert (ws / "figures" / "latex_includes.tex").is_file()
    assert (ws / "figures" / "fig_metrics.pdf").is_file()
    assert (ws / "figures" / "TABLE_metrics.md").is_file()
    assert domain.build_paper_write(ws, title="Evidence Native Agents", language="en")["success"]
    assert (ws / "PAPER_PLAN.md").is_file()
    assert (ws / "RESULTS.md").is_file()
    assert (ws / "paper" / "main.tex").is_file()
    tex = (ws / "paper" / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{document}" in tex
    assert "fig_metrics" in tex


def test_idea_discovery_host_chain(tmp_path: Path) -> None:
    ws = tmp_path / "idea发现工作区"
    ws.mkdir()
    topic = "证据原生科研 Agent"
    assert domain.build_research_lit(ws, title=topic, params={"topic": topic})["success"]
    assert domain.build_idea_creator(ws, title=topic, params={"topic": topic})["success"]
    assert domain.build_novelty_check(ws, title=topic, params={"topic": topic})["success"]
    assert domain.build_research_review(ws, title=topic, params={"topic": topic})["success"]
    assert domain.build_research_refine_pipeline(ws, title=topic, params={"topic": topic})["success"]
    lit = ws / "literature_review.md"
    assert lit.is_file() and lit.stat().st_size >= 1500
    assert "UNVERIFIED" in lit.read_text(encoding="utf-8") or "待核验" in lit.read_text(encoding="utf-8")
    assert (ws / "references.bib").is_file()
    idea = ws / "IDEA_REPORT.md"
    assert idea.is_file() and idea.stat().st_size >= 1500
    assert (ws / "novelty_check_report.md").stat().st_size >= 800
    assert (ws / "review_report.md").stat().st_size >= 800
    proposal = ws / "refine-logs" / "FINAL_PROPOSAL.md"
    plan = ws / "refine-logs" / "EXPERIMENT_PLAN.md"
    assert proposal.is_file() and proposal.stat().st_size >= 1500
    assert plan.is_file() and plan.stat().st_size >= 200


def test_auto_review_loop_host_narrative(tmp_path: Path) -> None:
    ws = tmp_path / "审稿循环工作区"
    ws.mkdir()
    # Seed experiment evidence so claim mapping is non-empty.
    domain.build_experiment_bridge(ws, title="审稿主题", params={"topic": "证据门禁", "seed": 7})
    result = domain.build_auto_review_loop(
        ws, title="审稿主题", params={"topic": "证据门禁", "max_rounds": 2, "target_score": 6}
    )
    assert result["success"] is True, result
    narrative = ws / "NARRATIVE_REPORT.md"
    auto = ws / "AUTO_REVIEW.md"
    assert narrative.is_file() and narrative.stat().st_size >= 1000
    assert auto.is_file() and "host_domain_builders.auto-review-loop" in auto.read_text(encoding="utf-8")
    state = json.loads((ws / "REVIEW_STATE.json").read_text(encoding="utf-8"))
    assert state.get("status") == "completed"
    assert float(state.get("last_score") or 0) >= 5.0


def test_experiment_bridge_runs_real_cpu_suite(tmp_path: Path) -> None:
    ws = tmp_path / "实验桥接工作区"
    ws.mkdir()
    result = domain.build_experiment_bridge(
        ws,
        title="证据原生科研 Agent 实验桥接",
        params={"topic": "可审计实验复现与基线对比", "seed": 42},
    )
    assert result["success"] is True, result
    results_md = ws / "experiment_results.md"
    assert results_md.is_file() and results_md.stat().st_size >= 500
    text = results_md.read_text(encoding="utf-8")
    assert "host_domain_builders.experiment-bridge" in text
    assert "M2" in text
    data = json.loads((ws / "figures" / "experiment_data.json").read_text(encoding="utf-8"))
    assert data["main_results"]["method_beats_baseline"] is True
    assert (ws / "code" / "experiments" / "run_bridge.py").is_file()
    assert (ws / "results" / "m2_main.json").is_file()
    assert (ws / "refine-logs" / "EXPERIMENT_PLAN.md").is_file()
    assert (ws / "refine-logs" / "EXPERIMENT_TRACKER.md").is_file()
    assert (ws / "figures" / "latex_includes.tex").is_file()
    assert (ws / "figures" / "fig_metrics.pdf").is_file()
    assert (ws / "figures" / "TABLE_main_results.md").is_file()
    # Re-run is deterministic on same seed.
    again = domain.build_experiment_bridge(
        ws, title="证据原生科研 Agent 实验桥接", params={"topic": "可审计实验复现与基线对比", "seed": 42}
    )
    assert again["success"] is True
    data2 = json.loads((ws / "figures" / "experiment_data.json").read_text(encoding="utf-8"))
    assert data2["metrics"]["method_rmse"] == data["metrics"]["method_rmse"]


def test_competition_english_paper_scaffold(tmp_path: Path) -> None:
    ws = tmp_path / "mcm-ws"
    ws.mkdir()
    domain.build_competition_code(ws, title="Bike Rebalancing")
    domain.build_paper_figure(ws, title="Bike Rebalancing")
    result = domain.build_competition_paper_en(ws, title="Bike Rebalancing", template="comp_mcm")
    assert result["success"]
    assert result.get("figures_embedded") is True
    tex = (ws / "paper" / "main.tex").read_text(encoding="utf-8")
    assert "documentclass" in tex
    assert "Bike Rebalancing" in tex or "Mathematical Modeling" in tex
    assert "fig_metrics" in tex
    assert "../figures/fig_metrics.pdf" in tex


def test_competition_docx_markdown_host_scaffold(tmp_path: Path) -> None:
    """comp-paper-*-docx must emit paper/main.md large enough for the DOCX chain."""
    ws = tmp_path / "华东docx工作区"
    ws.mkdir()
    problem = "共享单车调度：站点需求与运力约束下最小化调度成本。"
    assert domain.build_competition_problem_analysis(
        ws, title="共享单车调度", params={"problem_statement": problem}
    )["success"]
    assert domain.build_competition_modeling(ws)["success"]
    assert domain.build_competition_code(ws)["success"]
    assert domain.build_paper_figure(ws, title="共享单车调度")["success"]

    zh = domain.build_competition_paper_md(
        ws, title="共享单车调度", params={"competition": "huadong"}, language="zh",
    )
    assert zh["success"] is True
    main_md = ws / "paper" / "main.md"
    assert main_md.is_file() and main_md.stat().st_size >= 8000
    text = main_md.read_text(encoding="utf-8")
    assert "问题重述" in text
    assert "fig_metrics" in text or "figures/" in text

    en = domain.build_competition_paper_md(
        ws, title="Bike Rebalancing", params={"competition": "shuwei_en"}, language="en",
    )
    assert en["success"] is True
    assert main_md.stat().st_size >= 8000
    assert "Problem Restatement" in main_md.read_text(encoding="utf-8")

    improved = domain.build_auto_paper_improvement_docx(
        ws, title="共享单车调度", params={"language": "zh", "competition": "huadong"},
    )
    assert improved["success"] is True
    assert (ws / "paper" / "PAPER_IMPROVEMENT_LOG.md").is_file()


def test_full_pipeline_plan_and_write_grounded_on_bridge(tmp_path: Path) -> None:
    """paper-plan / paper-write host tail must bind idea + experiment-bridge lineage."""
    ws = tmp_path / "全流程写作工作区"
    ws.mkdir()
    domain.build_research_lit(ws, title="Evidence Agent", params={"topic": "auditable agents"})
    domain.build_idea_creator(ws, title="Evidence Agent", params={"topic": "auditable agents"})
    domain.build_novelty_check(ws, title="Evidence Agent", params={"topic": "auditable agents"})
    domain.build_research_refine_pipeline(
        ws, title="Evidence Agent", params={"topic": "auditable agents"}
    )
    bridge = domain.build_experiment_bridge(
        ws, title="Evidence Agent", params={"topic": "auditable agents", "seed": 3}
    )
    assert bridge["success"] is True
    plan = domain.build_paper_plan(ws, title="Evidence-native Full Pipeline", params={})
    assert plan["success"] is True
    plan_text = (ws / "PAPER_PLAN.md").read_text(encoding="utf-8")
    assert "IDEA_REPORT.md" in plan_text
    assert "experiment_results.md" in plan_text
    write = domain.build_paper_write(
        ws,
        title="Evidence-native Full Pipeline",
        params={"topic": "auditable agents"},
        language="en",
    )
    assert write["success"] is True
    tex_path = ws / "paper" / "main.tex"
    assert tex_path.is_file()
    assert tex_path.stat().st_size >= 1500
    tex = tex_path.read_text(encoding="utf-8")
    assert "documentclass" in tex
    assert "Artifact Lineage" in tex or "lineage" in tex.lower()
    assert "experiment" in tex.lower()
    # Underscores are LaTeX-escaped in body text.
    assert (
        "method\\_beats\\_baseline" in tex
        or "experiment\\_results" in tex
        or "experiment_results" in tex.lower()
    )
    lineage = write.get("lineage_inputs") or []
    assert "experiment_results.md" in lineage
    assert "figures/experiment_data.json" in lineage


def test_grad_project_host_chain_produces_runnable_artifacts(tmp_path: Path) -> None:
    ws = tmp_path / "毕设工作区"
    ws.mkdir()
    req = domain.build_dev_requirement(
        ws,
        title="证据门禁科研助手",
        params={"idea": "一句话生成可审计科研助手", "project_type": "fullstack"},
    )
    assert req["success"] is True
    assert (ws / "REQUIREMENTS.md").stat().st_size >= 1500
    text = (ws / "REQUIREMENTS.md").read_text(encoding="utf-8")
    for sec in (
        "## 项目概述",
        "## 用户角色",
        "## 功能清单",
        "## 页面清单",
        "## 接口清单",
        "## 非功能需求",
    ):
        assert sec in text
    design = domain.build_dev_design(
        ws,
        title="证据门禁科研助手",
        params={"idea": "一句话生成可审计科研助手", "project_type": "fullstack"},
    )
    assert design["success"] is True
    assert (ws / "DESIGN.md").stat().st_size >= 2000
    assert "CREATE TABLE" in (ws / "schema.sql").read_text(encoding="utf-8")
    code = domain.build_dev_code(
        ws,
        title="证据门禁科研助手",
        params={"idea": "一句话生成可审计科研助手", "project_type": "fullstack"},
    )
    assert code["success"] is True
    main_py = ws / "code" / "backend" / "main.py"
    assert main_py.is_file()
    source = main_py.read_text(encoding="utf-8")
    compile(source, str(main_py), "exec")
    assert "FastAPI" in source
    assert (ws / "code" / "frontend" / "index.html").is_file()
    assert (ws / "RUN.md").is_file()
    check = domain.build_dev_selfcheck(ws, title="证据门禁科研助手", params={})
    assert check["success"] is True
    report = (ws / "TEST_REPORT.md").read_text(encoding="utf-8")
    for sec in ("## 依赖安装", "## 服务启动", "## 功能验证", "## 修复记录", "## 已知问题"):
        assert sec in report


def test_comp_stats_topic_has_figure_manifest(tmp_path: Path) -> None:
    ws = tmp_path / "统计选题"
    ws.mkdir()
    result = domain.build_comp_stats_topic(
        ws,
        title="区域创新效率影响因素",
        params={"topic": "区域创新效率影响因素"},
    )
    assert result["success"] is True
    plan = ws / "TOPIC_PLAN.md"
    assert plan.is_file() and plan.stat().st_size >= 1000
    text = plan.read_text(encoding="utf-8")
    assert "<!-- BEGIN FIGURE_MANIFEST -->" in text
    assert "<!-- END FIGURE_MANIFEST -->" in text
    assert "fig_coef" in text
    assert "fig_roadmap" in text


def test_humanities_write_latex_size_gate(tmp_path: Path) -> None:
    ws = tmp_path / "人文LaTeX"
    ws.mkdir()
    domain.build_humanities_plan(ws, title="叙事伦理", params={"subject_domain": "literature"})
    result = domain.build_humanities_write_latex(
        ws, title="叙事伦理", params={"subject_domain": "literature"}
    )
    assert result["success"] is True
    tex = ws / "paper" / "main.tex"
    assert tex.is_file() and tex.stat().st_size >= 5000
    assert "ctexart" in tex.read_text(encoding="utf-8")


def test_auto_paper_improvement_loop_writes_log(tmp_path: Path) -> None:
    ws = tmp_path / "改进循环"
    ws.mkdir()
    domain.build_paper_analysis(ws, title="Host Paper")
    domain.build_paper_plan(ws, title="Host Paper")
    domain.build_paper_write(ws, title="Host Paper", language="en")
    result = domain.build_auto_paper_improvement_loop(ws, title="Host Paper")
    assert result["success"] is True
    log = ws / "paper" / "PAPER_IMPROVEMENT_LOG.md"
    assert log.is_file() and log.stat().st_size >= 200
    text = log.read_text(encoding="utf-8")
    assert "offline host" in text
    assert "No GPT/Claude review scores claimed" in text
    assert (ws / "paper" / "main.tex").stat().st_size >= 15000
