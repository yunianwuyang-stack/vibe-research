"""Run the local relay + llm_client + ClaudeRunner integration matrix."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main() -> dict:
    from services import llm_client
    from services.claude_runner import ClaudeRunner

    port = free_port()
    relay = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "mock_relay.py"), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    base_url = f"http://127.0.0.1:{port}/v1"
    settings = {
        "executor_base_url": base_url, "executor_api_key": "executor-key", "executor_model_id": "mock-text",
        "reviewer_base_url": base_url, "reviewer_api_key": "reviewer-key", "reviewer_model_id": "mock-text",
        "editor_ai_base_url": base_url, "editor_ai_api_key": "editor-key", "editor_ai_model_id": "mock-vision",
        "claude_bin": sys.executable,
    }

    async def fake_settings():
        return dict(settings)

    old_settings = llm_client.get_all_settings
    llm_client.get_all_settings = fake_settings
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)

        results = {}
        results["text"] = await llm_client.call_llm("executor", "hello relay", timeout=2)
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "vision.png"
            image.write_bytes(b"\x89PNG\r\nmock")
            results["vision"] = await llm_client.describe_image(str(image), "integration context")

        try:
            await llm_client.call_llm("unknown", "x", timeout=1)
        except Exception as exc:
            results["unknown_agent"] = f"{type(exc).__name__}: {exc}"

        settings["executor_model_id"] = "mock-http-error"
        try:
            await llm_client.call_llm("executor", "x", timeout=1)
        except Exception as exc:
            results["http_error"] = f"{type(exc).__name__}: {exc}"

        settings["executor_model_id"] = "mock-malformed"
        try:
            await llm_client.call_llm("executor", "x", timeout=1)
        except Exception as exc:
            results["malformed"] = f"{type(exc).__name__}: {exc}"

        settings["executor_model_id"] = "mock-timeout"
        try:
            await llm_client.call_llm("executor", "x", timeout=1)
        except Exception as exc:
            results["timeout"] = f"{type(exc).__name__}: {exc}"

        settings["executor_model_id"] = "mock-text"
        results["connection"] = await llm_client.test_connection("executor")
        results["env"] = await llm_client.get_env_for_subprocess()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "skills" / "mock-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("Mock $ARGUMENTS", encoding="utf-8")
            import services.claude_runner as runner_module
            old_skills_dir = runner_module.SKILLS_DIR
            runner_module.SKILLS_DIR = root / "skills"
            output = []
            runner = ClaudeRunner()
            runner.skills_dir = root / "skills"
            os.environ["MOCK_CLAUDE_MODE"] = "success"
            try:
                runner.claude_bin = str(ROOT / "tests" / "mock_claude.cmd")
                results["claude_success"] = await runner.run_skill(
                    "mock-skill", "ARGS", root, "wf-relay", on_output=lambda line: _capture(output, line),
                    inactivity_timeout=2, overall_timeout=5, resume_session_id="resume-old",
                )
                results["claude_output_callbacks"] = output
                os.environ["MOCK_CLAUDE_MODE"] = "error"
                results["claude_error"] = await runner.run_skill(
                    "mock-skill", "ARGS", root, "wf-error", inactivity_timeout=2, overall_timeout=5,
                )
                os.environ["MOCK_CLAUDE_MODE"] = "timeout"
                results["claude_timeout"] = await runner.run_skill(
                    "mock-skill", "ARGS", root, "wf-timeout", inactivity_timeout=1, overall_timeout=2,
                )
            finally:
                runner_module.SKILLS_DIR = old_skills_dir
                os.environ.pop("MOCK_CLAUDE_MODE", None)

        assert results["text"].startswith("TEXT_OK")
        assert results["vision"].startswith("VISION_OK blocks=1")
        assert "未知 agent" in results["unknown_agent"]
        assert "HTTP 503" in results["http_error"]
        assert "响应格式错误" in results["malformed"]
        assert "Timeout" in results["timeout"] or "timed out" in results["timeout"]
        assert results["connection"]["ok"] is True and "message" in results["connection"]
        assert results["claude_success"]["success"] is True
        assert results["claude_success"]["result"].startswith("CLI_OK stdin=")
        assert results["claude_success"]["session_id"] == "session-mock-1"
        assert results["claude_error"]["returncode"] == 7
        assert results["claude_timeout"]["success"] is False
        return results
    finally:
        llm_client.get_all_settings = old_settings
        relay.terminate()
        try:
            relay.wait(timeout=5)
        except subprocess.TimeoutExpired:
            relay.kill()


async def _capture(output: list[str], line: str) -> None:
    output.append(line)


if __name__ == "__main__":
    report = asyncio.run(main())
    print(json.dumps(report, ensure_ascii=False, indent=2))
