"""Dual Unicode user-data: editor generate-image honest fail / real provider.

Without credentials the route must return structured capability_unavailable
and must not write a fake success image. When a live OpenAI-compatible image
provider is configured via model profiles, the same dual-clean roots must
persist a validated image + .image_generation manifest.
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
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))
PROXY = "http://127.0.0.1:15721"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, token: str, path: str, method: str = "GET", body: dict | None = None, timeout: int = 90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"X-Vibe-Session-Token": token, "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=timeout) as response:
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
        # Force honest-fail path unless profiles are configured via API later.
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
    for _ in range(200):
        if process.poll() is not None:
            log_file.flush()
            out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            raise AssertionError(f"backend exited early ({process.returncode}): {out[-4000:]}")
        try:
            status, body = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            pass
        time.sleep(0.1)
    process.kill()
    raise AssertionError("backend failed to start")


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


def _prepare_workflow(port: int, token: str, label: str) -> tuple[str, Path]:
    status, project = _request(
        port,
        token,
        "/api/research-projects",
        "POST",
        {
            "title": f"Generate-image dual-clean {label}",
            "research_question": "Does image generation fail honestly without keys?",
            "inclusion_criteria": "no mock success image",
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
            "title": f"Image gen {label}",
            "params": {"topic": f"image-dual-{label}"},
            "enable_checkpoints": True,
            "project_id": project["id"],
        },
    )
    assert status == 200, workflow
    status, detail = _request(port, token, f"/api/workflows/{workflow['id']}")
    assert status == 200, detail
    workspace = Path(detail["workspace_dir"])
    assert any(ord(ch) > 127 for ch in str(workspace))
    return workflow["id"], workspace


def _clean_honest_fail(label: str, base: Path) -> dict:
    user = base / f"用户数据-ImageGen-{label}"
    user.mkdir(parents=True)
    token = f"dual-img-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        wf_id, workspace = _prepare_workflow(port, token, label)
        status, body = _request(
            port,
            token,
            f"/api/editor/{wf_id}/generate-image",
            "POST",
            {"prompt": "A simple research pipeline diagram, flat style", "model": "gpt-image-1", "size": "1024x1024"},
        )
        # Honest unavailable: 503 structured OR 200 with status=failed + failure_reason.
        # Never completed with a mock image.
        if status == 503:
            detail = body.get("detail") if isinstance(body, dict) else body
            if isinstance(detail, dict):
                assert detail.get("code") == "capability_unavailable", body
                assert detail.get("reason"), body
            else:
                assert "密钥" in str(detail) or "Base URL" in str(detail) or "OpenAI" in str(detail) or "模型" in str(detail), body
            generated = list((workspace / "figures" / "generated").glob("*")) if (workspace / "figures" / "generated").is_dir() else []
            assert not any(p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and p.stat().st_size > 0 for p in generated), generated
            mode = "http_503"
        elif status == 200:
            assert body.get("status") != "completed", body
            assert body.get("status") == "failed" or body.get("failure_reason"), body
            assert "mock" not in json.dumps(body, ensure_ascii=False).lower()
            manifest_rel = (body.get("manifest") or {}).get("path")
            if manifest_rel:
                mpath = workspace / manifest_rel
                assert mpath.is_file()
                manifest = json.loads(mpath.read_text(encoding="utf-8"))
                assert manifest.get("status") == "failed"
                assert manifest.get("failure_reason")
            mode = "status_failed"
        else:
            raise AssertionError(f"unexpected generate-image status {status}: {body}")

        return {
            "label": label,
            "user_data": str(user),
            "workspace": str(workspace),
            "mode": mode,
            "status": status,
        }
    finally:
        _stop(process)


def _proxy_supports_image_generation() -> bool:
    """Probe local OpenAI-compatible proxy for /v1/images/generations support."""
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("XAI_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or "proxy-local"
    ).strip()
    payload = json.dumps(
        {
            "model": "gpt-image-1",
            "prompt": "tiny test square",
            "size": "1024x1024",
            "n": 1,
        }
    ).encode("utf-8")
    req = Request(
        f"{PROXY}/v1/images/generations",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=15) as response:
            return response.status == 200
    except HTTPError as error:
        # 401/404/405/501 mean image route not usable for live dual-clean.
        return False
    except (URLError, TimeoutError, OSError):
        return False


def test_dual_clean_generate_image_honest_fail_e2e(tmp_path: Path):
    a = _clean_honest_fail("A", tmp_path)
    b = _clean_honest_fail("B", tmp_path)
    assert a["user_data"] != b["user_data"]
    assert Path(a["workspace"]).resolve() != Path(b["workspace"]).resolve()
    assert a["mode"] in {"http_503", "status_failed"}
    assert b["mode"] in {"http_503", "status_failed"}


def test_dual_clean_generate_image_live_provider_when_available(tmp_path: Path):
    """Only runs live path when proxy actually implements image generations."""
    if not _proxy_supports_image_generation():
        # Honest skip of live-only slice — no fake complete of image generation.
        return

    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("XAI_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or "proxy-local"
    ).strip()

    def _live(label: str) -> dict:
        user = tmp_path / f"用户数据-ImageLive-{label}"
        user.mkdir(parents=True)
        token = f"dual-imglive-{label}"
        port = _free_port()
        process = _server(port, token, user)
        try:
            # Configure editor_ai profile to the live proxy.
            status, profile = _request(
                port,
                token,
                "/api/settings/model-profiles/editor_ai",
                "PUT",
                {
                    "provider": "openai_compatible",
                    "base_url": f"{PROXY}/v1",
                    "model_id": "gpt-image-1",
                    "temperature": 0.2,
                    "top_p": 1.0,
                    "max_tokens": 1024,
                    "reasoning_effort": "",
                    "api_key": api_key,
                },
            )
            assert status == 200, profile
            wf_id, workspace = _prepare_workflow(port, token, f"live-{label}")
            status, body = _request(
                port,
                token,
                f"/api/editor/{wf_id}/generate-image",
                "POST",
                {
                    "prompt": "Minimal flat icon of a research checklist, white background",
                    "model": "gpt-image-1",
                    "size": "1024x1024",
                },
                timeout=240,
            )
            assert status == 200, body
            assert body.get("status") == "completed", body
            image = body.get("image") or {}
            rel = image.get("path") or (image.get("source") or {}).get("path")
            assert rel, body
            path = workspace / rel
            assert path.is_file() and path.stat().st_size > 500
            manifest_rel = (body.get("manifest") or {}).get("path")
            assert manifest_rel
            mpath = workspace / manifest_rel
            assert mpath.is_file()
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            assert manifest["operation"] == "provider_image_generation"
            assert manifest["status"] == "completed"
            assert manifest["response"]["bytes_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
            return {"workspace": str(workspace), "image": str(path), "bytes": path.stat().st_size}
        finally:
            _stop(process)

    a = _live("A")
    b = _live("B")
    assert Path(a["workspace"]).resolve() != Path(b["workspace"]).resolve()
    assert a["bytes"] > 500 and b["bytes"] > 500
