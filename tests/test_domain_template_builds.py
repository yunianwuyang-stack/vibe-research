"""Host-side soft-copyright / patent build scripts produce real artifacts."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


def test_copyright_build_script_generates_formal_docx_and_txt(tmp_path):
    work = tmp_path / "软件著作权申请资料"
    draft = work / "草稿"
    draft.mkdir(parents=True)
    (work / "截图").mkdir()
    (draft / "业务理解.md").write_text("# 业务理解\n测试软件用于本地科研工作台验证。\n", encoding="utf-8")
    (draft / "业务理解.json").write_text('{"user_confirmed": true}', encoding="utf-8")
    (draft / "代码文件选择.json").write_text('{"user_confirmed": true, "files": []}', encoding="utf-8")
    (draft / "申请表信息.md").write_text("➤软件全称：测试软件\n➤版本号：V1.0\n", encoding="utf-8")
    (draft / "申请表字段确认.json").write_text('{"application_fields_confirmed": true}', encoding="utf-8")
    (draft / "最终生成确认.json").write_text('{"markdown_confirmed": true}', encoding="utf-8")
    (work / "截图方式确认.json").write_text(
        '{"screenshot_method_confirmed": true, "screenshot_method": "manual"}',
        encoding="utf-8",
    )
    code = "\n".join(f"## 第{i}页\n\n```python\nprint({i})\n```\n" for i in range(1, 61))
    (draft / "代码-前30页.md").write_text(code, encoding="utf-8")
    (draft / "代码-后30页.md").write_text(code, encoding="utf-8")
    (draft / "操作手册.md").write_text("# 操作手册\n\n## 安装\n1. 安装\n\n## 使用\n1. 启动\n", encoding="utf-8")

    script = ROOT / "skills" / "copyright-build" / "scripts" / "build_docx_from_md.py"
    assert script.is_file()
    result = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "--workdir",
            str(work),
            "--software-name",
            "测试软件",
            "--version",
            "V1.0",
            "--skip-preview",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    formal = work / "正式资料"
    txt = formal / "申请表信息.txt"
    manual = formal / "测试软件_操作手册.docx"
    code_front = formal / "测试软件-代码(前30页).docx"
    code_back = formal / "测试软件-代码(后30页).docx"
    assert txt.is_file() and "测试软件" in txt.read_text(encoding="utf-8")
    for docx_path in (manual, code_front, code_back):
        assert docx_path.is_file() and docx_path.stat().st_size > 1000
        with zipfile.ZipFile(docx_path) as archive:
            assert "word/document.xml" in archive.namelist()


def test_patent_build_script_renders_mermaid_and_exports_docx(tmp_path):
    patent_dir = tmp_path / "专利交底书"
    patent_dir.mkdir(parents=True)
    (patent_dir / "交底书草稿.md").write_text(
        """# 测试案件

## 一、技术背景与现有技术
现有方案存在延迟与可审计性不足。

## 三、本发明技术方案的详细阐述
### 3.2 系统框图
```mermaid
flowchart LR
  A[输入] --> B[处理]
  B --> C[输出]
```
### 3.4 流程图
```mermaid
flowchart TD
  S[开始] --> E[结束]
```

## 六、具体实施方式
按上述模块部署并复现。
""",
        encoding="utf-8",
    )
    script = ROOT / "skills" / "patent-build" / "tools" / "mermaid_render.py"
    assert script.is_file()
    result = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "-i",
            str(patent_dir / "交底书草稿.md"),
            "-o",
            str(patent_dir / "交底书.md"),
            "--docx",
            str(patent_dir / "交底书.docx"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(tmp_path),
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (patent_dir / "交底书.md").is_file()
    docx_path = patent_dir / "交底书.docx"
    assert docx_path.is_file() and docx_path.stat().st_size > 1000
    figures = list((patent_dir / "mermaid_figures").glob("*.png"))
    assert len(figures) >= 1
    with zipfile.ZipFile(docx_path) as archive:
        assert "word/document.xml" in archive.namelist()


def test_paper_slides_host_builder_generates_pdf_and_pptx(tmp_path):
    workspace = tmp_path / "ws-slides"
    paper = workspace / "paper"
    paper.mkdir(parents=True)
    (paper / "main.md").write_text(
        """# Evidence-Native Research Agents

## Motivation
- Doctoral pipelines need auditable artifacts
- Silent degradation breaks scientific trust

