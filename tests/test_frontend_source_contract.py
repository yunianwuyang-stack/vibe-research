from pathlib import Path
import re


def test_clean_room_frontend_has_build_and_accessibility_contract():
    root = Path(__file__).resolve().parents[1] / "frontend"
    text = (root / "src/main.tsx").read_text(encoding="utf-8")
    assert (root / "package.json").exists()
    # Current product shell: settings doctor + workflow catalog, not the old
    # English onboarding copy that predated the Chinese research workbench.
    assert "设置与连接" in text
    assert "环境诊断" in text
    assert "智能工作流" in text
    assert "templateCategories" in text
    css = (root / "src/styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css
    assert "@media(max-width:1024px)" in css or "@media (max-width: 1024px)" in css


def test_template_catalog_exposes_academic_and_competition_surface():
    root = Path(__file__).resolve().parents[1] / "frontend"
    text = (root / "src/main.tsx").read_text(encoding="utf-8")
    academic = re.search(r'id:\s*"academic"[\s\S]*?templates:\s*\[([\s\S]*?)\],', text)
    competition = re.search(r'id:\s*"competition"[\s\S]*?templates:\s*\[([\s\S]*?)\],', text)
    assert academic and competition
    academic_templates = re.findall(r'"([a-z0-9_]+)"', academic.group(1))
    competition_templates = re.findall(r'"([a-z0-9_]+)"', competition.group(1))
    assert academic_templates[0] == "paper_writing"
    assert "thesis_proposal" in academic_templates
    assert competition_templates[0] == "comp_tianfu"
    assert competition_templates[-1] == "comp_certcup_en"
    assert len(competition_templates) == 22


def test_editor_page_exposes_reviewable_agent_surface():
    """UI must surface the real editor agent stage/apply loop, not hide it."""
    root = Path(__file__).resolve().parents[1] / "frontend"
    text = (root / "src/main.tsx").read_text(encoding="utf-8")
    assert "编辑代理" in text
    assert "/ai-agent" in text
    assert "/ai-agent-apply" in text
    assert "/ai-agent-discard" in text
    assert "/ai-agent-undo" in text
    assert "agent_provider_unavailable" in text
    assert "生成提案" in text
    assert "应用提案" in text


def test_editor_page_exposes_ai_edit_chat_history_and_run_script():
    """Editor must wire the three still-missing API surfaces into the page."""
    root = Path(__file__).resolve().parents[1] / "frontend"
    text = (root / "src/main.tsx").read_text(encoding="utf-8")
    assert "AI 编辑与聊天历史" in text
    assert "/ai-edit" in text
    assert "/chat-history" in text
    assert "工作区脚本执行" in text
    assert "/run-script" in text
    assert "生成 AI 编辑" in text
    assert "运行脚本" in text
    assert "清空聊天历史" in text


def test_editor_page_exposes_mermaid_export_surface():
    root = Path(__file__).resolve().parents[1] / "frontend"
    text = (root / "src/main.tsx").read_text(encoding="utf-8")
    assert "Mermaid 导出" in text
    assert "/mermaid-export" in text
    assert "MermaidExportPanel" in text
    assert "offline mermaid.min.js" in text
