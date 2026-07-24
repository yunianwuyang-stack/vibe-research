"""Dual Unicode user-data: Mermaid offline export → SVG/PNG + manifest.

Full API→executor→persistence chain under two clean roots:
create workflow → mermaid-export svg/png → offline library hash → reject external refs.
No network mermaid CDN; requires bundled mermaid.min.js + local Chrome/Edge.
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

MERMAID_SOURCE = """flowchart LR
  A[Research] --> B[Evidence]
  B --> C[Claim]
  C --> D[Assurance]
"""

EXTERNAL_SOURCE = """flowchart LR
  A-->B
  click A "https://example.com"
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
        headers={"X-Vibe-Session-Token": token, "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=180) as response:
            payload = response.read()
            return response.status, json.loads(payload.decode("utf-8"))
    except HTTPError as error:
        payload = error.read()
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


def _chromium_available() -> bool:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    ]
    return any(path.is_file() for path in candidates)


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-Mermaid-{label}"
    user.mkdir(parents=True)
    token = f"dual-mermaid-{label}"
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
                "title": f"Mermaid dual-clean {label}",
                "research_question": "Do dual-clean roots export offline Mermaid artifacts?",
                "inclusion_criteria": "offline mermaid.min.js + local Chromium",
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
                "title": f"Mermaid export {label}",
                "params": {"topic": f"mermaid-dual-{label}"},
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

        status, svg_export = _request(
            port,
            token,
            f"/api/editor/{wf_id}/mermaid-export",
            "POST",
            {"source": MERMAID_SOURCE, "format": "svg"},
        )
        assert status == 200, svg_export
        assert svg_export.get("status") == "completed", svg_export
        assert svg_export.get("outputs"), svg_export
        svg_rel = svg_export["outputs"][0]["path"]
        svg_path = workspace / svg_rel
        assert svg_path.is_file() and svg_path.stat().st_size > 200, svg_path
        svg_text = svg_path.read_text(encoding="utf-8", errors="replace")
        assert "<svg" in svg_text.casefold()
        assert "viewbox" in svg_text.casefold() or "viewBox" in svg_text
        assert "cdn.jsdelivr" not in svg_text.casefold()
        assert "mermaid.min.js" not in svg_text.casefold()
        assert "http://example.com" not in svg_text.casefold()
        assert "https://example.com" not in svg_text.casefold()

        manifest_rel = (svg_export.get("manifest") or {}).get("path")
        assert manifest_rel, svg_export
        manifest_path = workspace / manifest_rel
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["operation"] == "mermaid_export"
        assert manifest["runtime"]["offline"] is True
        assert manifest["runtime"]["mermaid_library_sha256"]
        assert len(manifest["runtime"]["mermaid_library_sha256"]) == 64
        assert manifest["runtime"]["browser"]
        assert len(manifest["runtime"]["browser_sha256"]) == 64
        assert manifest.get("source", {}).get("sha256")
        source_mmd = workspace / manifest["source"]["path"]
        assert source_mmd.is_file()
        assert "Research" in source_mmd.read_text(encoding="utf-8")

        status, png_export = _request(
            port,
            token,
            f"/api/editor/{wf_id}/mermaid-export",
            "POST",
            {"source": MERMAID_SOURCE, "format": "png"},
        )
        assert status == 200, png_export
        assert png_export.get("status") == "completed", png_export
        png_out = png_export["outputs"][0]
        png_rel = png_out.get("path") or (png_out.get("source") or {}).get("path")
        assert png_rel, png_export
        png_path = workspace / png_rel
        assert png_path.is_file() and png_path.stat().st_size > 500, png_path
        assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert png_out.get("status") == "valid", png_out

        status, blocked = _request(
            port,
            token,
            f"/api/editor/{wf_id}/mermaid-export",
            "POST",
            {"source": EXTERNAL_SOURCE, "format": "svg"},
        )
        assert status == 422, blocked

        return {
            "label": label,
            "wf_id": wf_id,
            "user_data": str(user),
            "workspace": str(workspace),
            "svg": str(svg_path),
            "png": str(png_path),
            "manifest": str(manifest_path),
            "svg_sha": hashlib.sha256(svg_path.read_bytes()).hexdigest(),
            "png_sha": hashlib.sha256(png_path.read_bytes()).hexdigest(),
            "library_sha": manifest["runtime"]["mermaid_library_sha256"],
            "offline": manifest["runtime"]["offline"],
        }
    finally:
        _stop(process)


def test_dual_clean_mermaid_export_e2e(tmp_path: Path):
    library = ROOT / "skills" / "patent-build" / "tools" / "mermaid.min.js"
    assert library.is_file(), f"missing offline mermaid library: {library}"
    assert _chromium_available(), "Chrome or Edge required for offline Mermaid export"

    a = _clean_run("A", tmp_path)
    b = _clean_run("B", tmp_path)
    assert a["user_data"] != b["user_data"]
    assert Path(a["workspace"]).resolve() != Path(b["workspace"]).resolve()
    assert a["offline"] is True and b["offline"] is True
    assert a["library_sha"] == b["library_sha"] == hashlib.sha256(library.read_bytes()).hexdigest()
    assert Path(a["svg"]).is_file() and Path(b["svg"]).is_file()
    assert Path(a["png"]).is_file() and Path(b["png"]).is_file()
    assert a["svg_sha"] and b["svg_sha"]
    assert a["png_sha"] and b["png_sha"]
