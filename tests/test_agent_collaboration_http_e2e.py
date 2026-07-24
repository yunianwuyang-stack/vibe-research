"""HTTP E2E: multi-agent collaboration under Unicode user-data without credentials."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, token: str, path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"X-Vibe-Session-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def test_agent_collaboration_http_honest_fail_and_artifact(tmp_path):
    user = tmp_path / "用户数据-协作"
    user.mkdir()
    token = "collab-http"
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
    }
    process = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(100):
            try:
                status, _ = _request(port, token, "/api/health")
                if status == 200:
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("backend failed to start")

        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": "协作 HTTP",
                "research_question": "Can multi-agent collaboration persist honest failures?",
                "inclusion_criteria": "peer reviewed",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        status, collab = _request(
            port,
            token,
            "/api/agents/collaborations",
            "POST",
            {
                "project_id": project_id,
                "goal": "Coordinate multi-role research packaging with independent review",
                "roles": ["executor", "reviewer", "editor_ai"],
                "cli_adapters": [],
                "timeout_seconds": 20,
            },
        )
        assert status == 200, collab
        assert collab["status"] == "failed"
        assert collab["report_path"]
        assert collab["report_sha256"]
        assert len(collab["steps"]) == 3
        assert all(step["status"] == "failed" for step in collab["steps"])

        report = user / "workspaces" / project_id / collab["report_path"]
        assert report.is_file(), report
        assert hashlib.sha256(report.read_bytes()).hexdigest() == collab["report_sha256"]
        document = json.loads(report.read_text(encoding="utf-8"))
        assert document["status"] == "failed"
        assert document["format_version"] == "agent-collaboration/v1"
        assert any(ord(ch) > 127 for ch in str(report))

        status, listed = _request(port, token, f"/api/agents/collaborations?project_id={project_id}")
        assert status == 200, listed
        assert any(item["id"] == collab["id"] for item in listed)

        status, fetched = _request(port, token, f"/api/agents/collaborations/{collab['id']}")
        assert status == 200, fetched
        assert fetched["id"] == collab["id"]
    finally:
        process.terminate()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