## Method
- Host builders produce real PPTX and PDF
- Lineage JSON records every executor step

## Results
- End-to-end workspace export remains deterministic
- Unicode paths survive dual clean environments
""",
        encoding="utf-8",
    )
    (paper / "main.tex").write_text(
        r"""\documentclass{article}
\title{Evidence-Native Research Agents}
\author{Vibe Research}
\begin{document}
\maketitle
\section{Motivation}
Doctoral pipelines need auditable artifacts.
\section{Method}
Host builders produce real PPTX and PDF.
\section{Results}
Unicode paths survive dual clean environments.
\end{document}
""",
        encoding="utf-8",
    )
    script = ROOT / "skills" / "paper-slides" / "tools" / "build_slides.py"
    assert script.is_file()
    result = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "--workspace",
            str(workspace),
            "--venue",
            "ICML",
            "--talk-type",
            "spotlight",
            "--minutes",
            "8",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    pdf = workspace / "slides" / "main.pdf"
    pptx = workspace / "slides" / "presentation.pptx"
    outline = workspace / "slides" / "SLIDE_OUTLINE.md"
    script_md = workspace / "slides" / "TALK_SCRIPT.md"
    assert pdf.is_file() and pdf.stat().st_size >= 500
    assert pptx.is_file() and pptx.stat().st_size >= 500
    assert outline.is_file() and "ICML" in outline.read_text(encoding="utf-8")
    assert script_md.is_file() and "Talk Script" in script_md.read_text(encoding="utf-8")
    with zipfile.ZipFile(pptx) as archive:
        names = archive.namelist()
        assert any(n.startswith("ppt/slides/slide") for n in names)


def test_paper_poster_host_builder_generates_pdf_and_pptx(tmp_path):
    workspace = tmp_path / "ws-poster"
    paper = workspace / "paper"
    paper.mkdir(parents=True)
    (paper / "main.md").write_text(
        """# Vibe Research Poster Pipeline

## Background
- Conference posters need visual-first summaries
- A0 landscape remains the default print size

## Approach
- Deterministic extraction from paper markdown
- Editable PPTX plus print-ready PDF

## Findings
- Host executor writes lineage under .host_builds
- No provider credentials are required for this step
""",
        encoding="utf-8",
    )
    script = ROOT / "skills" / "paper-poster" / "tools" / "build_poster.py"
    assert script.is_file()
    result = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "--workspace",
            str(workspace),
            "--venue",
            "NeurIPS",
            "--size",
            "A1",
            "--orientation",
            "landscape",
            "--columns",
            "3",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    pdf = workspace / "poster" / "main.pdf"
    pptx = workspace / "poster" / "poster.pptx"
    plan = workspace / "poster" / "POSTER_CONTENT_PLAN.md"
    speech = workspace / "poster" / "POSTER_SPEECH.md"
    assert pdf.is_file() and pdf.stat().st_size >= 500
    assert pptx.is_file() and pptx.stat().st_size >= 500
    assert plan.is_file() and "Poster Content Plan" in plan.read_text(encoding="utf-8")
    assert speech.is_file() and "Presentation Script" in speech.read_text(encoding="utf-8")
    with zipfile.ZipFile(pptx) as archive:
        assert any(n.startswith("ppt/slides/slide") for n in archive.namelist())


def test_domain_templates_create_workspace_and_bind_existing_skills(tmp_path, monkeypatch):
    import services.state_store as store
    import services.workflow_engine as engine

    store.DB_PATH = tmp_path / "domain.db"
    engine.WORKSPACES_DIR = tmp_path / "workspaces"
    engine.WORKSPACES_DIR.mkdir()

    async def go():
        await store.init_db()
        matrix = {
            "copyright_material": ["copyright-draft", "copyright-build"],
            "patent_disclosure": ["patent-draft", "patent-build"],
            "grad_project": ["dev-requirement", "dev-design", "dev-code", "dev-selfcheck"],
            "software_copyright": ["software-copyright"],
            "one_sentence_project": ["project-blueprint"],
        }
        for template, skills in matrix.items():
            wf_id = await engine.create_new_workflow(template, f"Domain {template}", {}, False)
            workspace = engine.WORKSPACES_DIR / wf_id
            assert (workspace / "CLAUDE.md").is_file()
            db = await store.get_db()
            try:
                rows = await (
                    await db.execute(
                        "SELECT skill_name,status FROM workflow_steps WHERE workflow_id=? ORDER BY step_order",
                        (wf_id,),
                    )
                ).fetchall()
            finally:
                await db.close()
            names = [row["skill_name"] for row in rows]
            assert names == skills
            for skill in skills:
                assert (ROOT / "skills" / skill / "SKILL.md").is_file()

    import asyncio

    asyncio.run(go())


def test_host_runner_executes_patent_and_copyright_build_without_llm(tmp_path, monkeypatch):
    """patent-build / copyright-build must run as deterministic host steps."""
    import asyncio
    import services.state_store as store
    import services.workflow_engine as engine
    from services.workflow_engine import StepDef, _HostStepRunner

    store.DB_PATH = tmp_path / "host_build.db"
    engine.WORKSPACES_DIR = tmp_path / "workspaces"
    engine.WORKSPACES_DIR.mkdir()

    async def go():
        await store.init_db()

        patent_id = await engine.create_new_workflow(
            "patent_disclosure", "Host Patent Build", {}, False,
        )
        patent_ws = engine.WORKSPACES_DIR / patent_id
        draft_dir = patent_ws / "专利交底书"
        draft_dir.mkdir(parents=True, exist_ok=True)
        (draft_dir / "交底书草稿.md").write_text(
            """# 主机构建案件

