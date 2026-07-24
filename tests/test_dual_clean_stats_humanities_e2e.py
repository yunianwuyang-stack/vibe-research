"""Dual Unicode user-data: comp_stats topic host + humanities LaTeX compile."""
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
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, token: str, path: str, method: str = "GET", body: dict | None = None, timeout: int = 60):
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
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        payload = error.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"detail": payload}
        return error.code, parsed


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    env = {
        **os.environ,
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
    for _ in range(150):
        if process.poll() is not None:
            out = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"backend exited early for {user_data}: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"backend failed to start for {user_data}: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(port: int, token: str, wf_id: str, seconds: int = 300) -> dict:
    terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
    last: dict = {}
    for _ in range(max(1, seconds * 2)):
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        last = detail
        if detail.get("status") in terminal:
            return detail
        time.sleep(0.5)
    return last


def _approve_if_waiting(port: int, token: str, wf_id: str, detail: dict) -> dict:
    guard = 0
    while detail.get("status") == "waiting_checkpoint" and guard < 12:
        guard += 1
        status, approved = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/approve",
            "POST",
            {"decision": "approve", "feedback": "dual-clean auto-approve"},
        )
        assert status == 200, approved
        detail = _wait_terminal(port, token, wf_id, seconds=240)
    return detail


def _assert_pdf(path: Path) -> None:
    assert path.is_file() and path.stat().st_size >= 1000, path
    assert path.read_bytes()[:4] == b"%PDF"


def _clean_run(label: str, base: Path) -> dict:
    user_data = base / f"用户数据-{label}"
    user_data.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    token = f"dual-stats-hum-{label}-{port}"
    process = _server(port, token, user_data)
    try:
        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"统计人文 dual clean {label}",
                "research_question": "Can stats topic and humanities latex host chains complete offline?",
                "inclusion_criteria": "host scaffold dual-clean unicode user-data",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        # --- comp_stats: topic → code → (skip figs) → paper → compile ---
        status, stats_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "comp_stats",
                "title": f"区域创新效率-{label}",
                "params": {
                    "topic": f"区域创新效率影响因素-{label}",
                    "skip_figures": True,
                    "skip_drawio": True,
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, stats_wf
        stats_id = stats_wf["id"]
        status, stats_detail = _request(port, token, f"/api/workflows/{stats_id}")
        assert status == 200, stats_detail
        stats_ws = Path(stats_detail["workspace_dir"])
        status, started = _request(port, token, f"/api/workflows/{stats_id}/start", "POST")
        assert status == 200, started
        stats_final = _approve_if_waiting(
            port, token, stats_id, _wait_terminal(port, token, stats_id, seconds=420)
        )
        assert stats_final["status"] == "completed", stats_final
        topic = stats_ws / "TOPIC_PLAN.md"
        assert topic.is_file() and topic.stat().st_size >= 1000, topic
        text = topic.read_text(encoding="utf-8")
        assert "BEGIN FIGURE_MANIFEST" in text and "END FIGURE_MANIFEST" in text
        for rel in ("RESULTS.md", "code/main.py", "paper/main.tex", "paper/main.pdf"):
            path = stats_ws / rel
            assert path.is_file() and path.stat().st_size > 40, path
        _assert_pdf(stats_ws / "paper" / "main.pdf")
        for skill in ("comp-stats-topic", "comp-code", "comp-paper-zh"):
            lineage = stats_ws / ".host_builds" / f"{skill}.json"
            assert lineage.is_file(), skill
            assert json.loads(lineage.read_text(encoding="utf-8")).get("executor") == "host_step_runner"

        # --- humanities_paper latex/pdf path: plan → write-latex → compile ---
        status, hum_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "humanities_paper",
                "title": f"叙事与证据伦理-{label}",
                "params": {
                    "subject_domain": "literature",
                    "output_format": "pdf",
                    "skip_figures": True,
                    "skip_drawio": True,
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, hum_wf
        hum_id = hum_wf["id"]
        status, hum_detail = _request(port, token, f"/api/workflows/{hum_id}")
        assert status == 200, hum_detail
        hum_ws = Path(hum_detail["workspace_dir"])
        status, started = _request(port, token, f"/api/workflows/{hum_id}/start", "POST")
        assert status == 200, started
        hum_final = _approve_if_waiting(
            port, token, hum_id, _wait_terminal(port, token, hum_id, seconds=420)
        )
        assert hum_final["status"] == "completed", hum_final
        tex = hum_ws / "paper" / "main.tex"
        pdf = hum_ws / "paper" / "main.pdf"
        assert tex.is_file() and tex.stat().st_size >= 5000, tex
        _assert_pdf(pdf)
        lineage = hum_ws / ".host_builds" / "humanities-write-latex.json"
        assert lineage.is_file(), lineage
        assert json.loads(lineage.read_text(encoding="utf-8")).get("executor") == "host_step_runner"

        return {
            "label": label,
            "stats_id": stats_id,
            "hum_id": hum_id,
            "stats_ws": str(stats_ws),
            "hum_ws": str(hum_ws),
            "stats_pdf_bytes": (stats_ws / "paper" / "main.pdf").stat().st_size,
            "hum_pdf_bytes": pdf.stat().st_size,
            "topic_bytes": topic.stat().st_size,
        }
    finally:
        _stop(process)


def test_dual_clean_stats_and_humanities_latex_independent(tmp_path: Path) -> None:
    base = tmp_path / "双干净统计人文"
    base.mkdir()
    # Labels must be ASCII: session token is sent as an HTTP header (latin-1).
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)
    assert run1["stats_id"] != run2["stats_id"]
    assert run1["hum_id"] != run2["hum_id"]
    assert Path(run1["stats_ws"]).resolve() != Path(run2["stats_ws"]).resolve()
    assert Path(run1["hum_ws"]).resolve() != Path(run2["hum_ws"]).resolve()
    assert run1["stats_pdf_bytes"] >= 1000 and run2["stats_pdf_bytes"] >= 1000
    assert run1["hum_pdf_bytes"] >= 1000 and run2["hum_pdf_bytes"] >= 1000
    assert run1["topic_bytes"] >= 1000 and run2["topic_bytes"] >= 1000
