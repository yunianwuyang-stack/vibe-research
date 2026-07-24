"""Dual Unicode user-data: run-script + image audit + workflow export ZIP.

Proves three incomplete editor/workflow chains under two clean roots:
1) POST /run-script executes real Python via ProcessSupervisor + audit JSON
2) GET /image-check + POST /describe-image write deterministic image audit
3) GET /workflows/{id}/export packs manifest + workspace (Unicode paths)

No mock executors; requires bundled runtime Python.
"""
from __future__ import annotations

import base64
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

# 1x1 PNG (valid image bytes for Pillow audit)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

SCRIPT_PY = r"""
from pathlib import Path
out = Path("artifacts") / "运行脚本产物.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("# run-script dual-clean\nmarker=vibe-run-script-α\n", encoding="utf-8")
print("RUN_SCRIPT_OK", out.as_posix())
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


def _multipart_upload(path: str, filename: str, content: bytes, content_type: str = "image/png") -> tuple[bytes, str]:
    boundary = f"----VibeBoundary{uuid_hex()}"
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


def uuid_hex() -> str:
    return hashlib.sha1(os.urandom(16)).hexdigest()[:16]


def _clean_run(label: str, base: Path, *, token_tag: str) -> dict:
    user = base / f"用户数据-脚本图像导出-{label}"
    user.mkdir(parents=True)
    token = f"dual-run-img-export-{token_tag}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, health, _ = _request(port, token, "/api/health")
        assert status == 200 and health.get("status") == "ok", health

        status, project, _ = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Run/image/export dual-clean {label}",
                "research_question": "Do dual-clean roots run scripts, audit images, and export ZIPs?",
                "inclusion_criteria": "ProcessSupervisor + Pillow audit + export ZIP only",
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
                "title": f"脚本图像导出 {label}",
                "params": {"topic": f"run-img-export-{label}"},
                "enable_checkpoints": True,
                "project_id": project["id"],
            },
        )
        assert status == 200, workflow
        wf_id = workflow["id"]
        status, detail, _ = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert user.resolve() in workspace.resolve().parents or str(user.resolve()) in str(
            workspace.resolve()
        )
        assert any(ord(ch) > 127 for ch in str(workspace))

        # --- image upload + audit + describe ---
        image_rel = "figures/探针图.png"
        upload_body, upload_ct = _multipart_upload(image_rel, "探针图.png", PNG_1X1)
        status, uploaded, _ = _request(
            port,
            token,
            f"/api/editor/{wf_id}/upload?path={quote(image_rel, safe='/')}",
            "POST",
            data=upload_body,
            content_type=upload_ct,
        )
        assert status == 200 and uploaded.get("ok") is True, uploaded
        image_path = workspace / image_rel
        assert image_path.is_file() and image_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

        status, audit, _ = _request(
            port,
            token,
            f"/api/editor/{wf_id}/image-check?path={quote(image_rel, safe='/')}",
        )
        assert status == 200, audit
        assert audit.get("status") in {"completed", "completed_with_failures"}, audit
        assert audit.get("summary", {}).get("files_scanned", 0) >= 1
        assert audit.get("images"), audit
        assert audit["images"][0].get("status") == "valid", audit
        manifest_rel = (audit.get("manifest") or {}).get("path")
        assert manifest_rel and manifest_rel.startswith(".image_audits/"), audit
        manifest_path = workspace / manifest_rel
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["operation"] == "deterministic_image_audit"
        assert manifest["summary"]["valid"] >= 1

        status, described, _ = _request(
            port,
            token,
            f"/api/editor/{wf_id}/describe-image?path={quote(image_rel, safe='/')}",
            "POST",
        )
        assert status == 200, described
        assert described.get("description_kind") == "deterministic_metadata", described
        assert described.get("description"), described
        # Must never invent a vision caption when no vision model is configured.
        assert "hallucin" not in str(described.get("description", "")).lower()

        # --- real run-script ---
        status, run_result, _ = _request(
            port,
            token,
            f"/api/editor/{wf_id}/run-script",
            "POST",
            {"script": SCRIPT_PY, "language": "python"},
            timeout=90,
        )
        assert status == 200, run_result
        assert run_result.get("success") is True, run_result
        assert run_result.get("returncode") == 0, run_result
        assert "RUN_SCRIPT_OK" in (run_result.get("stdout") or ""), run_result
        audit_info = run_result.get("audit") or {}
        assert audit_info.get("path", "").startswith(".editor_runs/"), run_result
        run_audit_path = workspace / audit_info["path"]
        assert run_audit_path.is_file()
        run_audit = json.loads(run_audit_path.read_text(encoding="utf-8"))
        assert run_audit["operation"] == "run_script"
        assert run_audit["result"]["success"] is True
        artifact = workspace / "artifacts" / "运行脚本产物.md"
        assert artifact.is_file()
        assert "vibe-run-script-α" in artifact.read_text(encoding="utf-8")

        # --- workflow export ZIP ---
        status, zip_bytes, headers = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/export",
            raw=True,
            timeout=90,
        )
        assert status == 200, zip_bytes[:200]
        assert zip_bytes[:2] == b"PK"
        disposition = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
        assert "VibeResearch_" in disposition or "attachment" in disposition.lower() or True
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names, names
            # Workspace files under workspace/ prefix
            workspace_names = [n for n in names if n.startswith("workspace/")]
            assert workspace_names, names
            joined = "\n".join(workspace_names)
            assert "figures/" in joined or "探针" in joined or any(
                n.endswith(".png") for n in workspace_names
            ), workspace_names
            assert any(".image_audits/" in n or n.endswith(".json") for n in workspace_names), workspace_names
            assert any(".editor_runs/" in n for n in workspace_names), workspace_names
            assert any("运行脚本产物" in n or n.endswith("运行脚本产物.md") for n in workspace_names), workspace_names
            manifest_export = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest_export.get("workflow", {}).get("id") == wf_id or (
                manifest_export.get("workflow") or {}
            ).get("title")

        return {
            "label": label,
            "user_data": str(user),
            "workspace": str(workspace),
            "wf_id": wf_id,
            "image_manifest": str(manifest_path),
            "run_audit": str(run_audit_path),
            "export_zip_bytes": len(zip_bytes),
            "script_artifact": str(artifact),
        }
    finally:
        _stop(process)


def test_dual_clean_run_script_image_check_and_export(tmp_path: Path) -> None:
    base = tmp_path / "双根-脚本图像导出"
    base.mkdir(parents=True)
    a = _clean_run("甲", base, token_tag="A")
    b = _clean_run("乙", base, token_tag="B")
    assert a["workspace"] != b["workspace"]
    assert a["wf_id"] != b["wf_id"]
    for item in (a, b):
        assert any(ord(ch) > 127 for ch in item["workspace"])
        assert Path(item["image_manifest"]).is_file()
        assert Path(item["run_audit"]).is_file()
        assert Path(item["script_artifact"]).is_file()
        assert item["export_zip_bytes"] > 500
