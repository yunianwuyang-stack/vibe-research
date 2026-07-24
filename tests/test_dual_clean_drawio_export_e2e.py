"""Dual Unicode user-data: Draw.io CLI export → PNG/PDF + hashed manifest.

Full API→bundled draw.io executor→persistence under two clean roots.
Rejects external URI sources. No mock export; requires runtime/draw.io.
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
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))

DRAWIO_SOURCE = (
    '<mxfile host="app.diagrams.net"><diagram name="Page-1">'
    '<mxGraphModel dx="800" dy="600" grid="1" page="1" pageWidth="827" pageHeight="1169">'
    '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="2" value="Input" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">'
    '<mxGeometry x="80" y="100" width="120" height="60" as="geometry"/></mxCell>'
    '<mxCell id="3" value="Output" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">'
    '<mxGeometry x="300" y="100" width="120" height="60" as="geometry"/></mxCell>'
    '<mxCell id="4" style="edgeStyle=orthogonalEdgeStyle;endArrow=block;" edge="1" parent="1" source="2" target="3">'
    '<mxGeometry relative="1" as="geometry"/></mxCell>'
    "</root></mxGraphModel></diagram></mxfile>"
)

EXTERNAL_SOURCE = (
    '<mxfile host="app.diagrams.net"><diagram name="Page-1">'
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="2" value="A" style="shape=image;image=https://example.com/x.png;" vertex="1" parent="1">'
    '<mxGeometry x="40" y="40" width="80" height="80" as="geometry"/></mxCell>'
    "</root></mxGraphModel></diagram></mxfile>"
)


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
        with _OPENER.open(req, timeout=180) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


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
        except Exception as exc:
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


def _output_path(workspace: Path, payload: dict) -> Path:
    out = (payload.get("outputs") or [{}])[0]
    rel = out.get("path") or (out.get("source") or {}).get("path")
    assert rel, payload
    path = workspace / rel
    assert path.is_file() and path.stat().st_size > 100, path
    return path


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-DrawIO-{label}"
    user.mkdir(parents=True)
    token = f"dual-drawio-{label}"
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
                "title": f"DrawIO dual-clean {label}",
                "research_question": "Do dual-clean roots export Draw.io artifacts offline?",
                "inclusion_criteria": "bundled draw.io CLI only",
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
                "title": f"DrawIO export {label}",
                "params": {"topic": f"drawio-dual-{label}"},
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

        status, png_export = _request(
            port,
            token,
            f"/api/editor/{wf_id}/drawio-export",
            "POST",
            {"source": DRAWIO_SOURCE, "format": "png"},
        )
        assert status == 200, png_export
        assert png_export.get("status") == "completed", png_export
        png_path = _output_path(workspace, png_export)
        assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

        status, pdf_export = _request(
            port,
            token,
            f"/api/editor/{wf_id}/drawio-export",
            "POST",
            {"source": DRAWIO_SOURCE, "format": "pdf"},
        )
        assert status == 200, pdf_export
        assert pdf_export.get("status") == "completed", pdf_export
        pdf_path = _output_path(workspace, pdf_export)
        assert pdf_path.read_bytes()[:5] == b"%PDF-"

        manifest_rel = (png_export.get("manifest") or {}).get("path")
        assert manifest_rel, png_export
        manifest_path = workspace / manifest_rel
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["operation"] == "drawio_export"
        assert manifest["status"] == "completed"
        assert manifest["runtime"]["executable"]
        assert len(manifest["runtime"]["sha256"]) == 64
        assert manifest.get("source", {}).get("sha256")
        source_file = workspace / manifest["source"]["path"]
        assert source_file.is_file()
        assert "mxfile" in source_file.read_text(encoding="utf-8")

        status, blocked = _request(
            port,
            token,
            f"/api/editor/{wf_id}/drawio-export",
            "POST",
            {"source": EXTERNAL_SOURCE, "format": "png"},
        )
        assert status == 422, blocked

        return {
            "label": label,
            "user_data": str(user),
            "workspace": str(workspace),
            "png": str(png_path),
            "pdf": str(pdf_path),
            "manifest": str(manifest_path),
            "png_sha": hashlib.sha256(png_path.read_bytes()).hexdigest(),
            "pdf_sha": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
            "runtime_sha": manifest["runtime"]["sha256"],
        }
    finally:
        _stop(process)


def test_dual_clean_drawio_export_e2e(tmp_path: Path):
    drawio = ROOT / "runtime" / "draw.io" / "draw.io.exe"
    assert drawio.is_file(), f"missing bundled draw.io: {drawio}"

    a = _clean_run("A", tmp_path)
    b = _clean_run("B", tmp_path)
    assert a["user_data"] != b["user_data"]
    assert Path(a["workspace"]).resolve() != Path(b["workspace"]).resolve()
    assert Path(a["png"]).is_file() and Path(b["png"]).is_file()
    assert Path(a["pdf"]).is_file() and Path(b["pdf"]).is_file()
    assert a["png_sha"] and b["png_sha"]
    assert a["pdf_sha"] and b["pdf_sha"]
    assert a["runtime_sha"] == b["runtime_sha"] == hashlib.sha256(drawio.read_bytes()).hexdigest()
