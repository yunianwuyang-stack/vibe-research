"""Dual Unicode user-data: editor save → Draw.io export → Pandoc compile → artifacts.

Full UI→API→executor→persistence chain under two clean roots:
create workflow → write markdown → drawio PNG → compile DOCX/HTML → export ZIP.
No mock compile; requires bundled runtime pandoc + draw.io.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from io import BytesIO
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
    "</root></mxGraphModel></diagram></mxfile>"
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
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"X-Vibe-Session-Token": token, "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=180) as response:
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
    last_status = None
    last_body = None
    last_error = None
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


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-编辑器-{label}"
    user.mkdir(parents=True)
    token = f"dual-editor-{label}"
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
                "title": f"Editor dual-clean {label}",
                "research_question": "Do dual-clean roots compile editor artifacts independently?",
                "inclusion_criteria": "real pandoc and drawio outputs",
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
                "title": f"Editor compile {label}",
                "params": {"topic": f"editor-dual-{label}"},
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

        md = (
            f"# Editor Dual Clean {label}\n\n"
            f"Unicode 编辑编译证据 for root {label}.\n\n"
            "## Method\n\n"
            "Pandoc DOCX/HTML + Draw.io PNG under isolated user-data.\n\n"
            "| gate | status |\n|---|---|\n| drawio | pass |\n| compile | pass |\n"
        )
        status, saved = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {"path": "paper/main.md", "content": md},
        )
        assert status == 200, saved
        assert (workspace / "paper" / "main.md").is_file()

        status, files = _request(port, token, f"/api/editor/{wf_id}/files")
        assert status == 200, files
        names = {item.get("path") or item.get("name") for item in (files.get("files") or files if isinstance(files, list) else [])}
        # files payload may be list or {files:[...]}
        if not names and isinstance(files, dict):
            raw_files = files.get("files") or []
            names = set()
            for item in raw_files:
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict):
                    names.add(str(item.get("path") or item.get("name") or ""))
        assert any("main.md" in n for n in names) or (workspace / "paper" / "main.md").is_file()

        status, drawio = _request(
            port,
            token,
            f"/api/editor/{wf_id}/drawio-export",
            "POST",
            {"source": DRAWIO_SOURCE, "format": "png"},
        )
        assert status == 200, drawio
        assert drawio.get("status") == "completed", drawio
        assert drawio.get("outputs"), drawio
        png_rel = drawio["outputs"][0].get("path") or drawio["outputs"][0].get("source", {}).get("path")
        assert png_rel, drawio
        png_path = workspace / png_rel
        assert png_path.is_file() and png_path.stat().st_size > 500, png_path
        assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        manifest_rel = drawio.get("manifest", {}).get("path")
        if manifest_rel:
            assert (workspace / manifest_rel).is_file()
            assert len(drawio["manifest"]["sha256"]) == 64

        # Embed figure then compile.
        md2 = md + f"\n\n![pipeline]({Path(png_rel).as_posix()})\n"
        status, saved = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {"path": "paper/main.md", "content": md2},
        )
        assert status == 200, saved

        status, compiled = _request(
            port,
            token,
            f"/api/editor/{wf_id}/compile",
            "POST",
            {"source_md": ""},
        )
        assert status == 200, compiled
        assert compiled.get("status") == "completed", compiled
        assert compiled.get("outputs"), compiled
        out_paths = [workspace / item["path"] for item in compiled["outputs"]]
        docx_paths = [p for p in out_paths if p.suffix.lower() == ".docx" and p.is_file()]
        html_paths = [p for p in out_paths if p.suffix.lower() == ".html" and p.is_file()]
        assert docx_paths, compiled
        assert html_paths, compiled
        assert docx_paths[0].stat().st_size > 1000
        assert html_paths[0].stat().st_size > 200
        with zipfile.ZipFile(docx_paths[0]) as archive:
            assert "word/document.xml" in archive.namelist()
        assert "Editor Dual Clean" in html_paths[0].read_text(encoding="utf-8", errors="replace")

        compile_manifest = compiled.get("manifest") or {}
        if compile_manifest.get("path"):
            mpath = workspace / compile_manifest["path"]
            assert mpath.is_file()
            assert len(compile_manifest.get("sha256") or "") == 64

        status, stats = _request(port, token, f"/api/editor/{wf_id}/stats?path=paper/main.md")
        assert status == 200, stats

        # Honest AI edit without keys: 501/502 or structured failure — never mock polish.
        status, ai_edit = _request(
            port,
            token,
            f"/api/editor/{wf_id}/ai-edit",
            "POST",
            {
                "message": "polish this paragraph",
                "current_file": "paper/main.md",
                "current_content": "Unicode 编辑编译证据",
                "workspace_files": ["paper/main.md"],
                "compile_log": "",
                "extra_context": "",
                "history": [],
                "role": "editor_ai",
                "chat_summary": "",
            },
        )
        if status == 200:
            body = json.dumps(ai_edit, ensure_ascii=False).lower()
            assert "mock" not in body
            assert "placeholder" not in body
        else:
            assert status in {400, 422, 500, 501, 502, 503}, (status, ai_edit)
            detail = json.dumps(ai_edit, ensure_ascii=False).lower()
            assert "mock" not in detail

        status, export_bytes = _request(port, token, f"/api/workflows/{wf_id}/export", raw=True)
        assert status == 200, export_bytes[:200]
        assert export_bytes[:2] == b"PK"
        with zipfile.ZipFile(BytesIO(export_bytes)) as archive:
            names = archive.namelist()
            assert any("main.md" in n or "main.docx" in n or "main.html" in n for n in names), names[:40]

        return {
            "label": label,
            "wf_id": wf_id,
            "user_data": str(user),
            "workspace": str(workspace),
            "png": str(png_path),
            "docx": str(docx_paths[0]),
            "html": str(html_paths[0]),
            "png_sha": hashlib.sha256(png_path.read_bytes()).hexdigest(),
            "docx_sha": hashlib.sha256(docx_paths[0].read_bytes()).hexdigest(),
        }
    finally:
        _stop(process)


def test_dual_clean_editor_compile_e2e(tmp_path: Path):
    # Runtime preflight — fail loudly rather than skip/mock.
    pandoc = ROOT / "runtime" / "pandoc" / "pandoc.exe"
    drawio = ROOT / "runtime" / "draw.io"
    assert pandoc.is_file(), f"missing pandoc runtime: {pandoc}"
    assert drawio.is_dir(), f"missing draw.io runtime: {drawio}"

    a = _clean_run("A", tmp_path)
    b = _clean_run("B", tmp_path)
    assert a["user_data"] != b["user_data"]
    assert a["png_sha"] != "" and b["png_sha"] != ""
    # Isolated roots: artifacts not shared.
    assert Path(a["workspace"]).resolve() != Path(b["workspace"]).resolve()
    assert Path(a["docx"]).is_file() and Path(b["docx"]).is_file()
