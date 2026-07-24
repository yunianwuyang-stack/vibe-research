"""Drive the packaged Claude Code CLI through the local Anthropic SSE relay."""
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

    packaged_root = ROOT
    claude_exe = packaged_root / "runtime" / "node" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    if not claude_exe.exists():
        claude_exe = packaged_root / "runtime" / "node" / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    if not claude_exe.exists():
        raise FileNotFoundError(claude_exe)

    port = free_port()
    temp = Path(tempfile.mkdtemp(prefix="vibe-bundled-relay-"))
    try:
        relay_log = temp / "requests.jsonl"
        relay_env = dict(os.environ)
        relay_env["MOCK_RELAY_LOG"] = str(relay_log)
        relay = subprocess.Popen(
            [sys.executable, str(ROOT / "tests" / "mock_relay.py"), "--port", str(port)],
            env=relay_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        settings = {
            "executor_base_url": f"http://127.0.0.1:{port}",
            "executor_api_key": "bundled-cli-test-key",
            "executor_model_id": "claude-sonnet-4-5-20250929",
        }

        async def fake_settings():
            return dict(settings)

        old_settings = llm_client.get_all_settings
        old_env = {key: os.environ.get(key) for key in (
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING",
        )}
        llm_client.get_all_settings = fake_settings
        os.environ["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        os.environ["DISABLE_TELEMETRY"] = "1"
        os.environ["DISABLE_ERROR_REPORTING"] = "1"
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.05)

            skills = temp / "skills" / "bundled-relay-probe"
            skills.mkdir(parents=True)
            (skills / "SKILL.md").write_text(
                "Reply once with a concise confirmation. Do not call tools. Input: $ARGUMENTS",
                encoding="utf-8",
            )
            import services.claude_runner as runner_module
            old_skills_dir = runner_module.SKILLS_DIR
            runner_module.SKILLS_DIR = temp / "skills"
            runner = ClaudeRunner()
            runner.claude_bin = str(claude_exe)
            runner.skills_dir = temp / "skills"
            callbacks: list[str] = []

            async def capture(line: str) -> None:
                callbacks.append(line)

            try:
                result = await runner.run_skill(
                    "bundled-relay-probe",
                    "bundled CLI local relay",
                    temp,
                    "bundled-relay-wf",
                    on_output=capture,
                    inactivity_timeout=15,
                    overall_timeout=45,
                )
            finally:
                runner_module.SKILLS_DIR = old_skills_dir

            requests = []
            if relay_log.exists():
                requests = [json.loads(line) for line in relay_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            report = {
                "claude_exe": str(claude_exe),
                "relay_base_url": settings["executor_base_url"],
                "result": result,
                "callbacks": callbacks,
                "requests": requests,
            }
            assert result["success"] is True, report
            assert "BUNDLED_CLAUDE_RELAY_OK" in result.get("result", ""), report
            assert any("/messages" in request["path"] for request in requests), report
            return report
        finally:
            llm_client.get_all_settings = old_settings
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            relay.terminate()
            try:
                relay.wait(timeout=5)
            except subprocess.TimeoutExpired:
                relay.kill()
    finally:
        # Some Claude CLI builds release Windows directory handles slightly
        # after process exit; cleanup is best-effort and never weakens assertions.
        import shutil
        for _ in range(10):
            try:
                shutil.rmtree(temp)
                break
            except PermissionError:
                await asyncio.sleep(0.1)


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