## 一、技术背景与现有技术
现有方案延迟高且缺少可审计产物。

## 三、本发明技术方案的详细阐述
### 3.2 系统框图
```mermaid
flowchart LR
  A[输入] --> B[处理]
  B --> C[输出]
```
### 3.4 流程图
```mermaid
flowchart TD
  S[开始] --> E[结束]
```

## 六、具体实施方式
按上述模块部署并复现。
""",
            encoding="utf-8",
        )
        patent_runner = _HostStepRunner(
            "patent_disclosure",
            StepDef(
                skill_name="patent-build",
                display_name="渲染图示并导出 Word",
                output_files=["专利交底书/交底书.docx"],
                primary_output="专利交底书/交底书.docx",
            ),
        )
        patent_result = await patent_runner.run_skill(cwd=patent_ws, extra_params={})
        assert patent_result["success"] is True, patent_result
        assert patent_result.get("returncode", patent_result.get("return_code")) == 0
        patent_docx = patent_ws / "专利交底书" / "交底书.docx"
        assert patent_docx.is_file() and patent_docx.stat().st_size > 1000
        with zipfile.ZipFile(patent_docx) as archive:
            assert "word/document.xml" in archive.namelist()
        patent_lineage = patent_ws / ".host_builds" / "patent-build.json"
        assert patent_lineage.is_file()
        patent_payload = json.loads(patent_lineage.read_text(encoding="utf-8"))
        assert patent_payload["executor"] == "host_step_runner"
        assert patent_payload["skill_name"] == "patent-build"
        assert any(item["path"].endswith("交底书.docx") for item in patent_payload["artifacts"])

        copyright_id = await engine.create_new_workflow(
            "copyright_material", "Host Copyright Build", {}, False,
        )
        copyright_ws = engine.WORKSPACES_DIR / copyright_id
        work = copyright_ws / "软件著作权申请资料"
        draft = work / "草稿"
        draft.mkdir(parents=True)
        (work / "截图").mkdir()
        (draft / "业务理解.md").write_text("# 业务理解\n本地科研工作台验证。\n", encoding="utf-8")
        (draft / "业务理解.json").write_text('{"user_confirmed": true}', encoding="utf-8")
        (draft / "代码文件选择.json").write_text('{"user_confirmed": true, "files": []}', encoding="utf-8")
        (draft / "申请表信息.md").write_text("➤软件全称：主机构建软件\n➤版本号：V1.0\n", encoding="utf-8")
        (draft / "申请表字段确认.json").write_text('{"application_fields_confirmed": true}', encoding="utf-8")
        (draft / "最终生成确认.json").write_text('{"markdown_confirmed": true}', encoding="utf-8")
        (work / "截图方式确认.json").write_text(
            '{"screenshot_method_confirmed": true, "screenshot_method": "manual"}',
            encoding="utf-8",
        )
        code = "\n".join(f"## 第{i}页\n\n```python\nprint({i})\n```\n" for i in range(1, 61))
        (draft / "代码-前30页.md").write_text(code, encoding="utf-8")
        (draft / "代码-后30页.md").write_text(code, encoding="utf-8")
        (draft / "操作手册.md").write_text("# 操作手册\n\n## 安装\n1. 安装\n\n## 使用\n1. 启动\n", encoding="utf-8")

        copyright_runner = _HostStepRunner(
            "copyright_material",
            StepDef(
                skill_name="copyright-build",
                display_name="生成正式 Word/TXT",
                output_files=["软件著作权申请资料/正式资料/生成报告.md"],
                primary_output="软件著作权申请资料/正式资料/",
            ),
        )
        copyright_result = await copyright_runner.run_skill(cwd=copyright_ws, extra_params={})
        assert copyright_result["success"] is True, copyright_result
        formal = work / "正式资料"
        assert formal.is_dir()
        assert (formal / "申请表信息.txt").is_file()
        assert any(path.suffix.lower() == ".docx" for path in formal.glob("*.docx"))
        copyright_lineage = copyright_ws / ".host_builds" / "copyright-build.json"
        assert copyright_lineage.is_file()
        copyright_payload = json.loads(copyright_lineage.read_text(encoding="utf-8"))
        assert copyright_payload["executor"] == "host_step_runner"
        assert copyright_payload["skill_name"] == "copyright-build"
        assert copyright_payload["artifacts"]

    asyncio.run(go())


def test_ip_templates_do_not_inject_generic_docx_export_chain():
    """Dedicated patent/copyright builders already emit formal Word packages."""
    from services.workflow_engine import _resolve_template

    for template in ("copyright_material", "patent_disclosure"):
        for params in ({}, {"output_format": "docx"}, {"output_format": "pdf"}):
            skills = [step.skill_name for step in _resolve_template(template, params, Path(".")).sub_steps]
            assert "docx-export" not in skills
            assert "docx-format-check" not in skills
            assert skills[-1].endswith("-build")

    software = [step.skill_name for step in _resolve_template(
        "software_copyright", {"output_format": "docx"}, Path(".")
    ).sub_steps]
    assert software == ["software-copyright", "docx-format-check", "docx-export"]


def test_format_profile_host_step_parses_chinese_requirements(tmp_path):
    import asyncio
    from services.workflow_engine import StepDef, _HostStepRunner

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "FORMAT_REQUIREMENTS.md").write_text(
        "# 格式\n正文小四号宋体，1.5倍行距，页边距2.54厘米，一级标题三号黑体。\n",
        encoding="utf-8",
    )

    async def go():
        runner = _HostStepRunner(
            "course_paper",
            StepDef(
                skill_name="format-profile",
                display_name="解析格式要求",
                output_files=["_text_profile.json"],
                primary_output="_text_profile.json",
            ),
        )
        result = await runner.run_skill(
            cwd=workspace,
            extra_params={"format_text": "正文小四号宋体，1.5倍行距，页边距2.54厘米，一级标题三号黑体。"},
        )
        assert result["success"] is True, result
        profile_path = workspace / "_text_profile.json"
        assert profile_path.is_file()
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        assert profile["body"]["font_size_pt"] == 12
        assert profile["body"]["line_spacing"] == 1.5
        assert profile["page"]["margin_top_cm"] == 2.54
        assert profile["headings"]["level1_pt"] == 16
        assert profile["fonts"]["chinese_body"] == "SimSun"
        assert profile["fonts"]["chinese_heading"] == "SimHei"
        assert profile["_derived_from"] == "text-description"
        assert profile["_matched_items"]

    asyncio.run(go())


def test_docx_format_check_host_step_fixes_list_headings(tmp_path):
    import asyncio
    from services.workflow_engine import StepDef, _HostStepRunner

    workspace = tmp_path / "ws"
    workspace.mkdir()
    source = """# 课程论文草稿

