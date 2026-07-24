"""Dual Unicode user-data roots: paper_writing_zh WITH improvement loop ON.

Chinese host path:
paper-plan-zh → paper-analysis → paper-figure → (skip drawio) → paper-write-zh
→ paper-compile-zh → auto-paper-improvement-loop.
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_MIKTEX = Path(r"C:\miktex-portable\texmfs\install\miktex\bin\x64")
if _MIKTEX.is_dir():
    os.environ["PATH"] = str(_MIKTEX) + os.pathsep + os.environ.get("PATH", "")


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
    timeout: int = 90,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={
            "X-Vibe-Session-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
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
    path = os.environ.get("PATH", "")
    if _MIKTEX.is_dir() and str(_MIKTEX) not in path:
        path = str(_MIKTEX) + os.pathsep + path
    env = {
        **os.environ,
        "PATH": path,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
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
        cwd=str(ROOT / "backend"),
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
            raise AssertionError(f"backend exited early: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"backend failed to start: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(port: int, token: str, wf_id: str, *, seconds: float = 720.0) -> dict:
    terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
    deadline = time.time() + seconds
    detail: dict = {}
    while time.time() < deadline:
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        if str(detail.get("status") or "") in terminal:
            return detail
        time.sleep(0.5)
    raise AssertionError(f"workflow {wf_id} did not reach terminal state: {detail}")


def _approve_if_waiting(port: int, token: str, wf_id: str, detail: dict) -> dict:
    hops = 0
    while detail.get("status") == "waiting_checkpoint" and hops < 16:
        status, cp = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/checkpoint",
            "POST",
            {"action": "approve", "data": {"feedback": "dual-clean zh paper auto-approve"}},
        )
        assert status == 200, cp
        detail = _wait_terminal(port, token, wf_id, seconds=480)
        hops += 1
    return detail


def _assert_pdf(path: Path, *, min_bytes: int = 30000) -> None:
    assert path.is_file(), path
    data = path.read_bytes()
    assert data[:4] == b"%PDF", path
    assert len(data) >= min_bytes, f"{path} too small: {len(data)}"


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-中文论文-{label}"
    user.mkdir(parents=True)
    token = f"dual-paper-zh-{label}"
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
                "title": f"ZH paper dual-clean {label}",
                "research_question": "Does paper_writing_zh complete with improvement dual-clean?",
                "inclusion_criteria": "zh host PDF + improvement log",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        status, wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "paper_writing_zh",
                "title": f"证据原生中文论文改进 {label}",
                "params": {
                    "topic": f"证据原生中文论文写作与改进循环 dual-clean {label}",
                    "language": "zh",
                    "skip_drawio": True,
                    "skip_improvement_loop": False,
                    "seed": 13,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, wf
        wf_id = wf["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        ws = Path(detail["workspace_dir"])
        assert any(ord(ch) > 127 for ch in str(user))
        skill_names = [str(s.get("skill_name") or "") for s in (detail.get("steps") or [])]
        assert "paper-plan-zh" in skill_names or "paper-plan" in skill_names, skill_names
        assert "paper-write-zh" in skill_names or "paper-write" in skill_names, skill_names
        assert "auto-paper-improvement-loop" in skill_names, skill_names

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _approve_if_waiting(
            port, token, wf_id, _wait_terminal(port, token, wf_id, seconds=720)
        )
        assert final["status"] == "completed", final

        for rel in (
            "PAPER_PLAN.md",
            "RESULTS.md",
            "paper/main.tex",
            "paper/main.pdf",
            "paper/PAPER_IMPROVEMENT_LOG.md",
        ):
            path = ws / rel
            assert path.is_file() and path.stat().st_size > 40, path

        _assert_pdf(ws / "paper" / "main.pdf", min_bytes=30000)
        tex = (ws / "paper" / "main.tex").read_text(encoding="utf-8")
        assert (ws / "paper" / "main.tex").stat().st_size >= 15000
        # Chinese path should carry CJK in title/topic-derived body.
        assert any("\u4e00" <= ch <= "\u9fff" for ch in tex) or "zh" in tex.lower()

        for skill in (
            "paper-plan-zh",
            "paper-analysis",
            "paper-write-zh",
            "auto-paper-improvement-loop",
        ):
            lineage = ws / ".host_builds" / f"{skill}.json"
            # plan-zh may be stored as paper-plan if engine normalizes; accept either.
            if skill == "paper-plan-zh" and not lineage.is_file():
                lineage = ws / ".host_builds" / "paper-plan.json"
            if skill == "paper-write-zh" and not lineage.is_file():
                lineage = ws / ".host_builds" / "paper-write.json"
            assert lineage.is_file(), skill
            payload = json.loads(lineage.read_text(encoding="utf-8"))
            assert payload.get("executor") == "host_step_runner", skill

        status, export_blob = _request(
            port, token, f"/api/workflows/{wf_id}/export", raw=True, timeout=120
        )
        assert status == 200 and export_blob[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_blob)) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
            assert any(n.endswith("main.pdf") or "paper/main.pdf" in n for n in names)

        return {
            "label": label,
            "project_id": project_id,
            "wf_id": wf_id,
            "ws": str(ws),
            "user_data": str(user),
            "pdf_bytes": (ws / "paper" / "main.pdf").stat().st_size,
            "tex_bytes": (ws / "paper" / "main.tex").stat().st_size,
        }
    finally:
        _stop(process)


def test_dual_clean_paper_writing_zh_with_improvement(tmp_path: Path) -> None:
    base = tmp_path / "双干净中文论文"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert Path(run1["ws"]).resolve() != Path(run2["ws"]).resolve()
    assert "用户数据-中文论文-1" in run1["user_data"]
    assert "用户数据-中文论文-2" in run2["user_data"]
    for run in (run1, run2):
        assert run["pdf_bytes"] >= 30000
        assert run["tex_bytes"] >= 15000
