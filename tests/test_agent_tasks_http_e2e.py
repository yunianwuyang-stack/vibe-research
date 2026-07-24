from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from test_golden_path_http_e2e import free_port, request, server, stop


def test_agent_task_http_lifecycle_and_restart_recovery(tmp_path):
    # Self-contained Windows shim: avoid invoking a Python under Unicode paths
    # from a .cmd file (cmd.exe fails to resolve those executable paths).
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    cmd = fake_bin / "codex.cmd"
    cmd.write_text(
        "@echo off\r\n"
        "if \"%1\"==\"--version\" (\r\n"
        "  echo codex-cli test\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        "echo {\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"HTTP_AGENT_OK\"}}\r\n"
        "echo {\"type\":\"turn.completed\",\"usage\":{\"output_tokens\":2}}\r\n"
        "exit /b 0\r\n",
        encoding="ascii",
    )
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
    token = "agent-http-token"
    appdata = tmp_path / "appdata"
    port = free_port()
    process = server(port, token, appdata)
    try:
        status, project = request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": "Agent project",
                "research_question": "Can an Agent summarize evidence?",
                "inclusion_criteria": "read only",
            },
        )
        assert status == 200
        status, task = request(
            port,
            token,
            "/api/agents/tasks",
            "POST",
            {"project_id": project["id"], "adapter": "codex", "prompt": "summarize"},
        )
        assert status == 200, task
        for _ in range(100):
            status, current = request(port, token, f"/api/agents/tasks/{task['id']}")
            if current["status"] not in {"queued", "running", "cancelling"}:
                break
            time.sleep(0.05)
        assert current["status"] == "completed", current
        assert current["result"]["final_text"] == "HTTP_AGENT_OK"
        assert len(current["result"]["artifact_sha256"]) == 64
    finally:
        stop(process)
        os.environ["PATH"] = old_path
    port = free_port()
    process = server(port, token, appdata)
    try:
        status, tasks = request(port, token, f"/api/agents/tasks?project_id={project['id']}")
        assert status == 200 and tasks[0]["id"] == task["id"] and tasks[0]["status"] == "completed"
    finally:
        stop(process)