- 一、问题重述
正文第一段。

- 图 4-1：方法对比
![fig](figures/a.png)

$$
y = ax + b
$$
- (1)

```python
print(1)
```

"""
    (workspace / "COURSE_PAPER.md").write_text(source, encoding="utf-8")

    async def go():
        runner = _HostStepRunner(
            "course_paper",
            StepDef(
                skill_name="docx-format-check",
                display_name="Markdown 格式自检与修复",
                output_files=["DOCX_FORMAT_CHECK_REPORT.md"],
                primary_output="DOCX_FORMAT_CHECK_REPORT.md",
            ),
        )
        result = await runner.run_skill(cwd=workspace, extra_params={})
        assert result["success"] is True, result
        report = workspace / "DOCX_FORMAT_CHECK_REPORT.md"
        assert report.is_file() and report.stat().st_size >= 200
        updated = (workspace / "COURSE_PAPER.md").read_text(encoding="utf-8")
        assert "# 一、问题重述" in updated
        assert "- 一、问题重述" not in updated
        assert "图 4-1：方法对比" in updated
        assert "- 图 4-1：方法对比" not in updated
        assert "$$" in updated and "(1)" in updated
        report_text = report.read_text(encoding="utf-8")
        assert "自动修复" in report_text
        assert "list-as-heading" in report_text or "converted heading list" in report_text

    asyncio.run(go())


def test_paper_compile_host_step_builds_pdf(tmp_path):
    import asyncio
    import shutil
    from services.workflow_engine import StepDef, _HostStepRunner

    workspace = tmp_path / "ws"
    paper = workspace / "paper"
    paper.mkdir(parents=True)
    sample = ROOT / "tests" / "document_artifacts" / "paper" / "main.tex"
    assert sample.is_file()
    shutil.copy(sample, paper / "main.tex")
    figures = ROOT / "tests" / "document_artifacts" / "figures"
    if figures.is_dir():
        shutil.copytree(figures, workspace / "figures", dirs_exist_ok=True)

    async def go():
        runner = _HostStepRunner(
            "paper_writing_zh",
            StepDef(
                skill_name="paper-compile-zh",
                display_name="编译 PDF（中文）",
                output_files=["paper/main.pdf"],
                primary_output="paper/main.pdf",
            ),
        )
        result = await runner.run_skill(cwd=workspace, extra_params={})
        assert result["success"] is True, result
        pdf = paper / "main.pdf"
        assert pdf.is_file() and pdf.stat().st_size > 1000
        assert pdf.read_bytes()[:4] == b"%PDF"
        lineage = workspace / ".host_builds" / "paper-compile-zh.json"
        assert lineage.is_file()
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload["executor"] == "host_step_runner"
        assert payload["skill_name"] == "paper-compile-zh"

    asyncio.run(go())


def test_assets_inventory_host_step_classifies_user_data(tmp_path):
    import asyncio
    from services.workflow_engine import StepDef, _HostStepRunner

    workspace = tmp_path / "ws"
    user = workspace / "user_data"
    user.mkdir(parents=True)
    (user / "problem.md").write_text("# problem" + chr(10) + "prove pipeline" + chr(10), encoding="utf-8")
    (user / "main.py").write_text("print('ok')" + chr(10), encoding="utf-8")
    (user / "train.csv").write_text("x,y" + chr(10) + "1,2" + chr(10), encoding="utf-8")
    (user / "fig1.png").write_bytes(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"0" * 64)
    (user / "results.json").write_text('{"acc": 0.9}' + chr(10), encoding="utf-8")
    (user / "template.cls").write_text("% cls" + chr(10), encoding="utf-8")

    async def go():
        runner = _HostStepRunner(
            "paper_from_assets",
            StepDef(
                skill_name="assets-inventory",
                display_name="assets inventory",
                output_files=["ASSETS_INVENTORY.md", "_assets_index.json"],
                primary_output="ASSETS_INVENTORY.md",
            ),
        )
        result = await runner.run_skill(
            cwd=workspace, extra_params={"paper_type_target": "academic_zh"},
        )
        assert result["success"] is True, result
        inventory = workspace / "ASSETS_INVENTORY.md"
        index = workspace / "_assets_index.json"
        assert inventory.is_file() and inventory.stat().st_size >= 100
        payload = json.loads(index.read_text(encoding="utf-8"))
        assert payload["executor"] == "host_step_runner"
        cats = {item["name"]: item["category"] for item in payload["files"]}
        assert cats["problem.md"] == "problem"
        assert cats["main.py"] == "code"
        assert cats["train.csv"] == "data"
        assert cats["fig1.png"] == "figure"
        assert cats["results.json"] == "result"
        assert cats["template.cls"] == "template"

    asyncio.run(go())


def test_paper_figure_html_host_step_renders_pdf(tmp_path):
    import asyncio
    from services.workflow_engine import StepDef, _HostStepRunner

    workspace = tmp_path / "ws"
    figures = workspace / "figures"
    figures.mkdir(parents=True)
    (figures / "fig_flow.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:sans-serif;margin:20px}"
        ".b{border:2px solid #000;padding:10px;display:inline-block}</style>"
        "</head><body><div class='b'>A</div> -> <div class='b'>B</div></body></html>",
        encoding="utf-8",
    )

    async def go():
        runner = _HostStepRunner(
            "course_paper",
            StepDef(
                skill_name="paper-figure-html",
                display_name="HTML figures",
                output_files=["figures/latex_includes.tex"],
                primary_output="figures/",
            ),
        )
        result = await runner.run_skill(cwd=workspace, extra_params={})
        assert result["success"] is True, result
        pdf = figures / "fig_flow.pdf"
        assert pdf.is_file() and pdf.stat().st_size > 500
        assert pdf.read_bytes()[:4] == b"%PDF"
        assert (figures / "latex_includes.tex").is_file()
        lineage = workspace / ".host_builds" / "paper-figure-html.json"
        assert lineage.is_file()
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload["executor"] == "host_step_runner"

    asyncio.run(go())


def test_paper_figure_drawio_host_step_exports_pdf(tmp_path):
    import asyncio
    from services.workflow_engine import StepDef, _HostStepRunner

    workspace = tmp_path / "ws"
    figures = workspace / "figures"
    figures.mkdir(parents=True)
    (figures / "fig_arch.drawio").write_text(
        '<mxfile host="vibe"><diagram id="1" name="Page-1"><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="2" value="A" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="80" height="40" as="geometry"/></mxCell>'
        '<mxCell id="3" value="B" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="180" y="40" width="80" height="40" as="geometry"/></mxCell>'
        '<mxCell id="4" edge="1" parent="1" source="2" target="3" style="endArrow=classic;">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
        '</root></mxGraphModel></diagram></mxfile>',
        encoding="utf-8",
    )

    async def go():
        runner = _HostStepRunner(
            "course_paper",
            StepDef(
                skill_name="paper-figure-drawio",
                display_name="DrawIO figures",
                output_files=["figures/latex_includes.tex"],
                primary_output="figures/",
            ),
        )
        result = await runner.run_skill(cwd=workspace, extra_params={})
        assert result["success"] is True, result
        pdf = figures / "fig_arch.pdf"
        assert pdf.is_file() and pdf.stat().st_size > 500
        assert (figures / "latex_includes.tex").is_file()
        lineage = workspace / ".host_builds" / "paper-figure-drawio.json"
        assert lineage.is_file()
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload["executor"] == "host_step_runner"

    asyncio.run(go())


def test_host_patent_build_with_relative_workspaces_dir(tmp_path, monkeypatch):
    """Relative WORKSPACES_DIR must not double-join host script input paths."""
    import asyncio
    import os
    import services.state_store as store
    import services.workflow_engine as engine

    # Keep the path relative while redirecting its resolution to pytest-owned storage.
    original_db_path = store.DB_PATH
    original_workspaces_dir = engine.WORKSPACES_DIR
    monkeypatch.chdir(tmp_path)
    rel_root = Path("verification-logs") / "_rel_ws_test"
    rel_root.mkdir(parents=True)
    store.DB_PATH = (rel_root / "db.sqlite").resolve()
    # Intentionally relative: this is the behavior under test.
    engine.WORKSPACES_DIR = Path("verification-logs") / "_rel_ws_test" / "workspaces"
    engine.WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

    async def go():
        await store.init_db()
        wf_id = await engine.create_new_workflow("patent_disclosure", "Rel Path Patent", {}, False)
        ws = engine.WORKSPACES_DIR / wf_id
        draft_dir = ws / "专利交底书"
        draft_dir.mkdir(parents=True, exist_ok=True)
        (draft_dir / "交底书草稿.md").write_text(
            "# Rel Path" + chr(10)*2 + "### 3.2" + chr(10) + "```mermaid" + chr(10) + "flowchart LR" + chr(10) + "A-->B" + chr(10) + "```" + chr(10),
            encoding="utf-8",
        )
        await engine.run_single_step(wf_id, "patent-build")
        docx = (ws / "专利交底书" / "交底书.docx").resolve()
        assert docx.is_file() and docx.stat().st_size > 1000
        db = await store.get_db()
        try:
            step = await (
                await db.execute(
                    "SELECT status,error_message FROM workflow_steps WHERE workflow_id=? AND skill_name=?",
                    (wf_id, "patent-build"),
                )
            ).fetchone()
        finally:
            await db.close()
        assert dict(step)["status"] == "completed", dict(step)

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = original_db_path
        engine.WORKSPACES_DIR = original_workspaces_dir
        import shutil
        shutil.rmtree(rel_root, ignore_errors=True)
