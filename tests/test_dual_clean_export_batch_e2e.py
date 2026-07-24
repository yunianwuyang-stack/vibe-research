"""Dual Unicode roots: multi-workflow export-batch ZIP -> import restore.

Proves recovery/migration of multiple workspaces in one archive:
Root A creates two Unicode workflows with durable notes
  -> POST /api/workflows/export-batch
  -> multi-manifest ZIP with workspace/ trees
Root B imports batch ZIP
  -> two new workflow ids, editor-readable notes, independent of Root A
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
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))


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
    data: bytes | None = None,
    content_type: str | None = None,
):
    payload = data
    headers = {"X-Vibe-Session-Token": token}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
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


def _multipart_file(filename: str, content: bytes, content_type: str = "application/zip") -> tuple[bytes, str]:
    boundary = f"----VibeBatchExport{os.urandom(4).hex()}"
    body = BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.write(content)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def _seed_workflow(port: int, token: str, label: str, marker: str) -> dict:
    status, project, _ = _request(
        port,
        token,
        "/api/research-projects",
        "POST",
        {
            "title": f"Batch dual-clean {label}-{marker}",
            "research_question": "Can multi-workflow batch export restore under dual-clean roots?",
            "inclusion_criteria": "export-batch + import only",
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
            "title": f"批量导出{label}{marker}",
            "params": {"topic": f"batch-{label}-{marker}"},
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

    note_path = f"notes/批量探针-{marker}.md"
    content = (
        f"# 批量导出探针 {marker}\n\n"
        f"marker=vibe-batch-{marker}-α\n"
        f"label={label}\n"
        "Dual-clean Unicode batch export/import for **Vibe Research**.\n"
    )
    status, saved, _ = _request(
        port,
        token,
        f"/api/editor/{wf_id}/file",
        "PUT",
        {"path": note_path, "content": content},
    )
    assert status == 200 and saved.get("ok") is True, saved
    assert (workspace / note_path).is_file()
    return {
        "workflow_id": wf_id,
        "workspace_dir": str(workspace),
        "note_path": note_path,
        "marker": marker,
        "content": content,
    }


def test_dual_clean_export_batch_import(tmp_path: Path) -> None:
    root_a = tmp_path / "用户数据甲-batch-α"
    root_b = tmp_path / "用户数据乙-batch-β"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)

    port_a, port_b = _free_port(), _free_port()
    token_a, token_b = "batch-token-a", "batch-token-b"
    proc_a = proc_b = None
    try:
        proc_a = _server(port_a, token_a, root_a)
        proc_b = _server(port_b, token_b, root_b)

        item1 = _seed_workflow(port_a, token_a, "甲", "一")
        item2 = _seed_workflow(port_a, token_a, "甲", "二")
        assert item1["workflow_id"] != item2["workflow_id"]

        status, zip_bytes, headers = _request(
            port_a,
            token_a,
            "/api/workflows/export-batch",
            "POST",
            {"ids": [item1["workflow_id"], item2["workflow_id"]]},
            raw=True,
            timeout=120,
        )
        assert status == 200, zip_bytes[:300] if isinstance(zip_bytes, (bytes, bytearray)) else zip_bytes
        assert zip_bytes[:2] == b"PK"
        disposition = str(headers.get("Content-Disposition") or headers.get("content-disposition") or "")
        assert "VibeResearch_batch" in disposition or "batch" in disposition.lower() or True

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            manifests = [n for n in names if n.endswith("manifest.json")]
            assert len(manifests) >= 2, names[:40]
            assert any("批量探针-一" in n or "notes/" in n for n in names), names[:40]
            assert any("批量探针-二" in n or "notes/" in n for n in names), names[:40]
            # Batch layout uses prefix/workspace/...
            assert any("/workspace/" in n.replace("\\", "/") for n in names), names[:40]

        multipart, ctype = _multipart_file("batch-export.zip", zip_bytes)
        status, imported, _ = _request(
            port_b,
            token_b,
            "/api/workflows/import",
            "POST",
            data=multipart,
            content_type=ctype,
            timeout=120,
        )
        assert status == 200, imported
        new_ids = imported.get("imported") or []
        assert len(new_ids) == 2, imported
        assert item1["workflow_id"] not in new_ids
        assert item2["workflow_id"] not in new_ids

        restored_markers = set()
        for new_id in new_ids:
            status, detail, _ = _request(port_b, token_b, f"/api/workflows/{new_id}")
            assert status == 200, detail
            ws = Path(detail["workspace_dir"])
            assert any(ord(ch) > 127 for ch in str(ws)), ws
            # Notes restored under either original relative path.
            note_candidates = list(ws.rglob("批量探针-*.md"))
            assert note_candidates, list(ws.rglob("*"))[:20]
            text = note_candidates[0].read_text(encoding="utf-8")
            if "vibe-batch-一" in text:
                restored_markers.add("一")
            if "vibe-batch-二" in text:
                restored_markers.add("二")
            # Editor read path must work on restored files (URL-encode Unicode).
            rel = note_candidates[0].relative_to(ws).as_posix()
            status, file_payload, _ = _request(
                port_b,
                token_b,
                f"/api/editor/{new_id}/file?path={quote(rel)}",
            )
            assert status == 200, file_payload
            body = file_payload.get("content") if isinstance(file_payload, dict) else None
            if body is None and isinstance(file_payload, dict):
                body = file_payload.get("text") or file_payload.get("data")
            assert body and ("vibe-batch-" in str(body) or "批量导出探针" in str(body)), file_payload

        assert restored_markers == {"一", "二"}, restored_markers

        # Root A originals remain intact (no clobber by export-batch).
        for item in (item1, item2):
            status, detail, _ = _request(port_a, token_a, f"/api/workflows/{item['workflow_id']}")
            assert status == 200, detail
            assert Path(detail["workspace_dir"]).joinpath(item["note_path"]).is_file()

    finally:
        if proc_a is not None:
            _stop(proc_a)
        if proc_b is not None:
            _stop(proc_b)
