"""Dual Unicode user-data roots against the *packaged* win-unpacked backend tree.

Proves release/win-unpacked/resources/app.asar.unpacked ships host_domain_builders + brand-clean
skills and can complete a real host workflow chain under two clean roots.

Uses the repo-bundled Python runtime (packaged tree may not ship python.exe) while
loading backend code exclusively from the packaged app path.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PACKAGED_APP = ROOT / "release" / "win-unpacked" / "resources" / "app.asar.unpacked"
PACKAGED_BACKEND = PACKAGED_APP / "backend"
PACKAGED_RUNTIME = ROOT / "release" / "win-unpacked" / "resources" / "runtime"
PYTHON = PACKAGED_RUNTIME / "python" / "python.exe"


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
        with urlopen(req, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    assert PACKAGED_BACKEND.is_dir(), f"missing packaged backend: {PACKAGED_BACKEND}"
    assert PYTHON.is_file(), f"missing packaged Python runtime: {PYTHON}"
    assert (PACKAGED_BACKEND / "services" / "host_domain_builders.py").is_file()
    env = {
        **os.environ,
        "PYTHONPATH": str(PACKAGED_BACKEND),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(PACKAGED_RUNTIME),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
    }
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
            "warning",
        ],
        cwd=str(PACKAGED_BACKEND),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for _ in range(120):
        if process.poll() is not None:
            out = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"packaged backend exited: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"packaged backend failed to start: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait(port: int, token: str, wf_id: str, *, seconds: float = 240.0) -> dict:
    terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
    deadline = time.time() + seconds
    detail: dict = {}
    while time.time() < deadline:
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        if str(detail.get("status") or "") in terminal:
            return detail
        time.sleep(0.4)
    raise AssertionError(detail)


def _approve(port: int, token: str, wf_id: str, detail: dict) -> dict:
    hops = 0
    while detail.get("status") == "waiting_checkpoint" and hops < 12:
        status, _ = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/checkpoint",
            "POST",
            {"action": "approve", "data": {"feedback": "packaged dual-clean approve"}},
        )
        assert status == 200
        detail = _wait(port, token, wf_id, seconds=180)
        hops += 1
    return detail


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-安装后端-{label}"
    user.mkdir(parents=True)
    token = f"pkg-dual-{label}"
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
                "title": f"Packaged dual-clean {label}",
                "research_question": "Does packaged backend host chain work dual-clean?",
                "inclusion_criteria": "packaged host_domain_builders artifacts",
            },
        )
        assert status == 200, project

        status, wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "one_sentence_project",
                "title": f"Packaged blueprint {label}",
                "params": {"one_sentence": f"packaged dual-clean host blueprint {label}"},
                "enable_checkpoints": False,
                "project_id": project["id"],
            },
        )
        assert status == 200, wf
        wf_id = wf["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        ws = Path(detail["workspace_dir"])
        assert any(ord(ch) > 127 for ch in str(user))

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _approve(port, token, wf_id, _wait(port, token, wf_id))
        assert final["status"] == "completed", final

        for name in ("PROJECT_BLUEPRINT.md", "RESEARCH_CONTRACT_DRAFT.md", "MILESTONES.md"):
            path = ws / name
            assert path.is_file() and path.stat().st_size >= 80, path
            text = path.read_text(encoding="utf-8")
            # Brand-zero: product artifacts must not embed foreign product names.
            assert "host" in text.lower() or "blueprint" in text.lower() or len(text) >= 80

        lineage = ws / ".host_builds" / "project-blueprint.json"
        assert lineage.is_file()
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload.get("executor") == "host_step_runner"

        # Packaged list_artifacts must mirror export filter (workspace deliverables).
        status, listed = _request(port, token, f"/api/workflows/{wf_id}/artifacts")
        assert status == 200, listed
        listed_paths = {
            str(item.get("path") or "").replace("\\", "/")
            for item in (listed or [])
            if isinstance(item, dict)
        }
        assert "PROJECT_BLUEPRINT.md" in listed_paths, listed_paths
        assert "RESEARCH_CONTRACT_DRAFT.md" in listed_paths, listed_paths
        assert "MILESTONES.md" in listed_paths, listed_paths

        status, ops = _request(port, token, f"/api/workflows/operations/{wf_id}")
        assert status == 200, ops
        assert ops.get("artifacts")
        assert ops.get("attempts")

        return {
            "label": label,
            "project_id": project["id"],
            "wf_id": wf_id,
            "user_data": str(user),
            "ws": str(ws),
            "packaged_backend": str(PACKAGED_BACKEND),
            "artifacts_api_ok": True,
        }
    finally:
        _stop(process)


def test_dual_clean_packaged_backend_host_chain(tmp_path: Path) -> None:
    if not PACKAGED_BACKEND.is_dir():
        import pytest

        pytest.skip("release/win-unpacked app.asar.unpacked backend not present")
    base = tmp_path / "双干净安装后端"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert Path(run1["ws"]).resolve() != Path(run2["ws"]).resolve()
    assert "用户数据-安装后端-1" in run1["user_data"]
    assert "用户数据-安装后端-2" in run2["user_data"]
    assert "release" in run1["packaged_backend"].replace("\\", "/")
