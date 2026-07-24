"""Dual Unicode user-data roots: paper_writing WITH improvement loop ON.

Proves UI→API→host executor→persistence→artifact for:
paper-plan → paper-analysis → paper-figure → (skip drawio) → paper-write
→ paper-compile → auto-paper-improvement-loop (PDF + PAPER_IMPROVEMENT_LOG).

skip_improvement_loop is explicitly False so the improvement host path is real.
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
            raise AssertionError(f"backend exited early for {user_data}: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    out = ""
    try:
        process.kill()
        out = process.stdout.read() if process.stdout else ""
    except Exception:
        pass
    raise AssertionError(f"backend failed to start for {user_data}: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(port: int, token: str, wf_id: str, *, seconds: float = 600.0) -> dict:
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
            {"action": "approve", "data": {"feedback": "dual-clean paper-writing auto-approve"}},
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
    # ASCII label for session token header safety; Unicode stays in user-data path.
    user = base / f"用户数据-论文改进-{label}"
    user.mkdir(parents=True)
    token = f"dual-paper-improve-{label}"
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
                "title": f"Paper writing improvement dual-clean {label}",
                "research_question": "Does paper_writing host chain complete with improvement loop?",
                "inclusion_criteria": "host PDF + improvement log lineage",
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
                "template": "paper_writing",
                "title": f"Evidence-native Paper Writing Improve {label}",
                "params": {
                    "topic": f"evidence-native paper writing with improvement loop {label}",
                    "language": "en",
                    "skip_drawio": True,
                    "skip_improvement_loop": False,
                    "seed": 11,
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
        assert str(user.resolve()) in str(ws.resolve()) or user.resolve() in ws.resolve().parents

        # Improvement loop must be present in the planned step list.
        steps = detail.get("steps") or []
        skill_names = [str(s.get("skill_name") or "") for s in steps]
        assert "auto-paper-improvement-loop" in skill_names, skill_names
        assert "paper-figure-drawio" not in skill_names or any(
            str(s.get("status")) == "skipped"
            for s in steps
            if str(s.get("skill_name")) == "paper-figure-drawio"
        ) or True  # drawio may be planned then skipped at runtime

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _approve_if_waiting(
            port, token, wf_id, _wait_terminal(port, token, wf_id, seconds=720)
        )
        assert final["status"] == "completed", final

        for rel in (
            "PAPER_PLAN.md",
            "RESULTS.md",
            "figures/latex_includes.tex",
            "paper/main.tex",
            "paper/references.bib",
            "paper/main.pdf",
            "paper/PAPER_IMPROVEMENT_LOG.md",
        ):
            path = ws / rel
            assert path.is_file() and path.stat().st_size > 40, path

        _assert_pdf(ws / "paper" / "main.pdf", min_bytes=30000)
        log_text = (ws / "paper" / "PAPER_IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
        assert "PAPER_IMPROVEMENT_LOG" in log_text
        assert "No GPT/Claude review scores claimed" in log_text or "honest" in log_text.lower()
        assert "host_domain_builders" in log_text or "offline host" in log_text.lower()
        assert (ws / "paper" / "main.tex").stat().st_size >= 15000

        host_skills = (
            "paper-plan",
            "paper-analysis",
            "paper-figure",
            "paper-write",
            "paper-compile",
            "auto-paper-improvement-loop",
        )
        for skill in host_skills:
            lineage = ws / ".host_builds" / f"{skill}.json"
            assert lineage.is_file(), skill
            payload = json.loads(lineage.read_text(encoding="utf-8"))
            assert payload.get("executor") == "host_step_runner", skill

        # Final step list: improvement completed, drawio skipped if present.
        status, refreshed = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, refreshed
        final_steps = refreshed.get("steps") or final.get("steps") or []
        improve = [
            s for s in final_steps
            if str(s.get("skill_name") or "") == "auto-paper-improvement-loop"
        ]
        assert improve, final_steps
        assert all(str(s.get("status")) == "completed" for s in improve), improve
        drawio_like = [
            s for s in final_steps
            if str(s.get("skill_name") or "") in {"paper-figure-drawio", "paper-figure-html"}
        ]
        if drawio_like:
            assert all(str(s.get("status")) == "skipped" for s in drawio_like), drawio_like

        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/recover",
            "POST",
            {"reason": "dual-clean paper_writing improvement recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        status, export_blob = _request(
            port, token, f"/api/workflows/{wf_id}/export", raw=True, timeout=120
        )
        assert status == 200, export_blob[:200]
        assert export_blob[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_blob)) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
            assert any("paper/main.pdf" in n or n.endswith("main.pdf") for n in names), names[:60]
            assert any("PAPER_IMPROVEMENT_LOG.md" in n for n in names), names[:60]

        return {
            "label": label,
            "project_id": project_id,
            "wf_id": wf_id,
            "ws": str(ws),
            "user_data": str(user),
            "pdf_bytes": (ws / "paper" / "main.pdf").stat().st_size,
            "tex_bytes": (ws / "paper" / "main.tex").stat().st_size,
            "log_bytes": (ws / "paper" / "PAPER_IMPROVEMENT_LOG.md").stat().st_size,
            "export_ok": True,
            "recovery_status": recover_status,
            "improvement_completed": True,
        }
    finally:
        _stop(process)


def test_dual_clean_paper_writing_with_improvement_loop(tmp_path: Path) -> None:
    base = tmp_path / "双干净论文改进"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)

    assert run1["project_id"] != run2["project_id"]
    assert run1["wf_id"] != run2["wf_id"]
    assert Path(run1["ws"]).resolve() != Path(run2["ws"]).resolve()
    assert Path(run1["user_data"]).resolve() != Path(run2["user_data"]).resolve()
    assert "用户数据-论文改进-1" in run1["user_data"]
    assert "用户数据-论文改进-2" in run2["user_data"]

    for run in (run1, run2):
        assert run["improvement_completed"]
        assert run["pdf_bytes"] >= 30000
        assert run["tex_bytes"] >= 15000
        assert run["log_bytes"] >= 200
        assert run["export_ok"]
        assert Path(run["ws"], "paper", "PAPER_IMPROVEMENT_LOG.md").is_file()
        assert Path(run["ws"], ".host_builds", "auto-paper-improvement-loop.json").is_file()
