"""Dual Unicode user-data roots: multi-agent collaboration honest fail + persistence.

Without live provider keys the collaboration must fail honestly (no silent mock
success) while still writing durable report artifacts under each root.
"""
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


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
        # Force honest no-key path: clear common provider env if present in shell.
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "VIBE_OPENAI_API_KEY": "",
        "VIBE_ANTHROPIC_API_KEY": "",
    }
    process = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for _ in range(120):
        if process.poll() is not None:
            out = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"backend exited early: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"backend failed to start: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-协作-{label}"
    user.mkdir(parents=True)
    token = f"dual-collab-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, health = _request(port, token, "/api/health")
        assert status == 200 and health.get("status") == "ok", health

        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Collab dual-clean {label}",
                "research_question": "Does multi-agent collab persist honest failures dual-clean?",
                "inclusion_criteria": "durable report under unicode user-data",
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
                "goal": f"Coordinate multi-role packaging dual-clean {label}",
                "roles": ["executor", "reviewer", "editor_ai"],
                "cli_adapters": [],
                "timeout_seconds": 20,
            },
        )
        assert status == 200, collab
        # Without keys: honest failed (not silent success / mock completion).
        assert collab["status"] == "failed", collab
        assert collab["report_path"]
        assert collab["report_sha256"]
        assert len(collab["steps"]) == 3
        assert all(step["status"] == "failed" for step in collab["steps"]), collab["steps"]
        assert collab.get("failure_reason") or any(
            step.get("error") or step.get("detail") for step in collab["steps"]
        )

        report = user / "workspaces" / project_id / collab["report_path"]
        assert report.is_file(), report
        assert any(ord(ch) > 127 for ch in str(report))
        assert hashlib.sha256(report.read_bytes()).hexdigest() == collab["report_sha256"]
        document = json.loads(report.read_text(encoding="utf-8"))
        assert document["status"] == "failed"
        assert document["format_version"] == "agent-collaboration/v1"
        assert str(document.get("generator") or "").startswith("vibe.agent-collaboration")

        status, listed = _request(port, token, f"/api/agents/collaborations?project_id={project_id}")
        assert status == 200 and any(item["id"] == collab["id"] for item in listed)

        status, fetched = _request(port, token, f"/api/agents/collaborations/{collab['id']}")
        assert status == 200 and fetched["id"] == collab["id"]
        assert fetched["status"] == "failed"

        return {
            "label": label,
            "project_id": project_id,
            "collab_id": collab["id"],
            "user_data": str(user),
            "report": str(report),
            "report_sha256": collab["report_sha256"],
            "status": collab["status"],
        }
    finally:
        _stop(process)


def test_dual_clean_agent_collaboration_honest_fail(tmp_path: Path) -> None:
    base = tmp_path / "双干净多Agent协作"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)

    assert run1["project_id"] != run2["project_id"]
    assert run1["collab_id"] != run2["collab_id"]
    assert Path(run1["user_data"]).resolve() != Path(run2["user_data"]).resolve()
    assert Path(run1["report"]).resolve() != Path(run2["report"]).resolve()
    assert "用户数据-协作-1" in run1["user_data"]
    assert "用户数据-协作-2" in run2["user_data"]
    assert run1["status"] == "failed" and run2["status"] == "failed"
    assert Path(run1["report"]).is_file() and Path(run2["report"]).is_file()
    # Independent roots must not share report bytes identity across projects.
    assert run1["report_sha256"] != run2["report_sha256"] or run1["project_id"] != run2["project_id"]
