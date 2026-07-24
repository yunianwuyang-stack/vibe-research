"""Dual Unicode user-data roots: thesis / humanities / CUMCM host full chains."""
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

# Ensure portable MiKTeX is visible to the backend compile step.
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


def _wait_terminal(port: int, token: str, wf_id: str, *, seconds: float = 300.0) -> dict:
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
    """Auto-approve host checkpoints so dual-clean can finish offline."""
    hops = 0
    while detail.get("status") == "waiting_checkpoint" and hops < 12:
        status, cp = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/checkpoint",
            "POST",
            {"action": "approve", "data": {"feedback": "dual-clean domain auto-approve"}},
        )
        assert status == 200, cp
        detail = _wait_terminal(port, token, wf_id, seconds=240)
        hops += 1
    return detail


def _assert_docx(path: Path) -> None:
    assert path.is_file() and path.stat().st_size >= 800, path
    with zipfile.ZipFile(path) as archive:
        assert "word/document.xml" in archive.namelist()


def _assert_pdf(path: Path) -> None:
    assert path.is_file() and path.stat().st_size >= 1000, path
    assert path.read_bytes()[:4] == b"%PDF"


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-领域-{label}"
    user.mkdir(parents=True)
    token = f"dual-domain-{label}"
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
                "title": f"领域双干净 {label}",
                "research_question": "Do dual-clean roots complete host domain scaffolds?",
                "inclusion_criteria": "host executor artifacts with lineage",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        # --- literature_review: host scaffold + docx (honest unverified) ---
        status, lit_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "literature_review",
                "title": f"证据原生科研Agent综述-{label}",
                "params": {
                    "topic": "可审计科研执行与证据门禁",
                    "target_paper_count": 12,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, lit_wf
        lit_id = lit_wf["id"]
        status, lit_detail = _request(port, token, f"/api/workflows/{lit_id}")
        assert status == 200, lit_detail
        lit_ws = Path(lit_detail["workspace_dir"])
        status, started = _request(port, token, f"/api/workflows/{lit_id}/start", "POST")
        assert status == 200, started
        lit_final = _approve_if_waiting(
            port, token, lit_id, _wait_terminal(port, token, lit_id, seconds=240)
        )
        assert lit_final["status"] == "completed", lit_final
        lit_md = lit_ws / "LITERATURE_REVIEW.md"
        lit_docx = lit_ws / "LITERATURE_REVIEW.docx"
        lit_lineage = lit_ws / ".host_builds" / "literature-review.json"
        assert lit_md.is_file() and lit_md.stat().st_size >= 5000
        assert "待核验" in lit_md.read_text(encoding="utf-8")
        _assert_docx(lit_docx)
        assert lit_lineage.is_file()
        assert json.loads(lit_lineage.read_text(encoding="utf-8")).get("executor") == "host_step_runner"

        # --- one_sentence_project / project-blueprint host ---
        status, bp_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "one_sentence_project",
                "title": f"一句话项目-{label}",
                "params": {
                    "one_sentence": f"从开题到PDF的证据原生链路-{label}",
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, bp_wf
        bp_id = bp_wf["id"]
        status, bp_detail = _request(port, token, f"/api/workflows/{bp_id}")
        assert status == 200, bp_detail
        bp_ws = Path(bp_detail["workspace_dir"])
        status, started = _request(port, token, f"/api/workflows/{bp_id}/start", "POST")
        assert status == 200, started
        bp_final = _approve_if_waiting(
            port, token, bp_id, _wait_terminal(port, token, bp_id, seconds=120)
        )
        assert bp_final["status"] == "completed", bp_final
        for name in ("PROJECT_BLUEPRINT.md", "RESEARCH_CONTRACT_DRAFT.md", "MILESTONES.md"):
            path = bp_ws / name
            assert path.is_file() and path.stat().st_size >= 80, path
        assert (bp_ws / ".host_builds" / "project-blueprint.json").is_file()

        # --- thesis_proposal: host draft + format-check + docx (skip drawio) ---
        status, thesis_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "thesis_proposal",
                "title": f"证据原生科研Agent开题-{label}",
                "params": {
                    "degree_level": "phd",
                    "topic": "可审计科研执行与证据门禁",
                    "skip_drawio": True,
                    "skip_figures": True,
                    "skip_analysis": True,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, thesis_wf
        thesis_id = thesis_wf["id"]
        status, thesis_detail = _request(port, token, f"/api/workflows/{thesis_id}")
        assert status == 200, thesis_detail
        thesis_ws = Path(thesis_detail["workspace_dir"])

        status, started = _request(port, token, f"/api/workflows/{thesis_id}/start", "POST")
        assert status == 200, started
        thesis_final = _approve_if_waiting(
            port, token, thesis_id, _wait_terminal(port, token, thesis_id, seconds=240)
        )
        assert thesis_final["status"] == "completed", thesis_final
        thesis_md = thesis_ws / "PROPOSAL.md"
        thesis_docx = thesis_ws / "PROPOSAL.docx"
        thesis_lineage = thesis_ws / ".host_builds" / "thesis-proposal.json"
        assert thesis_md.is_file() and thesis_md.stat().st_size >= 400
        _assert_docx(thesis_docx)
        assert thesis_lineage.is_file()
        lineage = json.loads(thesis_lineage.read_text(encoding="utf-8"))
        assert lineage.get("executor") == "host_step_runner"
        assert lineage.get("skill_name") == "thesis-proposal"

        # --- humanities_paper: plan + write + docx, skip analysis/figures/drawio ---
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
                    "skip_analysis": True,
                    "skip_figures": True,
                    "skip_drawio": True,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
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
            port, token, hum_id, _wait_terminal(port, token, hum_id, seconds=240)
        )
        assert hum_final["status"] == "completed", hum_final
        hum_md = hum_ws / "HUMANITIES_PAPER.md"
        hum_docx = hum_ws / "HUMANITIES_PAPER.docx"
        hum_plan_lineage = hum_ws / ".host_builds" / "humanities-plan.json"
        hum_write_lineage = hum_ws / ".host_builds" / "humanities-write.json"
        assert hum_md.is_file() and hum_md.stat().st_size >= 300
        _assert_docx(hum_docx)
        assert hum_plan_lineage.is_file() and hum_write_lineage.is_file()

        # --- course_paper: host plan/write/docx offline ---
        status, course_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "course_paper",
                "title": f"分布式系统课程论文-{label}",
                "params": {
                    "subject_domain": "cs",
                    "skip_analysis": True,
                    "skip_figures": True,
                    "skip_drawio": True,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
                    "word_count_target": 6000,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, course_wf
        course_id = course_wf["id"]
        status, course_detail = _request(port, token, f"/api/workflows/{course_id}")
        assert status == 200, course_detail
        course_ws = Path(course_detail["workspace_dir"])

        status, started = _request(port, token, f"/api/workflows/{course_id}/start", "POST")
        assert status == 200, started
        course_final = _approve_if_waiting(
            port, token, course_id, _wait_terminal(port, token, course_id, seconds=240)
        )
        assert course_final["status"] == "completed", course_final
        course_docx = course_ws / "COURSE_PAPER.docx"
        _assert_docx(course_docx)
        assert (course_ws / ".host_builds" / "course-plan.json").is_file()
        assert (course_ws / ".host_builds" / "course-paper.json").is_file()

        # --- course_report: host plan/write/docx offline (family academic surface) ---
        status, report_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "course_report",
                "title": f"软件工程课程报告-{label}",
                "params": {
                    "subject_domain": "cs",
                    "skip_analysis": True,
                    "skip_figures": True,
                    "skip_drawio": True,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
                    "word_count_target": 8000,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, report_wf
        report_id = report_wf["id"]
        status, report_detail = _request(port, token, f"/api/workflows/{report_id}")
        assert status == 200, report_detail
        report_ws = Path(report_detail["workspace_dir"])

        status, started = _request(port, token, f"/api/workflows/{report_id}/start", "POST")
        assert status == 200, started
        report_final = _approve_if_waiting(
            port, token, report_id, _wait_terminal(port, token, report_id, seconds=240)
        )
        assert report_final["status"] == "completed", report_final
        report_md = report_ws / "COURSE_REPORT.md"
        report_docx = report_ws / "COURSE_REPORT.docx"
        assert report_md.is_file() and report_md.stat().st_size >= 200
        _assert_docx(report_docx)
        assert (report_ws / ".host_builds" / "course-report-plan.json").is_file()
        assert (report_ws / ".host_builds" / "course-report.json").is_file()
        for skill in ("course-report-plan", "course-report"):
            lineage = report_ws / ".host_builds" / f"{skill}.json"
            payload = json.loads(lineage.read_text(encoding="utf-8"))
            assert payload.get("executor") == "host_step_runner", (skill, payload)

        # --- paper_from_assets: inventory → plan → analysis → write → compile ---
        status, assets_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "paper_from_assets",
                "title": f"资产论文-{label}",
                "params": {
                    "skip_figures": False,
                    "skip_drawio": True,
                    "skip_analysis": False,
                    "skip_improvement_loop": True,
                    "paper_type_target": "academic_en",
                    "language": "en",
                    "output_format": "pdf",
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, assets_wf
        assets_id = assets_wf["id"]
        status, assets_detail = _request(port, token, f"/api/workflows/{assets_id}")
        assert status == 200, assets_detail
        assets_ws = Path(assets_detail["workspace_dir"])
        # Seed requirements-role asset (start gate requires declared role)
        req_body = (
            f"# 写作要求 {label}\n\n"
            "主题：证据原生科研 Agent。\n"
            "目标：主机脚手架离线编译 PDF。\n"
        )
        status, put = _request(
            port,
            token,
            f"/api/editor/{assets_id}/file",
            "PUT",
            {"path": "user_data/requirements.md", "content": req_body},
        )
        assert status == 200, put
        manifest = {
            "files": {
                "requirements.md": {
                    "role": "requirements",
                    "name": "requirements.md",
                    "size": len(req_body.encode("utf-8")),
                }
            }
        }
        status, put = _request(
            port,
            token,
            f"/api/editor/{assets_id}/file",
            "PUT",
            {
                "path": "user_data/_input_manifest.json",
                "content": json.dumps(manifest, ensure_ascii=False, indent=2),
            },
        )
        assert status == 200, put
        status, started = _request(port, token, f"/api/workflows/{assets_id}/start", "POST")
        assert status == 200, started
        assets_final = _approve_if_waiting(
            port, token, assets_id, _wait_terminal(port, token, assets_id, seconds=420)
        )
        assert assets_final["status"] == "completed", assets_final
        for rel in (
            "ASSETS_INVENTORY.md",
            "PAPER_PLAN.md",
            "RESULTS.md",
            "figures/latex_includes.tex",
            "figures/fig_metrics.pdf",
            "figures/TABLE_metrics.md",
            "paper/main.tex",
            "paper/main.pdf",
        ):
            path = assets_ws / rel
            assert path.is_file() and path.stat().st_size > 40, path
        _assert_pdf(assets_ws / "paper" / "main.pdf")
        for skill in ("paper-plan", "paper-analysis", "paper-figure", "paper-write"):
            assert (assets_ws / ".host_builds" / f"{skill}.json").is_file(), skill

        # --- comp_cumcm: problem → model → code → paper → compile PDF ---
        problem = (
            f"【{label}】共享单车调度：给定站点需求与运力，"
            "建立优化模型最小化调度成本，并做敏感性分析。"
        )
        status, cumcm_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "comp_cumcm",
                "title": f"共享单车调度-{label}",
                "params": {
                    "problem_statement": problem,
                    "skip_figures": True,
                    "skip_drawio": True,
                    "skip_analysis": True,
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, cumcm_wf
        cumcm_id = cumcm_wf["id"]
        status, cumcm_detail = _request(port, token, f"/api/workflows/{cumcm_id}")
        assert status == 200, cumcm_detail
        cumcm_ws = Path(cumcm_detail["workspace_dir"])

        status, started = _request(port, token, f"/api/workflows/{cumcm_id}/start", "POST")
        assert status == 200, started
        cumcm_final = _approve_if_waiting(
            port, token, cumcm_id, _wait_terminal(port, token, cumcm_id, seconds=420)
        )
        assert cumcm_final["status"] == "completed", cumcm_final
        for rel in (
            "PROBLEM_ANALYSIS.md",
            "MODELING_REPORT.md",
            "RESULTS.md",
            "code/main.py",
            "paper/main.tex",
            "paper/main.pdf",
        ):
            path = cumcm_ws / rel
            assert path.is_file() and path.stat().st_size > 40, path
        _assert_pdf(cumcm_ws / "paper" / "main.pdf")
        for skill in (
            "comp-prob-analysis",
            "comp-modeling",
            "comp-code",
            "comp-paper-zh",
        ):
            lineage_path = cumcm_ws / ".host_builds" / f"{skill}.json"
            assert lineage_path.is_file(), lineage_path
            payload = json.loads(lineage_path.read_text(encoding="utf-8"))
            assert payload.get("executor") == "host_step_runner"

        # --- idea_discovery: lit → idea → novelty → review → refine (host) ---
        status, idea_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "idea_discovery",
                "title": f"Idea发现-{label}",
                "params": {
                    "topic": f"证据原生科研Agent方向探索-{label}",
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, idea_wf
        idea_id = idea_wf["id"]
        status, idea_detail = _request(port, token, f"/api/workflows/{idea_id}")
        assert status == 200, idea_detail
        idea_ws = Path(idea_detail["workspace_dir"])
        status, started = _request(port, token, f"/api/workflows/{idea_id}/start", "POST")
        assert status == 200, started
        idea_final = _approve_if_waiting(
            port, token, idea_id, _wait_terminal(port, token, idea_id, seconds=300)
        )
        assert idea_final["status"] == "completed", idea_final
        for rel in (
            "literature_review.md",
            "references.bib",
            "IDEA_REPORT.md",
            "novelty_check_report.md",
            "review_report.md",
            "refine-logs/FINAL_PROPOSAL.md",
            "refine-logs/EXPERIMENT_PLAN.md",
        ):
            path = idea_ws / rel
            assert path.is_file() and path.stat().st_size > 40, path
        assert (idea_ws / "literature_review.md").stat().st_size >= 1500
        assert (idea_ws / "IDEA_REPORT.md").stat().st_size >= 1500
        assert (idea_ws / "refine-logs" / "FINAL_PROPOSAL.md").stat().st_size >= 1500
        for skill in (
            "research-lit",
            "idea-creator",
            "novelty-check",
            "research-review",
            "research-refine-pipeline",
        ):
            lineage = idea_ws / ".host_builds" / f"{skill}.json"
            assert lineage.is_file(), skill
            assert json.loads(lineage.read_text(encoding="utf-8")).get("executor") == "host_step_runner"

        # --- experiment_bridge: plan → real CPU run → results/JSON/figures ---
        status, bridge_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "experiment_bridge",
                "title": f"实验桥接-{label}",
                "params": {
                    "topic": f"可审计实验复现与基线对比-{label}",
                    "seed": 42,
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, bridge_wf
        bridge_id = bridge_wf["id"]
        status, bridge_detail = _request(port, token, f"/api/workflows/{bridge_id}")
        assert status == 200, bridge_detail
        bridge_ws = Path(bridge_detail["workspace_dir"])
        status, started = _request(port, token, f"/api/workflows/{bridge_id}/start", "POST")
        assert status == 200, started
        bridge_final = _approve_if_waiting(
            port, token, bridge_id, _wait_terminal(port, token, bridge_id, seconds=240)
        )
        assert bridge_final["status"] == "completed", bridge_final
        for rel in (
            "experiment_results.md",
            "refine-logs/EXPERIMENT_PLAN.md",
            "refine-logs/EXPERIMENT_TRACKER.md",
            "code/experiments/run_bridge.py",
            "results/m2_main.json",
            "figures/experiment_data.json",
            "figures/latex_includes.tex",
            "figures/fig_metrics.pdf",
            "figures/TABLE_main_results.md",
        ):
            path = bridge_ws / rel
            assert path.is_file() and path.stat().st_size > 40, path
        bridge_md = bridge_ws / "experiment_results.md"
        assert bridge_md.stat().st_size >= 500
        bridge_data = json.loads(
            (bridge_ws / "figures" / "experiment_data.json").read_text(encoding="utf-8")
        )
        assert bridge_data.get("main_results", {}).get("method_beats_baseline") is True
        bridge_lineage = bridge_ws / ".host_builds" / "experiment-bridge.json"
        assert bridge_lineage.is_file()
        assert json.loads(bridge_lineage.read_text(encoding="utf-8")).get("executor") == "host_step_runner"

        # --- auto_review: narrative + AUTO_REVIEW from local evidence ---
        status, review_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "auto_review",
                "title": f"自动审稿-{label}",
                "params": {
                    "topic": f"证据原生科研Agent审稿-{label}",
                    "max_rounds": 1,
                    "target_score": 6,
                    "output_format": "markdown",
                    "skip_improvement_loop": True,
                },
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, review_wf
        review_id = review_wf["id"]
        status, review_detail = _request(port, token, f"/api/workflows/{review_id}")
        assert status == 200, review_detail
        review_ws = Path(review_detail["workspace_dir"])
        # Seed experiment evidence into this workspace so narrative is grounded.
        seed_body = (bridge_ws / "experiment_results.md").read_text(encoding="utf-8")
        status, put = _request(
            port,
            token,
            f"/api/editor/{review_id}/file",
            "PUT",
            {"path": "experiment_results.md", "content": seed_body},
        )
        assert status == 200, put
        seed_json = (bridge_ws / "figures" / "experiment_data.json").read_text(encoding="utf-8")
        status, put = _request(
            port,
            token,
            f"/api/editor/{review_id}/file",
            "PUT",
            {"path": "figures/experiment_data.json", "content": seed_json},
        )
        assert status == 200, put
        status, started = _request(port, token, f"/api/workflows/{review_id}/start", "POST")
        assert status == 200, started
        review_final = _approve_if_waiting(
            port, token, review_id, _wait_terminal(port, token, review_id, seconds=240)
        )
        assert review_final["status"] == "completed", review_final
        for rel in ("NARRATIVE_REPORT.md", "AUTO_REVIEW.md", "REVIEW_STATE.json"):
            path = review_ws / rel
            assert path.is_file() and path.stat().st_size > 40, path
        assert (review_ws / "NARRATIVE_REPORT.md").stat().st_size >= 1000
        review_lineage = review_ws / ".host_builds" / "auto-review-loop.json"
        assert review_lineage.is_file()
        assert json.loads(review_lineage.read_text(encoding="utf-8")).get("executor") == "host_step_runner"

        # recovery + export evidence on thesis workflow
        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{thesis_id}/recover",
            "POST",
            {"reason": "dual-clean domain recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        status, export_blob = _request(
            port, token, f"/api/workflows/{thesis_id}/export", raw=True, timeout=90
        )
        assert status == 200, export_blob[:200]
        assert export_blob[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_blob)) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
            assert any(n.endswith("PROPOSAL.docx") or n.endswith("PROPOSAL.md") for n in names), names[:40]

        return {
            "label": label,
            "project_id": project_id,
            "lit_id": lit_id,
            "bp_id": bp_id,
            "thesis_id": thesis_id,
            "hum_id": hum_id,
            "course_id": course_id,
            "report_id": report_id,
            "assets_id": assets_id,
            "cumcm_id": cumcm_id,
            "bridge_id": bridge_id,
            "idea_id": idea_id,
            "review_id": review_id,
            "lit_ws": str(lit_ws),
            "bp_ws": str(bp_ws),
            "thesis_ws": str(thesis_ws),
            "hum_ws": str(hum_ws),
            "course_ws": str(course_ws),
            "report_ws": str(report_ws),
            "assets_ws": str(assets_ws),
            "cumcm_ws": str(cumcm_ws),
            "bridge_ws": str(bridge_ws),
            "idea_ws": str(idea_ws),
            "review_ws": str(review_ws),
            "lit_docx_bytes": lit_docx.stat().st_size,
            "thesis_docx_bytes": thesis_docx.stat().st_size,
            "hum_docx_bytes": hum_docx.stat().st_size,
            "course_docx_bytes": course_docx.stat().st_size,
            "report_docx_bytes": report_docx.stat().st_size,
            "assets_pdf_bytes": (assets_ws / "paper" / "main.pdf").stat().st_size,
            "cumcm_pdf_bytes": (cumcm_ws / "paper" / "main.pdf").stat().st_size,
            "bridge_results_bytes": bridge_md.stat().st_size,
            "idea_report_bytes": (idea_ws / "IDEA_REPORT.md").stat().st_size,
            "narrative_bytes": (review_ws / "NARRATIVE_REPORT.md").stat().st_size,
            "recovery_status": recover_status,
            "export_ok": True,
        }
    finally:
        _stop(process)


def test_dual_clean_domain_host_chains_independent(tmp_path: Path) -> None:
    base = tmp_path / "双干净领域"
    base.mkdir()
    run1 = _clean_run("A", base)
    run2 = _clean_run("B", base)
    assert run1["thesis_id"] != run2["thesis_id"]
    assert run1["lit_id"] != run2["lit_id"]
    assert run1["cumcm_id"] != run2["cumcm_id"]
    assert run1["bridge_id"] != run2["bridge_id"]
    assert run1["idea_id"] != run2["idea_id"]
    assert run1["review_id"] != run2["review_id"]
    assert Path(run1["thesis_ws"]).resolve() != Path(run2["thesis_ws"]).resolve()
    assert Path(run1["cumcm_ws"]).resolve() != Path(run2["cumcm_ws"]).resolve()
    assert Path(run1["bridge_ws"]).resolve() != Path(run2["bridge_ws"]).resolve()
    assert Path(run1["idea_ws"]).resolve() != Path(run2["idea_ws"]).resolve()
    assert Path(run1["review_ws"]).resolve() != Path(run2["review_ws"]).resolve()
    assert run1["lit_docx_bytes"] >= 800 and run2["lit_docx_bytes"] >= 800
    assert run1["thesis_docx_bytes"] >= 800 and run2["thesis_docx_bytes"] >= 800
    assert run1["hum_docx_bytes"] >= 800 and run2["hum_docx_bytes"] >= 800
    assert run1["course_docx_bytes"] >= 800 and run2["course_docx_bytes"] >= 800
    assert run1["report_id"] != run2["report_id"]
    assert Path(run1["report_ws"]).resolve() != Path(run2["report_ws"]).resolve()
    assert run1["report_docx_bytes"] >= 800 and run2["report_docx_bytes"] >= 800
    assert run1["assets_pdf_bytes"] >= 1000 and run2["assets_pdf_bytes"] >= 1000
    assert run1["cumcm_pdf_bytes"] >= 1000 and run2["cumcm_pdf_bytes"] >= 1000
    assert run1["bridge_results_bytes"] >= 500 and run2["bridge_results_bytes"] >= 500
    assert run1["idea_report_bytes"] >= 1500 and run2["idea_report_bytes"] >= 1500
    assert run1["narrative_bytes"] >= 1000 and run2["narrative_bytes"] >= 1000
    assert run1["export_ok"] and run2["export_ok"]
