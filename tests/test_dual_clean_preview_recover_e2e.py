"""Dual Unicode user-data: project preview survives API process restart.

Chain under test (real UI-facing API → ProjectServerManager → child process
→ .preview-servers.json persistence → lifespan recover_all → stop):

  scaffold code/ FastAPI+static → POST /serve → live HTTP hit
  → kill API process only (child must keep serving)
  → restart API on same VIBE_USER_DATA_ROOT
  → GET /serve/status re-adopts running child
  → live HTTP still returns marker
  → DELETE /serve stops child (terminate_process_tree on recovered PID)

No mock preview process. Proves failure recovery for the editor project-serve
surface under two clean Unicode roots.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))

MAIN_PY = """\
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Vibe Research Preview Recover Probe")
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/api/health")
def health():
    return {"status": "ok", "probe": "vibe-preview-recover-dual-clean"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
"""

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"/><title>Vibe Research Preview Recover</title></head>
<body>
  <h1 id="probe">Vibe Research dual-clean preview recover</h1>
  <p>marker=preview-recover-α</p>
</body>
</html>
"""


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
        with _OPENER.open(req, timeout=60) as response:
            payload = response.read()
            if not payload:
                return response.status, {}
            return response.status, json.loads(payload.decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _plain_get(url: str, timeout: float = 5.0):
    req = Request(url, method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except URLError as error:
        return None, str(error.reason if hasattr(error, "reason") else error)


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    log_path = user_data / "backend-start.log"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        env.pop(key, None)
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
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
            "info",
        ],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._vibe_log_file = log_file  # type: ignore[attr-defined]
    process._vibe_log_path = log_path  # type: ignore[attr-defined]
    last_status = last_body = last_error = None
    for _ in range(200):
        if process.poll() is not None:
            log_file.flush()
            out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            raise AssertionError(f"backend exited early ({process.returncode}): {out[-4000:]}")
        try:
            status, body = _request(port, token, "/api/health")
            last_status, last_body = status, body
            if status == 200:
                return process
        except Exception as exc:  # noqa: BLE001 — startup race
            last_error = repr(exc)
        time.sleep(0.1)
    process.kill()
    log_file.flush()
    out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    raise AssertionError(
        f"backend failed to start last_status={last_status} last_body={last_body} "
        f"last_error={last_error} log={out[-4000:]}"
    )


def _stop(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(10)
    log_file = getattr(process, "_vibe_log_file", None)
    if log_file is not None:
        try:
            log_file.close()
        except Exception:
            pass


def _wait_preview(url: str, *, marker: bytes, timeout: float = 30.0) -> tuple[int, bytes]:
    deadline = time.time() + timeout
    last = (None, b"")
    while time.time() < deadline:
        status, body = _plain_get(url)
        if status == 200 and isinstance(body, (bytes, bytearray)) and marker in body:
            return status, bytes(body)
        last = (
            status,
            body if isinstance(body, (bytes, bytearray)) else str(body).encode(),
        )
        time.sleep(0.2)
    raise AssertionError(
        f"preview never ready url={url} last_status={last[0]} body={last[1][:400]!r}"
    )


def _wait_stopped(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _body = _plain_get(url)
        if status is None or status >= 500 or status == 0:
            return
        # Connection refused / reset surfaces as URLError → status None.
        time.sleep(0.2)
    raise AssertionError(f"preview still responding after stop url={url}")


def _clean_run(label: str, base: Path, *, token_tag: str) -> dict:
    user = base / f"用户数据-预览恢复-{label}"
    user.mkdir(parents=True)
    token = f"dual-preview-rec-{token_tag}"
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
                "title": f"Preview recover dual-clean {label}",
                "research_question": "Does project serve recover after API restart?",
                "inclusion_criteria": "preview PID identity + state file + stop",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        status, wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "one_sentence_project",
                "title": f"Preview recover scaffold {label}",
                "params": {
                    "one_sentence": f"preview recover dual-clean {label}",
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, wf
        wf_id = wf["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert any(ord(ch) > 127 for ch in str(user))
        assert any(ord(ch) > 127 for ch in str(workspace))

        code = workspace / "code"
        static = code / "static"
        static.mkdir(parents=True, exist_ok=True)
        (code / "main.py").write_text(MAIN_PY, encoding="utf-8")
        (static / "index.html").write_text(INDEX_HTML, encoding="utf-8")

        status, serve = _request(
            port,
            token,
            f"/api/editor/{wf_id}/serve",
            "POST",
            {"mode": "both"},
        )
        assert status == 200, serve
        servers = serve.get("servers") or []
        assert servers, serve
        backend = next(
            (row for row in servers if row.get("kind") == "backend" and row.get("url")),
            servers[0],
        )
        assert backend.get("status") in {"starting", "already_running"}, serve
        preview_url = str(backend.get("url") or "").rstrip("/")
        assert preview_url.startswith("http://127.0.0.1:"), serve
        preview_port = int(backend["port"])
        marker = b"preview-recover"

        http_status, html_bytes = _wait_preview(preview_url + "/", marker=marker)
        assert http_status == 200
        assert b"preview-recover" in html_bytes

        state_path = workspace / ".preview-servers.json"
        deadline = time.time() + 10
        while time.time() < deadline and not state_path.is_file():
            time.sleep(0.1)
        assert state_path.is_file(), "preview state must persist for recover_all"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state.get("version") == 1
        assert state.get("wf_id") == wf_id
        backend_row = (state.get("servers") or {}).get("backend") or {}
        child_pid = int(backend_row["pid"])
        assert child_pid > 0
        assert int(backend_row["port"]) == preview_port

        # Kill only the API process; preview child must keep serving.
        _stop(process)
        process = None
        still_status, still_body = _wait_preview(
            preview_url + "/",
            marker=marker,
            timeout=15.0,
        )
        assert still_status == 200 and marker in still_body

        # Restart API against the same Unicode user-data root.
        process = _server(port, token, user)
        status, health2 = _request(port, token, "/api/health")
        assert status == 200 and health2.get("status") == "ok", health2

        status, status_body = _request(port, token, f"/api/editor/{wf_id}/serve/status")
        assert status == 200, status_body
        recovered = status_body.get("backend") or status_body.get("frontend")
        assert recovered is not None, status_body
        assert recovered.get("running") is True, status_body
        assert int(recovered.get("port") or 0) == preview_port, status_body
        assert str(recovered.get("url") or "").rstrip("/") == preview_url

        http_status, html_after = _wait_preview(preview_url + "/", marker=marker, timeout=15.0)
        assert http_status == 200 and marker in html_after

        # Stop via recovered PID path (no ProcessSupervisor task_id after recover).
        status, stopped = _request(
            port,
            token,
            f"/api/editor/{wf_id}/serve",
            "DELETE",
        )
        assert status == 200, stopped
        assert stopped.get("stopped"), stopped
        _wait_stopped(preview_url + "/")

        status, after = _request(port, token, f"/api/editor/{wf_id}/serve/status")
        assert status == 200, after
        assert after.get("backend") is None and after.get("frontend") is None, after
        assert not state_path.is_file() or not json.loads(
            state_path.read_text(encoding="utf-8")
        ).get("servers")

        return {
            "label": label,
            "project_id": project_id,
            "wf_id": wf_id,
            "user_data": str(user),
            "workspace": str(workspace),
            "preview_url": preview_url,
            "child_pid": child_pid,
            "preview_port": preview_port,
        }
    finally:
        _stop(process)


def test_dual_clean_preview_serve_recovers_after_api_restart(tmp_path: Path) -> None:
    base = tmp_path / "预览恢复双根"
    base.mkdir(parents=True)
    run1 = _clean_run("甲", base, token_tag="a")
    run2 = _clean_run("乙", base, token_tag="b")

    assert run1["project_id"] != run2["project_id"]
    assert run1["wf_id"] != run2["wf_id"]
    assert Path(run1["user_data"]).resolve() != Path(run2["user_data"]).resolve()
    assert "用户数据-预览恢复" in run1["user_data"]
    assert "用户数据-预览恢复" in run2["user_data"]
    assert any(ord(ch) > 127 for ch in run1["user_data"])
    assert any(ord(ch) > 127 for ch in run2["user_data"])
    assert run1["preview_port"] != run2["preview_port"] or run1["child_pid"] != run2["child_pid"]
