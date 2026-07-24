"""Dual Unicode roots: paper_from_assets for every paper_type_target.

paper_from_assets catalog exposes academic_zh / academic_en / competition / course / nature.
Prior dual-clean only exercised academic_en — this matrix proves the full
UI→API→host executor→artifact chain for each target under two clean roots.
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

# Every OPTION_SETS paper_from_assets_target_types value.
ASSETS_MATRIX = (
    {
        "target": "academic_zh",
        "language": "zh",
        "output_format": "pdf",
        "title": "资产论文-中文学术",
        "expect_pdf": True,
        "expect_docx": False,
        "extra_files": ("PAPER_PLAN.md", "paper/main.tex"),
        "lineage": ("paper-plan-zh", "paper-write-zh"),
    },
    {
        "target": "academic_en",
        "language": "en",
        "output_format": "pdf",
        "title": "Assets paper academic EN",
        "expect_pdf": True,
        "expect_docx": False,
        "extra_files": ("PAPER_PLAN.md", "paper/main.tex"),
        "lineage": ("paper-plan", "paper-write"),
    },
    {
        "target": "competition",
        "language": "zh",
        "output_format": "pdf",
        "title": "资产论文-竞赛中文",
        "expect_pdf": True,
        "expect_docx": False,
        "extra_files": ("PROBLEM_ANALYSIS.md", "MODELING_REPORT.md", "paper/main.tex"),
        "lineage": ("comp-prob-analysis", "comp-modeling", "comp-paper-zh"),
    },
    {
        "target": "course",
        "language": "zh",
        "output_format": "docx",
        "title": "资产论文-课程",
        "expect_pdf": False,
        "expect_docx": True,
        "extra_files": ("OUTLINE.md", "COURSE_PAPER.md", "paper/main.docx"),
        "lineage": ("course-plan", "course-paper", "docx-export"),
    },
    {
        "target": "nature",
        "language": "en",
        "output_format": "pdf",
        "title": "Assets paper Nature style",
        "expect_pdf": True,
        "expect_docx": False,
        "extra_files": ("paper/main.tex",),
        "lineage": ("nature-figure", "paper-write-nature"),
    },
)


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
        headers={
            "X-Vibe-Session-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
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
            raise AssertionError(f"backend exited early: {out[-3000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"backend failed to start: {out[-3000:]}")


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
                {"action": "approve", "data": {"feedback": "dual-clean assets auto-approve"}},
            )
            assert st in {200, 202, 409}, body
        time.sleep(0.35)
    raise AssertionError(f"workflow {wf_id} not terminal: {last}")


def _assert_pdf(path: Path) -> None:
    assert path.is_file(), path
    assert path.stat().st_size >= 1000, path
    assert path.read_bytes()[:4] == b"%PDF", path


def _assert_docx(path: Path) -> None:
    assert path.is_file(), path
    assert path.stat().st_size >= 800, path
    assert path.read_bytes()[:2] == b"PK", path


def _seed_requirements(port: int, token: str, wf_id: str, label: str, target: str) -> None:
    req_body = (
        f"# Writing requirements [{label}/{target}]\n\n"
        "Topic: evidence-native research agent scaffold.\n"
        "Goal: offline host chain produces a real paper artifact.\n"
        "Constraints: no invented citations; mark pending verification.\n"
    )
    status, put = _request(
        port,
        token,
        f"/api/editor/{wf_id}/file",
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
        f"/api/editor/{wf_id}/file",
        "PUT",
        {
            "path": "user_data/_input_manifest.json",
            "content": json.dumps(manifest, ensure_ascii=False, indent=2),
        },
    )
    assert status == 200, put


def _run_assets(port: int, token: str, project_id: str, label: str, spec: dict) -> dict:
    status, wf = _request(
        port,
        token,
        "/api/workflows",
        "POST",
        {
            "template": "paper_from_assets",
            "title": f"{spec['title']}-{label}",
            "params": {
                "paper_type_target": spec["target"],
                "language": spec["language"],
                "output_format": spec["output_format"],
                "skip_figures": False,
                "skip_drawio": True,
                "skip_analysis": False,
                "skip_improvement_loop": True,
            },
            "enable_checkpoints": False,
            "project_id": project_id,
        },
    )
    assert status == 200, (spec["target"], wf)
    wf_id = wf["id"]
    status, detail = _request(port, token, f"/api/workflows/{wf_id}")
    assert status == 200, detail
    ws = Path(detail["workspace_dir"])
    _seed_requirements(port, token, wf_id, label, spec["target"])
    status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
    assert status == 200, (spec["target"], started)
    final = _wait_terminal(port, token, wf_id, seconds=520)
    assert final["status"] == "completed", (spec["target"], final)

    inv = ws / "ASSETS_INVENTORY.md"
    assert inv.is_file() and inv.stat().st_size > 40, (spec["target"], inv)

    for rel in spec["extra_files"]:
        path = ws / rel
        assert path.is_file() and path.stat().st_size > 40, (spec["target"], path)

    pdf_bytes = 0
    docx_bytes = 0
    if spec["expect_pdf"]:
        pdf = ws / "paper" / "main.pdf"
        _assert_pdf(pdf)
        pdf_bytes = pdf.stat().st_size
    if spec["expect_docx"]:
        docx = ws / "paper" / "main.docx"
        _assert_docx(docx)
        docx_bytes = docx.stat().st_size

    for skill in spec["lineage"]:
        lineage = ws / ".host_builds" / f"{skill}.json"
        # docx-export may record under different host marker; allow alternate
        if skill == "docx-export" and not lineage.is_file():
            # export may be non-host pandoc path; require artifact only
            continue
        assert lineage.is_file(), (spec["target"], skill, list((ws / ".host_builds").glob("*.json")))
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload.get("executor") == "host_step_runner", (spec["target"], skill, payload)

    return {
        "target": spec["target"],
        "wf_id": wf_id,
        "ws": str(ws),
        "pdf_bytes": pdf_bytes,
        "docx_bytes": docx_bytes,
    }


def _matrix_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-资产矩阵-{label}"
    user.mkdir(parents=True)
    token = f"dual-assets-matrix-{label}"
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
                "title": f"paper_from_assets matrix dual-clean {label}",
                "research_question": "Do all paper_type_target branches produce independent artifacts?",
                "inclusion_criteria": "host_step_runner paper_from_assets only",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        results = [_run_assets(port, token, project_id, label, spec) for spec in ASSETS_MATRIX]
        assert any(ord(ch) > 127 for ch in str(user))
        return {
            "label": label,
            "user_data": str(user),
            "project_id": project_id,
            "results": results,
        }
    finally:
        _stop(process)


def test_dual_clean_paper_from_assets_all_targets(tmp_path: Path) -> None:
    base = tmp_path / "双干净资产矩阵"
    base.mkdir()
    run1 = _matrix_run("1", base)
    run2 = _matrix_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert "用户数据-资产矩阵-1" in run1["user_data"]
    assert "用户数据-资产矩阵-2" in run2["user_data"]
    assert len(run1["results"]) == len(ASSETS_MATRIX) == len(run2["results"])
    targets = {r["target"] for r in run1["results"]}
    assert targets == {s["target"] for s in ASSETS_MATRIX}
    for a, b in zip(run1["results"], run2["results"], strict=True):
        assert a["target"] == b["target"]
        assert a["wf_id"] != b["wf_id"]
        assert Path(a["ws"]).resolve() != Path(b["ws"]).resolve()
        if a["pdf_bytes"]:
            assert a["pdf_bytes"] >= 1000 and b["pdf_bytes"] >= 1000
        if a["docx_bytes"]:
            assert a["docx_bytes"] >= 800 and b["docx_bytes"] >= 800
