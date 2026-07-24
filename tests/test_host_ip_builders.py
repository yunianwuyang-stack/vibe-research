"""Host IP builders produce real patent/copyright artifacts without LLMs."""
from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_host_ip_builders_generate_complete_packages(tmp_path):
    from services.host_ip_builders import (
        build_copyright_draft_package,
        build_patent_disclosure_draft,
        build_software_copyright_materials,
    )

    ws = tmp_path / "ws"
    code = ws / "code"
    code.mkdir(parents=True)
    (code / "main.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    (code / "service.ts").write_text("export const ok = true;\n", encoding="utf-8")

    soft = build_software_copyright_materials(
        ws, title="Vibe 软著测试件", params={"software_version": "V1.2"},
    )
    assert soft["success"] is True
    assert soft["source_files"] >= 2
    for name in (
        "PRODUCT_OVERVIEW.md",
        "USER_MANUAL.md",
        "SOURCE_CODE_INDEX.md",
        "REGISTRATION_CHECKLIST.md",
    ):
        path = ws / "software-copyright" / name
        assert path.is_file() and path.stat().st_size > 80
    assert "main.py" in (ws / "software-copyright" / "SOURCE_CODE_INDEX.md").read_text(encoding="utf-8")

    copyright = build_copyright_draft_package(
        ws, title="Vibe 软著正式包", params={"software_version": "V1.2"},
    )
    assert copyright["success"] is True
    draft = ws / "软件著作权申请资料" / "草稿"
    assert (draft / "申请表信息.md").is_file()
    assert "Vibe 软著正式包" in (draft / "申请表信息.md").read_text(encoding="utf-8")
    assert (draft / "代码-前30页.md").is_file()
    assert (draft / "代码-后30页.md").is_file()
    assert (draft / "操作手册.md").is_file()
    assert json.loads((draft / "业务理解.json").read_text(encoding="utf-8"))["user_confirmed"] is True

    patent = build_patent_disclosure_draft(
        ws, title="一种可审计科研工作流方法", params={"problem": "缺少产物血缘"},
    )
    assert patent["success"] is True
    draft_md = ws / "专利交底书" / "交底书草稿.md"
    text = draft_md.read_text(encoding="utf-8")
    assert "```mermaid" in text
    assert "可审计" in text
    assert draft_md.stat().st_size >= 500


def test_host_runner_ip_drafts_and_software_copyright(tmp_path, monkeypatch):
    import services.state_store as store
    import services.workflow_engine as engine
    from services.workflow_engine import StepDef, _HostStepRunner

    store.DB_PATH = tmp_path / "ip_host.db"
    engine.WORKSPACES_DIR = tmp_path / "workspaces"
    engine.WORKSPACES_DIR.mkdir()

    async def go():
        await store.init_db()

        soft_id = await engine.create_new_workflow(
            "software_copyright", "Host Soft Copyright", {"software_version": "V2.0"}, False,
        )
        soft_ws = engine.WORKSPACES_DIR / soft_id
        (soft_ws / "code").mkdir()
        (soft_ws / "code" / "app.py").write_text("print('vibe')\n", encoding="utf-8")
        soft_runner = _HostStepRunner(
            "software_copyright",
            StepDef(
                skill_name="software-copyright",
                display_name="软著材料清点与撰写",
                output_files=["software-copyright/USER_MANUAL.md"],
                primary_output="software-copyright/USER_MANUAL.md",
            ),
        )
        soft_result = await soft_runner.run_skill(cwd=soft_ws, extra_params={"software_version": "V2.0"})
        assert soft_result["success"] is True, soft_result
        assert (soft_ws / "software-copyright" / "PRODUCT_OVERVIEW.md").is_file()
        soft_lineage = soft_ws / ".host_builds" / "software-copyright.json"
        assert soft_lineage.is_file()
        assert json.loads(soft_lineage.read_text(encoding="utf-8"))["executor"] == "host_step_runner"

        patent_id = await engine.create_new_workflow(
            "patent_disclosure", "Host Patent Full", {}, False,
        )
        patent_ws = engine.WORKSPACES_DIR / patent_id
        draft_runner = _HostStepRunner(
            "patent_disclosure",
            StepDef(
                skill_name="patent-draft",
                display_name="起草技术交底书",
                output_files=["专利交底书/交底书草稿.md"],
                primary_output="专利交底书/交底书草稿.md",
            ),
        )
        draft_result = await draft_runner.run_skill(cwd=patent_ws, extra_params={})
        assert draft_result["success"] is True, draft_result
        build_runner = _HostStepRunner(
            "patent_disclosure",
            StepDef(
                skill_name="patent-build",
                display_name="渲染图示并导出 Word",
                output_files=["专利交底书/交底书.docx"],
                primary_output="专利交底书/交底书.docx",
            ),
        )
        build_result = await build_runner.run_skill(cwd=patent_ws, extra_params={})
        assert build_result["success"] is True, build_result
        docx = patent_ws / "专利交底书" / "交底书.docx"
        assert docx.is_file() and docx.stat().st_size > 1000
        with zipfile.ZipFile(docx) as archive:
            assert "word/document.xml" in archive.namelist()

        copyright_id = await engine.create_new_workflow(
            "copyright_material", "Host Copyright Full", {"software_name": "主机软著"}, False,
        )
        copyright_ws = engine.WORKSPACES_DIR / copyright_id
        (copyright_ws / "code").mkdir()
        (copyright_ws / "code" / "lib.py").write_text("x=1\n", encoding="utf-8")
        c_draft = _HostStepRunner(
            "copyright_material",
            StepDef(
                skill_name="copyright-draft",
                display_name="起草申请资料",
                output_files=["软件著作权申请资料/草稿/申请表信息.md"],
                primary_output="软件著作权申请资料/草稿/",
            ),
        )
        c_draft_result = await c_draft.run_skill(
            cwd=copyright_ws, extra_params={"software_name": "主机软著", "software_version": "V1.0"},
        )
        assert c_draft_result["success"] is True, c_draft_result
        c_build = _HostStepRunner(
            "copyright_material",
            StepDef(
                skill_name="copyright-build",
                display_name="生成正式 Word/TXT",
                output_files=["软件著作权申请资料/正式资料/生成报告.md"],
                primary_output="软件著作权申请资料/正式资料/",
            ),
        )
        c_build_result = await c_build.run_skill(cwd=copyright_ws, extra_params={})
        assert c_build_result["success"] is True, c_build_result
        formal = copyright_ws / "软件著作权申请资料" / "正式资料"
        assert formal.is_dir()
        assert (formal / "申请表信息.txt").is_file()
        assert any(path.suffix.lower() == ".docx" for path in formal.glob("*.docx"))

    asyncio.run(go())
