"""Dual Unicode user-data roots: grad_project host chain (req→design→code→selfcheck)."""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
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


def _request(
    port: int,
    token: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    *,
    raw: bool = False,
    timeout: int = 60,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={
            "X-Vibe-Session-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = response.read()
            if raw:
                return response.status, payload
            return response.status, json.loads(payload.decode("utf-8"))
    except HTTPError as error:
        payload = error.read()
        if raw:
            return error.code, payload
        text = payload.decode("utf-8")
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
    )
    for _ in range(100):
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    raise AssertionError(f"backend failed to start for {user_data}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(port: int, token: str, wf_id: str, seconds: int = 240) -> dict:
    terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
    last: dict = {}
    for _ in range(max(1, seconds * 2)):
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        last = detail
        if str(detail.get("status") or "") in terminal:
            return detail
        time.sleep(0.5)
    return last


def _approve_if_waiting(port: int, token: str, wf_id: str, detail: dict) -> dict:
    current = detail
    for _ in range(12):
        if str(current.get("status") or "") != "waiting_checkpoint":
            return current
        status, _ = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/checkpoint",
            "POST",
            {"action": "approve", "data": {"feedback": "dual-clean grad approve"}},
        )
        assert status == 200
        current = _wait_terminal(port, token, wf_id, seconds=120)
    return current


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-毕设-{label}"
    user.mkdir(parents=True)
    token = f"dual-grad-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"毕设 dual clean {label}",
                "research_question": "Can grad_project host chain complete without cloud keys?",
                "inclusion_criteria": "runnable host scaffold",
            },
        )
        assert status == 200, project

        status, workflow = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "grad_project",
                "title": f"证据门禁助手-{label}",
                "params": {
                    "idea": f"一句话生成可审计科研助手 dual-clean {label}",
                    "project_type": "fullstack",
                    "skip_report": True,
                },
                "enable_checkpoints": False,
                "project_id": project["id"],
            },
        )
        assert status == 200, workflow
        wf_id = workflow["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert any(ord(ch) > 127 for ch in str(workspace))

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _approve_if_waiting(port, token, wf_id, _wait_terminal(port, token, wf_id, seconds=300))
        assert final.get("status") == "completed", final

        req = workspace / "REQUIREMENTS.md"
        design = workspace / "DESIGN.md"
        schema = workspace / "schema.sql"
        main_py = workspace / "code" / "backend" / "main.py"
        index = workspace / "code" / "frontend" / "index.html"
        run_md = workspace / "RUN.md"
        report = workspace / "TEST_REPORT.md"
        for path in (req, design, schema, main_py, index, run_md, report):
            assert path.is_file() and path.stat().st_size >= 40, path
        assert req.stat().st_size >= 1500
        assert design.stat().st_size >= 2000
        compile(main_py.read_text(encoding="utf-8"), str(main_py), "exec")
        assert "FastAPI" in main_py.read_text(encoding="utf-8")

        for skill in ("dev-requirement", "dev-design", "dev-code", "dev-selfcheck"):
            lineage = workspace / ".host_builds" / f"{skill}.json"
            assert lineage.is_file(), lineage
            payload = json.loads(lineage.read_text(encoding="utf-8"))
            assert payload.get("executor") == "host_step_runner"
            assert payload.get("skill_name") == skill

        status, export_bytes = _request(port, token, f"/api/workflows/{wf_id}/export", raw=True)
        assert status == 200, export_bytes[:200]
        assert export_bytes[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
            names = archive.namelist()
            assert any(n.replace("\\", "/").endswith("code/backend/main.py") for n in names), names[:40]
            assert any(n.replace("\\", "/").endswith("TEST_REPORT.md") for n in names), names[:40]

        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/recover",
            "POST",
            {"reason": "dual-clean grad recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        return {
            "label": label,
            "workflow_id": wf_id,
            "workspace_dir": str(workspace),
            "main_py_bytes": main_py.stat().st_size,
            "export_ok": True,
            "recovery_status": recover_status,
        }
    finally:
        _stop(process)


def test_dual_clean_grad_project_host_roots(tmp_path):
    base = tmp_path / "dual-clean-grad"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)
    assert run1["workflow_id"] != run2["workflow_id"]
    assert Path(run1["workspace_dir"]).resolve() != Path(run2["workspace_dir"]).resolve()
    assert run1["main_py_bytes"] >= 200 and run2["main_py_bytes"] >= 200
    assert run1["export_ok"] and run2["export_ok"]
    assert "用户数据-毕设-1" in run1["workspace_dir"]
    assert "用户数据-毕设-2" in run2["workspace_dir"]
