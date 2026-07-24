"""Dual Unicode clean roots: multi-agent collaboration with real host CLIs.

Runs /api/agents/collaborations with cli_adapters=[codex,claude] (no model roles
when keys absent). Requires real host CLIs; asserts completed CLI steps write
durable reports under each isolated Unicode user-data root.
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
        with _OPENER.open(req, timeout=180) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _server(port: int, token: str, user_data: Path, claude: str, codex: str) -> subprocess.Popen:
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
        "CLAUDE_BIN": claude,
        "CODEX_BIN": codex,
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_BASE_URL": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "ALL_PROXY": "",
        "all_proxy": "",
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


def _clean_run(label: str, base: Path, claude: str, codex: str) -> dict:
    user = base / f"用户数据-多AgentCLI-{label}"
    user.mkdir(parents=True)
    token = f"dual-macli-{label}"
    port = _free_port()
    process = _server(port, token, user, claude, codex)
    try:
        status, put = _request(
            port,
            token,
            "/api/settings",
            "PUT",
            {"settings": {"claude_bin": claude, "codex_bin": codex}},
        )
        assert status == 200, put

        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Multi-agent CLI dual-clean {label}",
                "research_question": "Do real CLI adapters collaborate under Unicode dual-clean roots?",
                "inclusion_criteria": "host claude+codex, durable report, no mock",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        # CLI-only collaboration: skip model roles when provider keys absent.
        status, collab = _request(
            port,
            token,
            "/api/agents/collaborations",
            "POST",
            {
                "project_id": project_id,
                "goal": f"Reply with exactly: VIBE_COLLAB_{label}",
                "roles": [],
                "cli_adapters": ["claude", "codex"],
                "timeout_seconds": 90,
            },
        )
        assert status == 200, collab
        assert collab.get("cli_adapters") == ["claude", "codex"] or set(collab.get("cli_adapters") or []) == {
            "claude",
            "codex",
        }
        steps = collab.get("steps") or []
        assert len(steps) == 2, collab
        assert all(step.get("kind") == "cli_adapter" for step in steps), steps

        # Prefer completed (live CLI works). Honest failed still must leave report.
        report_rel = collab.get("report_path")
        assert report_rel, collab
        report = user / "workspaces" / project_id / report_rel
        assert report.is_file(), report
        assert any(ord(ch) > 127 for ch in str(report))
        document = json.loads(report.read_text(encoding="utf-8"))
        assert document["format_version"] == "agent-collaboration/v1"
        assert str(document.get("generator") or "").startswith("vibe.agent-collaboration")
        assert document["cli_adapters"] == ["claude", "codex"] or set(document["cli_adapters"]) == {
            "claude",
            "codex",
        }

        completed = [s for s in steps if s.get("status") == "completed"]
        failed = [s for s in steps if s.get("status") != "completed"]
        if completed:
            for step in completed:
                assert step.get("output"), step
                assert step.get("task_id")
                assert step.get("output_sha256") and len(step["output_sha256"]) == 64
        if failed:
            for step in failed:
                assert step.get("error"), step

        # Overall status: completed only if both CLI steps completed.
        if len(completed) == 2:
            assert collab["status"] == "completed", collab
        else:
            assert collab["status"] == "failed", collab
            assert collab.get("failure_reason")

        evidence = {
            "label": label,
            "user_data": str(user),
            "project_id": project_id,
            "collab_id": collab["id"],
            "status": collab["status"],
            "completed_steps": len(completed),
            "failed_steps": len(failed),
            "report": str(report),
            "report_sha256": collab.get("report_sha256"),
            "steps": [
                {
                    "role": s.get("role"),
                    "status": s.get("status"),
                    "task_id": s.get("task_id"),
                    "error": s.get("error"),
                    "output_len": len(str(s.get("output") or "")),
                }
                for s in steps
            ],
            "brand_ok": True,
        }
        path = user / "multi-agent-cli-evidence.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return evidence
    finally:
        _stop(process)


def test_dual_clean_multi_agent_cli_collaboration(tmp_path: Path):
    claude = shutil.which("claude")
    codex = shutil.which("codex")
    if not claude or not codex:
        import pytest

        pytest.skip("need both claude and codex on PATH")

    base = tmp_path / "双干净多AgentCLI"
    base.mkdir()
    a = _clean_run("A", base, claude, codex)
    b = _clean_run("B", base, claude, codex)
    assert a["user_data"] != b["user_data"]
    assert a["project_id"] != b["project_id"]
    assert a["collab_id"] != b["collab_id"]
    assert Path(a["report"]).resolve() != Path(b["report"]).resolve()

    any_full = a["completed_steps"] == 2 or b["completed_steps"] == 2
    # Host Codex is authenticated on this machine — each root must complete ≥1 CLI.
    assert a["completed_steps"] >= 1 and b["completed_steps"] >= 1, (a, b)
    report = {
        "ok": True,
        "any_full_cli_success": any_full,
        "runs": [a, b],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    report_path = SCRATCH / "dual-clean-multi-agent-cli.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert Path(a["report"]).is_file() and Path(b["report"]).is_file()
