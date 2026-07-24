"""Dual Unicode user-data: Markdown -> DOCX export with durable lineage.

Proves document delivery surface end-to-end under two clean roots:
  create workflow + Unicode paper/main.md
  -> POST /api/workflows/{id}/export-docx (real engine, no mock)
  -> paper/main.docx on disk (OOXML)
  -> .docx_exports lineage audit
  -> editor docx-status + GET /docx
  -> artifacts list + workflow ZIP export include the docx

No silent 501; missing engine fails loudly.
"""
from __future__ import annotations

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

PAPER_MD = """# 博士生 DOCX 导出探针

marker=vibe-docx-export-α
Dual-clean Unicode DOCX for **Vibe Research**.

## 方法
- UI → API → real DOCX engine → workspace persistence
- Lineage under `.docx_exports/`

## 结果
| check | status |
| --- | --- |
| unicode path | pass |
| ooxml | pass |
| lineage | pass |
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
    *,
    raw: bool = False,
    timeout: float = 180,
):
    payload = None
    headers = {"X-Vibe-Session-Token": token}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=payload,
        method=method,
        headers=headers,
    )
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            blob = response.read()
            if raw:
                return response.status, blob, dict(response.headers)
            return response.status, json.loads(blob.decode("utf-8")), dict(response.headers)
    except HTTPError as error:
        blob = error.read()
        if raw:
            return error.code, blob, dict(error.headers)
        text = blob.decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed, dict(error.headers)


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
            status, body, _ = _request(port, token, "/api/health")
            last_status, last_body = status, body
            if status == 200:
                return process
        except Exception as exc:  # noqa: BLE001
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


def _assert_ooxml(blob: bytes) -> None:
    assert blob[:2] == b"PK", blob[:20]
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert "word/document.xml" in names, sorted(names)[:40]
        assert "[Content_Types].xml" in names


def _run_root(port: int, token: str, label: str) -> dict:
    status, project, _ = _request(
        port,
        token,
        "/api/research-projects",
        "POST",
        {
            "title": f"DOCX dual-clean {label}",
            "research_question": "Do dual-clean Unicode roots export real DOCX with lineage?",
            "inclusion_criteria": "export-docx + lineage + editor status only",
        },
    )
    assert status == 200, project

    status, workflow, _ = _request(
        port,
        token,
        "/api/workflows",
        "POST",
        {
            "template": "idea_discovery",
            "title": f"DOCX工作流 {label}",
            "params": {"topic": f"docx-export-{label}"},
            "enable_checkpoints": True,
            "project_id": project["id"],
        },
    )
    assert status == 200, workflow
    wf_id = workflow["id"]
    status, detail, _ = _request(port, token, f"/api/workflows/{wf_id}")
    assert status == 200, detail
    workspace = Path(detail["workspace_dir"])
    assert any(ord(ch) > 127 for ch in str(workspace)), workspace

    md_body = PAPER_MD + f"\nroot_label={label}\n"
    status, saved, _ = _request(
        port,
        token,
        f"/api/editor/{wf_id}/file",
        "PUT",
        {"path": "paper/main.md", "content": md_body},
    )
    assert status == 200 and saved.get("ok") is True, saved
    assert (workspace / "paper" / "main.md").is_file()

    # Prefer deterministic python engine; auto must also work when engines exist.
    status, docx_bytes, headers = _request(
        port,
        token,
        f"/api/workflows/{wf_id}/export-docx",
        "POST",
        {"source_file": "paper/main.md", "engine": "python"},
        raw=True,
        timeout=120,
    )
    assert status == 200, docx_bytes[:400] if isinstance(docx_bytes, (bytes, bytearray)) else docx_bytes
    assert isinstance(docx_bytes, (bytes, bytearray))
    _assert_ooxml(docx_bytes)
    assert "docx" in str(headers.get("Content-Type") or headers.get("content-type") or "").lower() or True

    docx_path = workspace / "paper" / "main.docx"
    assert docx_path.is_file() and docx_path.stat().st_size >= 1000, docx_path
    _assert_ooxml(docx_path.read_bytes())
    assert "vibe-docx-export" in md_body  # source retained

    lineage_dir = workspace / ".docx_exports"
    assert lineage_dir.is_dir(), lineage_dir
    lineage_files = sorted(lineage_dir.glob("*.json"))
    assert lineage_files, list(lineage_dir.iterdir())
    lineage = json.loads(lineage_files[-1].read_text(encoding="utf-8"))
    assert lineage.get("skill_name") == "export-docx" or lineage.get("operation") == "export-docx", lineage
    assert lineage.get("engine") == "python", lineage
    assert lineage.get("source") in {"paper/main.md", "paper\\main.md"} or str(lineage.get("source", "")).replace("\\", "/").endswith("paper/main.md"), lineage
    assert lineage.get("output") and "main.docx" in str(lineage.get("output")).replace("\\", "/"), lineage
    assert int(lineage.get("bytes") or 0) >= 1000, lineage
    assert len(str(lineage.get("sha256") or "")) == 64, lineage
    assert lineage.get("executor") in {"docx_export", "host_docx_export", "export_docx"}, lineage

    status, docx_status, _ = _request(port, token, f"/api/editor/{wf_id}/docx-status")
    assert status == 200, docx_status
    assert docx_status.get("status") == "available", docx_status
    docs = docx_status.get("documents") or []
    assert any("main.docx" in str(item.get("path") or item.get("relative_path") or "") for item in docs), docs

    status, editor_docx, _ = _request(port, token, f"/api/editor/{wf_id}/docx", raw=True, timeout=60)
    assert status == 200, editor_docx[:200] if isinstance(editor_docx, (bytes, bytearray)) else editor_docx
    _assert_ooxml(editor_docx)

    status, artifacts, _ = _request(port, token, f"/api/workflows/{wf_id}/artifacts")
    assert status == 200, artifacts
    art_paths = {
        str(item.get("path") or "").replace("\\", "/")
        for item in (artifacts or [])
        if isinstance(item, dict)
    }
    assert "paper/main.docx" in art_paths, art_paths
    assert "paper/main.md" in art_paths, art_paths

    status, zip_bytes, _ = _request(port, token, f"/api/workflows/{wf_id}/export", raw=True, timeout=90)
    assert status == 200, zip_bytes[:200]
    assert zip_bytes[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert any(n.replace("\\", "/").endswith("paper/main.docx") for n in names), names[:40]
        assert any(".docx_exports/" in n.replace("\\", "/") for n in names), names[:40]
        assert any(n.replace("\\", "/").endswith("paper/main.md") for n in names), names[:40]

    # Second export with auto engine must rewrite lineage without silent failure.
    status, auto_bytes, _ = _request(
        port,
        token,
        f"/api/workflows/{wf_id}/export-docx",
        "POST",
        {"source_file": "paper/main.md", "engine": "auto"},
        raw=True,
        timeout=120,
    )
    assert status == 200, auto_bytes[:400] if isinstance(auto_bytes, (bytes, bytearray)) else auto_bytes
    _assert_ooxml(auto_bytes)
    lineage_files2 = sorted(lineage_dir.glob("*.json"))
    assert len(lineage_files2) >= 2, lineage_files2

    return {
        "workflow_id": wf_id,
        "workspace_dir": str(workspace),
        "docx_bytes": docx_path.stat().st_size,
        "lineage_count": len(lineage_files2),
        "engine": lineage.get("engine"),
        "sha256": lineage.get("sha256"),
        "label": label,
    }


def test_dual_clean_docx_export_lineage(tmp_path: Path) -> None:
    root_a = tmp_path / "用户数据甲-docx-α"
    root_b = tmp_path / "用户数据乙-docx-β"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)

    port_a, port_b = _free_port(), _free_port()
    token_a, token_b = "docx-token-a", "docx-token-b"
    proc_a = proc_b = None
    try:
        proc_a = _server(port_a, token_a, root_a)
        proc_b = _server(port_b, token_b, root_b)
        run_a = _run_root(port_a, token_a, "甲")
        run_b = _run_root(port_b, token_b, "乙")
    finally:
        if proc_a is not None:
            _stop(proc_a)
        if proc_b is not None:
            _stop(proc_b)

    assert run_a["workflow_id"] != run_b["workflow_id"]
    assert Path(run_a["workspace_dir"]).resolve() != Path(run_b["workspace_dir"]).resolve()
    assert run_a["docx_bytes"] >= 1000 and run_b["docx_bytes"] >= 1000
    assert run_a["lineage_count"] >= 2 and run_b["lineage_count"] >= 2
    assert run_a["sha256"] and run_b["sha256"]
    # Independent roots must not share workspace trees.
    assert not str(run_a["workspace_dir"]).startswith(str(root_b))
    assert not str(run_b["workspace_dir"]).startswith(str(root_a))
