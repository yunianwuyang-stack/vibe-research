"""OpenAI-compatible Chat Completions tool loop for workflow skills."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from services.claude_runner import _skill_parameter_environment
from services.openai_responses_agent import OpenAICompatibleAgent, chat_tool_definitions


def test_chat_tool_definitions_cover_workspace_surface():
    names = {item["function"]["name"] for item in chat_tool_definitions()}
    assert names == {
        "read",
        "write",
        "replace",
        "list",
        "search",
        "mkdir",
        "run_command",
    }


def test_skill_env_exports_project_and_ip_aliases():
    env = _skill_parameter_environment(
        {
            "project_type": "fullstack",
            "tech_frontend": "React",
            "feature_requirements": "login\ncheckout",
            "software_name": "Campus Trade",
            "case_name": "一种匹配方法",
            "skip_report": False,
        }
    )
    assert env["PROJECT_TYPE"] == "fullstack"
    assert env["TECH_FRONTEND"] == "React"
    assert env["FEATURE_REQUIREMENTS"] == "login\ncheckout"
    assert env["SOFTWARE_NAME"] == "Campus Trade"
    assert env["CASE_NAME"] == "一种匹配方法"
    assert env["SKILL_SKIP_REPORT"] == "False"


def test_openai_compatible_agent_runs_tool_loop(tmp_path: Path):
    calls: list[dict] = []

    def transport(payload: dict) -> dict:
        calls.append(payload)
        turn = len(calls)
        if turn == 1:
            assert payload["tools"]
            assert payload["tool_choice"] == "auto"
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_write_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write",
                                        "arguments": json.dumps(
                                            {
                                                "path": "RESULT.md",
                                                "content": "# ok\nfrom chat agent\n",
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        # Second turn receives tool result and finishes.
        assert any(item.get("role") == "tool" for item in payload["messages"])
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "done writing RESULT.md",
                    }
                }
            ]
        }

    agent = OpenAICompatibleAgent(
        base_url="https://example.test/v1",
        api_key="sk-test",
        model_id="gpt-4o",
        request_func=transport,
        max_turns=4,
    )

    async def _run():
        return await agent.run(
            prompt="Write RESULT.md then stop.",
            cwd=tmp_path,
            workflow_id="chat-agent-test",
            inactivity_timeout=10,
            overall_timeout=20,
        )

    result = asyncio.run(_run())
    assert result["success"] is True
    assert result["returncode"] == 0
    assert "done writing RESULT.md" in result["result"]
    assert (tmp_path / "RESULT.md").read_text(encoding="utf-8").startswith("# ok")
    assert len(calls) == 2


def test_claude_runner_routes_openai_compatible_to_chat_agent(tmp_path: Path, monkeypatch):
    import services.claude_runner as claude_runner
    import services.llm_client as llm_client
    from services.openai_responses_agent import OpenAICompatibleAgent

    seen: dict[str, object] = {}

    class _FakeAgent:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        async def run(self, **kwargs):
            seen["run"] = kwargs
            (Path(kwargs["cwd"]) / "OUT.md").write_text("routed\n", encoding="utf-8")
            return {
                "success": True,
                "stdout": "routed",
                "stderr": "",
                "returncode": 0,
                "result": "routed",
                "session_id": None,
            }

        async def cancel(self):
            return None

    monkeypatch.setattr(
        "services.openai_responses_agent.OpenAICompatibleAgent",
        _FakeAgent,
    )

    async def _fake_settings():
        return {
            "executor_provider": "openai_compatible",
            "executor_base_url": "https://share-api.com/v1",
            "executor_api_key": "sk-live",
            "executor_model_id": "gpt-4o",
            "executor_temperature": "0.2",
            "executor_top_p": "1.0",
            "executor_max_tokens": "1024",
        }

    async def _fake_env():
        return {}

    # Ensure skill runtime preflight can locate helpers and shared scripts.
    monkeypatch.setattr(claude_runner, "REVIEWER_SCRIPT", str(tmp_path / "reviewer.py"))
    monkeypatch.setattr(claude_runner, "SCHOLAR_SCRIPT", str(tmp_path / "scholar.py"))
    (tmp_path / "reviewer.py").write_text("# helper\n", encoding="utf-8")
    (tmp_path / "scholar.py").write_text("# helper\n", encoding="utf-8")
    isolated_skills = tmp_path / "skills"
    monkeypatch.setattr(claude_runner, "SKILLS_DIR", isolated_skills)
    shared = isolated_skills / "shared-scripts"
    if not shared.is_dir():
        # Tests may run against a thin fixture tree; create a local mount source.
        shared.mkdir(parents=True, exist_ok=True)
        (shared / "noop.py").write_text("print('ok')\n", encoding="utf-8")

    skill_dir = Path(claude_runner.SKILLS_DIR) / "idea-discovery"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# idea\nWrite IDEA.md\n", encoding="utf-8")

    old_settings = llm_client.get_all_settings
    old_env = llm_client.get_env_for_subprocess
    llm_client.get_all_settings = _fake_settings
    llm_client.get_env_for_subprocess = _fake_env
    try:
        runner = claude_runner.ClaudeRunner()

        async def _exercise():
            return await runner.run_skill(
                skill_name="idea-discovery",
                arguments="routing",
                cwd=tmp_path,
                workflow_id="route-compatible",
                inactivity_timeout=5,
                overall_timeout=10,
                extra_params={"project_type": "cli", "tech_lang": "Python"},
            )

        result = asyncio.run(_exercise())
    finally:
        llm_client.get_all_settings = old_settings
        llm_client.get_env_for_subprocess = old_env

    assert result["success"] is True
    assert seen["kwargs"]["model_id"] == "gpt-4o"
    assert isinstance(seen["run"], dict)
    assert (tmp_path / "OUT.md").read_text(encoding="utf-8") == "routed\n"
    # Sanity: the production class still exists for import contracts.
    assert OpenAICompatibleAgent is not None
