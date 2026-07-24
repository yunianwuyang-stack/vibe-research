"""Dual Unicode user-data: editor file lifecycle + local project serve.

Proves UI-observable editor surface end-to-end under two clean roots:
create → write → preview-html → stats → download → list → delete,
then scaffold code/ FastAPI+static → POST serve → live HTTP hit → status → stop.

No mock preview process; uses real uvicorn child via ProjectServerManager.
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
from urllib.parse import quote
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

app = FastAPI(title="Vibe Research Preview Probe")
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/api/health")
def health():
    return {"status": "ok", "probe": "vibe-preview-dual-clean"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
"""

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"/><title>Vibe Research Preview</title></head>
<body>
  <h1 id="probe">Vibe Research dual-clean preview</h1>
  <p>Unicode path serve probe</p>
</body>
</html>
"""

NOTES_MD = (
    "# 编辑器文件链路\n\n"
    "Dual-clean Unicode file preview probe for **Vibe Research**.\n\n"
    "包含中文路径与产物血缘验证标记：`file-preview-marker-α`。\n"
)


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
    timeout: float = 180,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"X-Vibe-Session-Token": token, "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=timeout) as response:
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
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
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


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()
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
        last = (status, body if isinstance(body, (bytes, bytearray)) else str(body).encode())
        time.sleep(0.2)
    raise AssertionError(f"preview never ready url={url} last_status={last[0]} body={last[1][:400]!r}")


def _clean_run(label: str, base: Path, *, token_tag: str) -> dict:
    user = base / f"用户数据-编辑器预览-{label}"
    user.mkdir(parents=True)
    # Session token is an HTTP header → ASCII only; Unicode lives in paths/titles.
    token = f"dual-editor-serve-{token_tag}"
    port = _free_port()
    process = _server(port, token, user)
    wf_id: str | None = None
    try:
        status, health = _request(port, token, "/api/health")
        assert status == 200 and health.get("status") == "ok", health

        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Editor serve dual-clean {label}",
                "research_question": "Do dual-clean roots preview editor files and code/ projects?",
                "inclusion_criteria": "editor API + ProjectServerManager only",
            },
        )
        assert status == 200, project

        status, workflow = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "idea_discovery",
                "title": f"编辑器与预览 {label}",
                "params": {"topic": f"editor-serve-dual-{label}"},
                "enable_checkpoints": True,
                "project_id": project["id"],
            },
        )
        assert status == 200, workflow
        wf_id = workflow["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert user.resolve() in workspace.resolve().parents or str(user.resolve()) in str(
            workspace.resolve()
        )
        assert any(ord(ch) > 127 for ch in str(workspace))

        notes_path = "notes/预览探针.md"
        q_notes = quote(notes_path, safe="/")
        status, created = _request(
            port,
            token,
            f"/api/editor/{wf_id}/create-file",
            "POST",
            {"path": notes_path},
        )
        assert status == 200, created

        status, saved = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {"path": notes_path, "content": NOTES_MD},
        )
        assert status == 200 and saved.get("ok") is True, saved

        status, read_body = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file?path={q_notes}",
        )
        assert status == 200, read_body
        assert "file-preview-marker-α" in read_body.get("content", "")

        status, preview = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file-preview-html?path={q_notes}",
        )
        assert status == 200, preview
        html = preview.get("html") or ""
        assert "<pre>" in html
        assert "file-preview-marker" in html
        assert "Vibe Research" in html

        status, stats = _request(
            port,
            token,
            f"/api/editor/{wf_id}/stats?path={q_notes}",
        )
        assert status == 200, stats
        assert int(stats.get("files", 0)) >= 1
        assert int(stats.get("characters", 0)) >= len(NOTES_MD) - 5

        status, download = _request(
            port,
            token,
            f"/api/editor/{wf_id}/download?path={q_notes}",
            raw=True,
        )
        assert status == 200, download
        assert b"file-preview-marker" in download

        status, listing = _request(port, token, f"/api/editor/{wf_id}/files")
        assert status == 200, listing
        paths = {item.get("path") for item in listing.get("files", [])}
        assert notes_path in paths or notes_path.replace("\\", "/") in paths

        # Scaffold runnable code/ project via editor writes (UI-equivalent).
        for rel, content in (
            ("code/main.py", MAIN_PY),
            ("code/index.html", INDEX_HTML),
            ("code/static/index.html", INDEX_HTML),
        ):
            status, body = _request(
                port,
                token,
                f"/api/editor/{wf_id}/file",
                "PUT",
                {"path": rel, "content": content},
            )
            assert status == 200 and body.get("ok") is True, (rel, body)
            assert (workspace / rel).is_file()

        status, serve = _request(
            port,
            token,
            f"/api/editor/{wf_id}/serve",
            "POST",
            {"mode": "both"},
            timeout=60,
        )
        assert status == 200, serve
        servers = serve.get("servers") or []
        assert servers, serve
        backend = next((s for s in servers if s.get("kind") == "backend"), servers[0])
        assert backend.get("status") in {"starting", "already_running"}, serve
        preview_url = backend.get("url")
        assert preview_url and preview_url.startswith("http://127.0.0.1:"), serve

        # Live child process responds with real HTML + API (not mock).
        http_status, html_bytes = _wait_preview(
            preview_url.rstrip("/") + "/",
            marker=b"Vibe Research dual-clean preview",
            timeout=45,
        )
        assert http_status == 200
        assert b"Unicode path serve probe" in html_bytes

        health_status, health_body = _plain_get(preview_url.rstrip("/") + "/api/health")
        assert health_status == 200, health_body
        health_json = json.loads(health_body.decode("utf-8"))
        assert health_json.get("probe") == "vibe-preview-dual-clean", health_json

        status, serve_status = _request(port, token, f"/api/editor/{wf_id}/serve/status")
        assert status == 200, serve_status
        assert serve_status.get("backend") and serve_status["backend"].get("running") is True
        assert serve_status["backend"]["url"] == preview_url

        state_file = workspace / ".preview-servers.json"
        # Persistence may appear after start; tolerate brief delay.
        for _ in range(30):
            if state_file.is_file():
                break
            time.sleep(0.1)
        assert state_file.is_file(), "preview state not persisted under workspace"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state, state

        status, stopped = _request(
            port,
            token,
            f"/api/editor/{wf_id}/serve",
            "DELETE",
        )
        assert status == 200, stopped
        assert "backend" in (stopped.get("stopped") or []) or stopped.get("stopped") is not None

        for _ in range(40):
            status, serve_status = _request(port, token, f"/api/editor/{wf_id}/serve/status")
            if status == 200 and not serve_status.get("backend"):
                break
            time.sleep(0.15)
        assert status == 200
        assert not serve_status.get("backend"), serve_status

        # File delete after serve proves editor still healthy.
        status, deleted = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file?path={q_notes}",
            "DELETE",
        )
        assert status == 200 and deleted.get("ok") is True, deleted
        status, missing = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file?path={q_notes}",
        )
        assert status == 404, missing

        return {
            "label": label,
            "user_data": str(user),
            "workspace": str(workspace),
            "wf_id": wf_id,
            "preview_url": preview_url,
            "preview_html_bytes": len(html_bytes),
            "state_file": str(state_file),
        }
    finally:
        if wf_id:
            try:
                _request(port, token, f"/api/editor/{wf_id}/serve", "DELETE")
            except Exception:
                pass
        _stop(process)


def test_dual_clean_editor_files_and_project_serve(tmp_path: Path) -> None:
    base = tmp_path / "双根-编辑器预览"
    base.mkdir(parents=True)
    a = _clean_run("甲", base, token_tag="A")
    b = _clean_run("乙", base, token_tag="B")
    assert a["workspace"] != b["workspace"]
    assert a["preview_url"] != b["preview_url"] or a["wf_id"] != b["wf_id"]
    assert Path(a["state_file"]).name == ".preview-servers.json"
    assert Path(b["state_file"]).name == ".preview-servers.json"
    for item in (a, b):
        assert any(ord(ch) > 127 for ch in item["workspace"])
        assert item["preview_html_bytes"] > 50
