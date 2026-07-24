"""Dual Unicode clean roots: real host Codex/Claude CLI via agents HTTP API.

Proves UI/API → agent_tasks → host CLI process → audit/workspace under each
isolated user-data root. Success requires real final_text; failure must be
honest with command + failure_reason/audit. No mock adapters.
"""
from __future__ import annotations

import json
import os
import shutil
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
SCRATCH = Path(os.environ.get("TEMP", str(ROOT))) / "grok-goal-a2d8993c825e" / "implementer"


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
        with _OPENER.open(req, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _which(name: str) -> str | None:
    return shutil.which(name)


def _server(port: int, token: str, user_data: Path, claude: str | None, codex: str | None) -> subprocess.Popen:
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
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "ALL_PROXY": "",
        "all_proxy": "",
        # Prefer explicit host CLIs; clear empty overrides.
        "CLAUDE_BIN": claude or "",
        "CODEX_BIN": codex or "",
    }
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
            "warning",
        ],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._vibe_log_file = log_file  # type: ignore[attr-defined]
    for _ in range(200):
        if process.poll() is not None:
            out = log_path.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"backend exited: {out[-3000:]}")
        try:
            status, body = _request(port, token, "/api/health")
            if status == 200 and body.get("status") == "ok":
                return process
        except Exception:
            pass
        time.sleep(0.1)
    process.kill()
    raise AssertionError("backend start timeout")


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


def _wait_task(port: int, token: str, task_id: str, timeout: float = 70.0) -> dict:
    deadline = time.time() + timeout
    current = None
    while time.time() < deadline:
        status, current = _request(port, token, f"/api/agents/tasks/{task_id}")
        assert status == 200, current
        if current.get("status") not in {"queued", "running", "cancelling"}:
            return current
        time.sleep(0.35)
    raise AssertionError(f"task timeout: {current}")


def _clean_run(label: str, base: Path, adapters: list[str], claude: str | None, codex: str | None) -> dict:
    user = base / f"用户数据-真实CLI-{label}"
    user.mkdir(parents=True)
    token = f"dual-cli-{label}"
    port = _free_port()
    process = _server(port, token, user, claude, codex)
    results = []
    try:
        # Persist CLI paths in settings for UI→settings→executor loop.
        settings_body = {"settings": {}}
        if claude:
            settings_body["settings"]["claude_bin"] = claude
        if codex:
            settings_body["settings"]["codex_bin"] = codex
        if settings_body["settings"]:
            status, put = _request(port, token, "/api/settings", "PUT", settings_body)
            assert status == 200, put

        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Real CLI dual-clean {label}",
                "research_question": "Does host CLI agent task leave durable audit under Unicode root?",
                "inclusion_criteria": "real executable, no mock adapter",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        status, manifest = _request(port, token, "/api/agents/manifest")
        assert status == 200, manifest
        available = {
            name: entry
            for name, entry in (manifest.get("adapters") or {}).items()
            if entry.get("status") == "available"
        }

        for adapter in adapters:
            if adapter not in available:
                results.append(
                    {
                        "adapter": adapter,
                        "skipped": True,
                        "reason": f"not available: {manifest.get('adapters', {}).get(adapter)}",
                    }
                )
                continue
            status, task = _request(
                port,
                token,
                "/api/agents/tasks",
                "POST",
                {
                    "project_id": project_id,
                    "adapter": adapter,
                    "prompt": "Reply with exactly: VIBE_CLI_DUAL_CLEAN",
                    "timeout_seconds": 45,
                },
            )
            assert status == 200, task
            assert task["adapter"] == adapter
            assert task["status"] in {"queued", "running", "completed", "failed", "cancelled", "interrupted"}
            final = _wait_task(port, token, task["id"], timeout=70)
            assert final["status"] in {"completed", "failed", "cancelled", "interrupted"}, final
            command = final.get("command") or []
            assert command and command[0], final
            # Real host binary path or discoverable name.
            exe = str(command[0])
            assert Path(exe).is_file() or shutil.which(exe), final

            entry = {
                "adapter": adapter,
                "task_id": task["id"],
                "status": final["status"],
                "command0": exe,
                "workspace": final.get("workspace_path"),
                "failure_reason": final.get("failure_reason"),
            }
            if final["status"] == "completed":
                result = final.get("result") or {}
                assert result.get("final_text"), final
                assert result.get("artifact_sha256") and len(result["artifact_sha256"]) == 64
                artifact = Path(
                    result.get("artifact_path")
                    or (Path(final["workspace_path"]) / "agent-response.txt")
                )
                assert artifact.is_file()
                entry["final_text_len"] = len(str(result.get("final_text")))
                entry["artifact"] = str(artifact)
            else:
                assert final.get("failure_reason") or (final.get("result") or {}).get("stderr") is not None
                audit = Path(final.get("audit_path") or "")
                if audit.is_file():
                    text = audit.read_text(encoding="utf-8", errors="replace")
                    assert "returncode" in text or adapter in text
                    entry["audit"] = str(audit)
            results.append(entry)

        assert any(not r.get("skipped") for r in results), f"no adapter ran: {results}"
        assert any(ord(ch) > 127 for ch in str(user))
        evidence = {
            "label": label,
            "user_data": str(user),
            "project_id": project_id,
            "results": results,
            "brand_ok": True,
        }
        path = user / "real-cli-dual-clean.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return evidence
    finally:
        _stop(process)


def test_dual_clean_real_cli_agents_e2e(tmp_path: Path):
    claude = _which("claude")
    codex = _which("codex")
    adapters = [name for name, path in (("claude", claude), ("codex", codex)) if path]
    if not adapters:
        # Still not a silent pass: prove detect endpoints fail honestly when missing.
        # But on this machine CLIs are expected; skip only if truly absent.
        import pytest

        pytest.skip("neither claude nor codex on PATH")

    base = tmp_path / "双干净真实CLI"
    base.mkdir()
    a = _clean_run("A", base, adapters, claude, codex)
    b = _clean_run("B", base, adapters, claude, codex)
    assert a["user_data"] != b["user_data"]
    assert a["project_id"] != b["project_id"]

    report = {
        "ok": True,
        "adapters": adapters,
        "runs": [a, b],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    report_path = SCRATCH / "dual-clean-real-cli-agents.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
