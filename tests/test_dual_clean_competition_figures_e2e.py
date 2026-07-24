"""Dual Unicode roots: competition workflows with figures ON (skip_figures=False).

Prior competition dual-clean matrices always set skip_figures=True. This proves
UI→API→host paper-figure→comp-paper→compile embeds fig_metrics into PDF under
two clean Unicode user-data roots (ZH cumcm + EN mcm).
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
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_MIKTEX = Path(r"C:\miktex-portable\texmfs\install\miktex\bin\x64")
if _MIKTEX.is_dir():
    os.environ["PATH"] = str(_MIKTEX) + os.pathsep + os.environ.get("PATH", "")

FIGURES_ON_MATRIX = (
    {
        "template": "comp_cumcm",
        "title": "国赛 figures-on",
        "paper_skill": "comp-paper-zh",
        "problem": "【国赛】共享单车调度：在站点需求与运力约束下最小化调度成本，并做敏感性分析。",
        "skip_drawio": True,
        "flowchart_engine": "html",
        "expect_pipeline": False,
    },
    {
        "template": "comp_mcm",
        "title": "MCM figures-on",
        "paper_skill": "comp-paper-en",
        "problem": (
            "MCM shared-bike rebalancing: minimize transport cost under demand "
            "and capacity constraints; report sensitivity on unit cost."
        ),
        "skip_drawio": True,
        "flowchart_engine": "html",
        "expect_pipeline": False,
    },
    {
        "template": "comp_cumcm",
        "title": "国赛 figures+html flowchart",
        "paper_skill": "comp-paper-zh",
        "problem": "【国赛+流程图】共享单车调度与技术路线图：模型-求解-结果全链路。",
        "skip_drawio": False,
        "flowchart_engine": "html",
        "expect_pipeline": True,
    },
)


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
    timeout: int = 60,
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
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
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
    )
    for _ in range(80):
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    raise AssertionError(f"backend failed to start for {user_data}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(port: int, token: str, wf_id: str, seconds: int = 480) -> dict:
    deadline = time.time() + seconds
    last: dict = {}
    while time.time() < deadline:
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        last = detail
        if detail.get("status") in {"completed", "failed", "cancelled"}:
            return detail
        if detail.get("status") == "waiting_checkpoint":
            st, body = _request(
                port,
                token,
                f"/api/workflows/{wf_id}/checkpoint",
                "POST",
                {"action": "approve", "data": {"feedback": "figures-on auto-approve"}},
            )
            assert st in {200, 202, 409}, body
        time.sleep(0.4)
    raise AssertionError(f"workflow {wf_id} not terminal: {last}")


def _assert_pdf(path: Path) -> None:
    assert path.is_file(), path
    assert path.stat().st_size >= 1000, path
    assert path.read_bytes()[:4] == b"%PDF", path


def _run_figures_on(port: int, token: str, project_id: str, label: str, spec: dict) -> dict:
    status, wf = _request(
        port,
        token,
        "/api/workflows",
        "POST",
        {
            "template": spec["template"],
            "title": f"{spec['title']}-{label}",
            "params": {
                "problem_statement": f"[{label}] {spec['problem']}",
                "skip_figures": False,
                "skip_drawio": bool(spec.get("skip_drawio", True)),
                "flowchart_engine": str(spec.get("flowchart_engine") or "html"),
                "skip_analysis": True,
                "skip_improvement_loop": True,
                "min_figures": 1,
            },
            "enable_checkpoints": False,
            "project_id": project_id,
        },
    )
    assert status == 200, (spec["template"], wf)
    wf_id = wf["id"]
    status, detail = _request(port, token, f"/api/workflows/{wf_id}")
    assert status == 200, detail
    ws = Path(detail["workspace_dir"])
    assert any(ord(ch) > 127 for ch in str(ws)), ws

    status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
    assert status == 200, (spec["template"], started)
    final = _wait_terminal(port, token, wf_id, seconds=520)
    assert final["status"] == "completed", (spec["template"], final)

    for rel in (
        "PROBLEM_ANALYSIS.md",
        "MODELING_REPORT.md",
        "RESULTS.md",
        "code/main.py",
        "figures/latex_includes.tex",
        "figures/fig_metrics.pdf",
        "figures/TABLE_metrics.md",
        "paper/main.tex",
        "paper/main.pdf",
    ):
        path = ws / rel
        assert path.is_file() and path.stat().st_size > 40, (spec["template"], path)
    _assert_pdf(ws / "paper" / "main.pdf")
    _assert_pdf(ws / "figures" / "fig_metrics.pdf")

    tex = (ws / "paper" / "main.tex").read_text(encoding="utf-8")
    assert "fig_metrics" in tex, (spec["template"], tex[:400])
    assert "../figures/fig_metrics.pdf" in tex

    for skill in (
        "comp-prob-analysis",
        "comp-modeling",
        "comp-code",
        "paper-figure",
        spec["paper_skill"],
    ):
        lineage = ws / ".host_builds" / f"{skill}.json"
        assert lineage.is_file(), (spec["template"], skill, lineage)
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload.get("executor") == "host_step_runner", (spec["template"], skill, payload)

    if spec.get("expect_pipeline"):
        pipeline = ws / "figures" / "fig_pipeline.pdf"
        assert pipeline.is_file() and pipeline.stat().st_size >= 200, pipeline
        assert "fig_pipeline" in tex or "../figures/fig_pipeline.pdf" in tex, tex[:600]
        html_lineage = ws / ".host_builds" / "paper-figure-html.json"
        assert html_lineage.is_file(), html_lineage
        html_payload = json.loads(html_lineage.read_text(encoding="utf-8"))
        assert html_payload.get("executor") == "host_step_runner", html_payload
    else:
        # DrawIO/HTML must stay skipped when skip_drawio=True.
        steps = final.get("steps") or final.get("sub_steps") or []
        if isinstance(steps, list):
            drawio_like = [
                s
                for s in steps
                if isinstance(s, dict)
                and str(s.get("skill_name") or "")
                in {"paper-figure-drawio", "paper-figure-html"}
            ]
            if drawio_like:
                assert all(str(s.get("status")) == "skipped" for s in drawio_like), drawio_like

    return {
        "template": spec["template"],
        "wf_id": wf_id,
        "ws": str(ws),
        "pdf_bytes": (ws / "paper" / "main.pdf").stat().st_size,
        "fig_bytes": (ws / "figures" / "fig_metrics.pdf").stat().st_size,
        "pipeline": bool(spec.get("expect_pipeline")),
    }


def _matrix_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-竞赛图-{label}"
    user.mkdir(parents=True)
    token = f"dual-comp-fig-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Competition figures dual clean {label}",
                "research_question": "Do competition hosts embed figures under dual-clean roots?",
                "inclusion_criteria": "skip_figures=false host paper-figure",
            },
        )
        assert status == 200, project
        results = []
        for spec in FIGURES_ON_MATRIX:
            results.append(_run_figures_on(port, token, project["id"], label, spec))
        return {
            "label": label,
            "user_data": str(user),
            "results": results,
        }
    finally:
        _stop(process)


def test_dual_clean_competition_figures_on(tmp_path):
    base = tmp_path / "dual-clean-comp-fig"
    base.mkdir()
    run1 = _matrix_run("1", base)
    run2 = _matrix_run("2", base)
    assert len(run1["results"]) == len(FIGURES_ON_MATRIX)
    assert len(run2["results"]) == len(FIGURES_ON_MATRIX)
    ids1 = {r["wf_id"] for r in run1["results"]}
    ids2 = {r["wf_id"] for r in run2["results"]}
    assert ids1.isdisjoint(ids2)
    for run in (run1, run2):
        for item in run["results"]:
            assert item["pdf_bytes"] >= 1000
            assert item["fig_bytes"] >= 200
            assert "用户数据-竞赛图" in item["ws"] or "用户数据-竞赛图" in item["ws"].replace("/", "\\")
