"""Dual Unicode user-data: workflow export ZIP → import restore round-trip.

Proves recovery/migration surface end-to-end under two clean roots:
Root A creates workflow + Unicode artifacts + lineage audits → export ZIP
Root B imports ZIP → new workflow id, workspace files, DB rows, editor read.

No mock import; uses real /api/workflows/{id}/export and /api/workflows/import.
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
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))

NOTES_MD = (
    "# 导出导入探针\n\n"
    "marker=vibe-export-import-α\n"
    "Dual-clean Unicode export/import for **Vibe Research**.\n"
)

SCRIPT_PY = r"""
from pathlib import Path
p = Path("artifacts") / "导入导出产物.md"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("# export-import dual-clean\nmarker=vibe-export-import-run-α\n", encoding="utf-8")
print("EXPORT_IMPORT_OK")
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


def _multipart_file(filename: str, content: bytes, content_type: str = "application/zip") -> tuple[bytes, str]:
    boundary = f"----VibeExportImport{hashlib.sha1(os.urandom(8)).hexdigest()[:12]}"
    body = BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.write(content)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def _seed_exportable_workflow(port: int, token: str, label: str) -> dict:
    status, project, _ = _request(
        port,
        token,
        "/api/research-projects",
        "POST",
        {
            "title": f"Export/import dual-clean {label}",
            "research_question": "Do dual-clean roots export and re-import Unicode workspaces?",
            "inclusion_criteria": "export ZIP + import restore only",
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
            "title": f"导出导入工作流 {label}",
            "params": {"topic": f"export-import-{label}"},
            "enable_checkpoints": True,
            "project_id": project["id"],
        },
    )
    assert status == 200, workflow
    wf_id = workflow["id"]
    status, detail, _ = _request(port, token, f"/api/workflows/{wf_id}")
    assert status == 200, detail
    workspace = Path(detail["workspace_dir"])
    assert any(ord(ch) > 127 for ch in str(workspace))

    notes_path = "notes/导出导入探针.md"
    status, saved, _ = _request(
        port,
        token,
        f"/api/editor/{wf_id}/file",
        "PUT",
        {"path": notes_path, "content": NOTES_MD},
    )
    assert status == 200 and saved.get("ok") is True, saved

    status, run_result, _ = _request(
        port,
        token,
        f"/api/editor/{wf_id}/run-script",
        "POST",
        {"script": SCRIPT_PY, "language": "python"},
        timeout=90,
    )
    assert status == 200 and run_result.get("success") is True, run_result
    audit_rel = (run_result.get("audit") or {}).get("path")
    assert audit_rel and audit_rel.startswith(".editor_runs/"), run_result
    assert (workspace / "artifacts" / "导入导出产物.md").is_file()
    assert (workspace / audit_rel).is_file()

    status, zip_bytes, headers = _request(
        port,
        token,
        f"/api/workflows/{wf_id}/export",
        raw=True,
        timeout=90,
    )
    assert status == 200, zip_bytes[:200]
    assert zip_bytes[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert any("导出导入探针" in n for n in names), names
        assert any(".editor_runs/" in n for n in names), names
        assert any("导入导出产物" in n for n in names), names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert (manifest.get("workflow") or {}).get("title")

    return {
        "wf_id": wf_id,
        "workspace": str(workspace),
        "zip_bytes": zip_bytes,
        "notes_path": notes_path,
        "audit_rel": audit_rel,
        "title": f"导出导入工作流 {label}",
        "project_id": project["id"],
    }


def _import_and_verify(port: int, token: str, user: Path, zip_bytes: bytes, *, source: dict) -> dict:
    body, content_type = _multipart_file("VibeResearch_export.zip", zip_bytes)
    status, imported, _ = _request(
        port,
        token,
        "/api/workflows/import",
        "POST",
        data=body,
        content_type=content_type,
        timeout=90,
    )
    assert status == 200, imported
    ids = imported.get("imported") or []
    assert len(ids) == 1, imported
    new_id = ids[0]
    assert new_id != source["wf_id"]

    status, detail, _ = _request(port, token, f"/api/workflows/{new_id}")
    assert status == 200, detail
    assert detail.get("title") == source["title"]
    assert detail.get("template") == "idea_discovery"
    workspace = Path(detail["workspace_dir"])
    assert user.resolve() in workspace.resolve().parents or str(user.resolve()) in str(
        workspace.resolve()
    )
    assert any(ord(ch) > 127 for ch in str(workspace))
    assert workspace.is_dir()

    notes = workspace / source["notes_path"]
    assert notes.is_file()
    assert "vibe-export-import-α" in notes.read_text(encoding="utf-8")

    artifact = workspace / "artifacts" / "导入导出产物.md"
    assert artifact.is_file()
    assert "vibe-export-import-run-α" in artifact.read_text(encoding="utf-8")

    # Lineage audit must restore (export allowlist + import workspace extract).
    audit_hits = list((workspace / ".editor_runs").glob("*.json")) if (workspace / ".editor_runs").is_dir() else []
    assert audit_hits, "imported workspace missing .editor_runs lineage"
    audit_payload = json.loads(audit_hits[0].read_text(encoding="utf-8"))
    assert audit_payload.get("operation") == "run_script"

    # Editor + artifacts API on imported workflow.
    status, read_body, _ = _request(
        port,
        token,
        f"/api/editor/{new_id}/file?path={quote(source['notes_path'], safe='/')}",
    )
    assert status == 200, read_body
    assert "vibe-export-import-α" in read_body.get("content", "")

    status, artifacts, _ = _request(port, token, f"/api/workflows/{new_id}/artifacts")
    assert status == 200, artifacts
    paths = {
        (item.get("path") if isinstance(item, dict) else item)
        for item in (artifacts if isinstance(artifacts, list) else artifacts.get("artifacts") or artifacts.get("files") or [])
    }
    path_text = "\n".join(str(p) for p in paths)
    assert "导出导入探针" in path_text or source["notes_path"] in path_text, paths
    assert "导入导出产物" in path_text or any("导入导出产物" in str(p) for p in paths), paths
    assert any(".editor_runs" in str(p) for p in paths), paths

    return {
        "new_id": new_id,
        "workspace": str(workspace),
        "notes": str(notes),
        "artifact": str(artifact),
        "audit_count": len(audit_hits),
    }


def test_dual_clean_export_import_round_trip(tmp_path: Path) -> None:
    """Root A exports; Root B imports; both roots are Unicode dual-clean."""
    base = tmp_path / "双根-导出导入"
    base.mkdir(parents=True)

    # --- Root A: produce export ZIP ---
    user_a = base / "用户数据-导出源-甲"
    user_a.mkdir(parents=True)
    token_a = "dual-export-import-A"
    port_a = _free_port()
    proc_a = _server(port_a, token_a, user_a)
    try:
        status, health, _ = _request(port_a, token_a, "/api/health")
        assert status == 200 and health.get("status") == "ok", health
        source = _seed_exportable_workflow(port_a, token_a, "甲")
        assert user_a.resolve() in Path(source["workspace"]).resolve().parents or str(
            user_a.resolve()
        ) in source["workspace"]
        zip_bytes = source["zip_bytes"]
        assert len(zip_bytes) > 500
    finally:
        _stop(proc_a)

    # --- Root B: import into independent Unicode user-data ---
    user_b = base / "用户数据-导入目标-乙"
    user_b.mkdir(parents=True)
    token_b = "dual-export-import-B"
    port_b = _free_port()
    proc_b = _server(port_b, token_b, user_b)
    try:
        status, health, _ = _request(port_b, token_b, "/api/health")
        assert status == 200 and health.get("status") == "ok", health
        restored = _import_and_verify(port_b, token_b, user_b, zip_bytes, source=source)
        assert restored["new_id"] != source["wf_id"]
        assert Path(restored["workspace"]).resolve() != Path(source["workspace"]).resolve()
        assert any(ord(ch) > 127 for ch in restored["workspace"])
        assert restored["audit_count"] >= 1

        # Second import of same ZIP yields another independent workflow (no clobber).
        body, content_type = _multipart_file("again.zip", zip_bytes)
        status, again, _ = _request(
            port_b,
            token_b,
            "/api/workflows/import",
            "POST",
            data=body,
            content_type=content_type,
            timeout=90,
        )
        assert status == 200, again
        again_ids = again.get("imported") or []
        assert len(again_ids) == 1
        assert again_ids[0] != restored["new_id"]
        status, again_detail, _ = _request(port_b, token_b, f"/api/workflows/{again_ids[0]}")
        assert status == 200, again_detail
        assert Path(again_detail["workspace_dir"]).is_dir()
    finally:
        _stop(proc_b)
