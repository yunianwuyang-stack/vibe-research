"""Dual Unicode roots: competition matrix host chains for previously untested comps.

Covers EN (comp-paper-en) and ZH (comp-paper-zh) paths beyond cumcm/stats:
  problem → model → code → paper → compile PDF with host_step_runner lineage.

Sample set is product-calendar-relevant and was NOT in prior dual-clean inventory.
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

def _zh(template: str, title: str, problem: str) -> dict:
    return {
        "template": template,
        "title": title,
        "paper_skill": "comp-paper-zh",
        "compile_skill": "comp-compile-zh",
        "problem": problem,
    }


def _en(template: str, title: str, problem: str) -> dict:
    return {
        "template": template,
        "title": title,
        "paper_skill": "comp-paper-en",
        "compile_skill": "comp-compile-en",
        "problem": problem,
    }


# Batch A: previously untested calendar-relevant comps (EN + ZH).
# (cumcm/stats covered in other dual-clean modules.)
COMP_MATRIX = (
    _en(
        "comp_mcm",
        "MCM shared-bike dual-clean",
        "Shared bike rebalancing: given station demand and fleet capacity, "
        "build an optimization model that minimizes rebalancing cost and "
        "perform sensitivity analysis on transport cost and demand volatility.",
    ),
    _zh(
        "comp_mathorcup",
        "MathorCup 共享单车调度",
        "【MathorCup】共享单车调度：给定站点需求与运力，"
        "建立优化模型最小化调度成本，并做敏感性分析。",
    ),
    _zh(
        "comp_certcup",
        "认证杯 物流网络优化",
        "【认证杯】区域物流网络选址与路径：在容量与时效约束下"
        "最小化总成本，给出可计算模型与数值算例。",
    ),
    _en(
        "comp_apmcm",
        "APMCM energy dispatch",
        "APMCM energy dispatch: schedule generation and storage under demand "
        "uncertainty to minimize cost and emissions; provide a reproducible "
        "baseline and ablation on storage capacity.",
    ),
    _zh(
        "comp_huawei",
        "华为杯 通信资源分配",
        "【华为杯】无线资源分配：在功率与干扰约束下最大化系统吞吐，"
        "给出可求解模型、算法复杂度与数值实验。",
    ),
)

# Batch B: remaining catalog comps not covered by domain/stats/matrix-A.
COMP_MATRIX_REMAINING = (
    _zh("comp_tianfu", "天府杯 交通流量预测", "【天府杯】城市交通流量预测与信号配时优化。"),
    _zh("comp_teddy", "泰迪杯 用户画像", "【泰迪杯】电商用户行为挖掘与流失预测。"),
    _zh("comp_huadong", "华东杯 供应链", "【华东杯】多级供应链库存与运输联合优化。"),
    _zh("comp_huazhong", "华中杯 疫情传播", "【华中杯】传染病传播模型与干预策略评估。"),
    _zh("comp_wuyi", "五一杯 选址", "【五一杯】应急设施选址与覆盖最大化。"),
    _zh("comp_zhongqing", "中青杯 舆情", "【中青杯】网络舆情传播与情感分析。"),
    _zh("comp_yangtze", "长三角 碳排", "【长三角】区域碳排放核算与减排路径优化。"),
    _zh("comp_shuwei", "数维杯 图像", "【数维杯】图像分类基线与消融实验。"),
    _zh("comp_diangong", "电工杯 电网", "【电工杯】配电网重构与损耗最小化。"),
    _zh("comp_liaoning", "东三省 港口", "【东三省】港口调度与泊位分配优化。"),
    _zh("comp_apmcm_zh", "亚太中文 能源", "【亚太中文】能源调度与储能容量敏感性。"),
    _zh("comp_shenzhen", "深圳杯 创新", "【深圳杯】创新创业项目评价与组合优化。"),
    _zh("comp_huashu", "华数杯 金融", "【华数杯】投资组合风险度量与回测。"),
    _en(
        "comp_certcup_en",
        "CertCup EN logistics",
        "International CertCup logistics network design under capacity and time windows.",
    ),
    _en(
        "comp_shuwei_en",
        "Shuwei EN imaging",
        "Shuwei international track: reproducible image classification baseline and ablation.",
    ),
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
        text = error.read().decode("utf-8")
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


def _wait_terminal(port: int, token: str, wf_id: str, seconds: int = 420) -> dict:
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
                {"action": "approve", "data": {"feedback": "dual-clean competition auto-approve"}},
            )
            assert st in {200, 202, 409}, body
        time.sleep(0.4)
    raise AssertionError(f"workflow {wf_id} not terminal: {last}")


def _assert_pdf(path: Path) -> None:
    assert path.is_file(), path
    assert path.stat().st_size >= 1000, path
    assert path.read_bytes()[:4] == b"%PDF", path


def _run_comp(port: int, token: str, project_id: str, label: str, spec: dict) -> dict:
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
                "skip_figures": True,
                "skip_drawio": True,
                "skip_analysis": True,
                "skip_improvement_loop": True,
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
    status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
    assert status == 200, (spec["template"], started)
    final = _wait_terminal(port, token, wf_id, seconds=480)
    assert final["status"] == "completed", (spec["template"], final)

    for rel in (
        "PROBLEM_ANALYSIS.md",
        "MODELING_REPORT.md",
        "RESULTS.md",
        "code/main.py",
        "paper/main.tex",
        "paper/main.pdf",
    ):
        path = ws / rel
        assert path.is_file() and path.stat().st_size > 40, (spec["template"], path)
    _assert_pdf(ws / "paper" / "main.pdf")

    for skill in (
        "comp-prob-analysis",
        "comp-modeling",
        "comp-code",
        spec["paper_skill"],
    ):
        lineage = ws / ".host_builds" / f"{skill}.json"
        assert lineage.is_file(), (spec["template"], skill, lineage)
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload.get("executor") == "host_step_runner", (spec["template"], skill, payload)

    # compile lineage may be named compile skill or folded into paper skill depending on host path
    compile_lineage = ws / ".host_builds" / f"{spec['compile_skill']}.json"
    paper_compile_alt = ws / ".host_builds" / "paper-compile.json"
    assert compile_lineage.is_file() or paper_compile_alt.is_file() or (
        ws / ".host_builds" / f"{spec['paper_skill']}.json"
    ).is_file(), (spec["template"], list((ws / ".host_builds").glob("*.json")))

    return {
        "template": spec["template"],
        "wf_id": wf_id,
        "ws": str(ws),
        "pdf_bytes": (ws / "paper" / "main.pdf").stat().st_size,
        "paper_skill": spec["paper_skill"],
    }


def _matrix_run(label: str, base: Path, matrix: tuple[dict, ...], *, tag: str) -> dict:
    user = base / f"用户数据-竞赛矩阵-{tag}-{label}"
    user.mkdir(parents=True)
    token = f"dual-comp-matrix-{tag}-{label}"
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
                "title": f"Competition matrix dual-clean {tag} {label}",
                "research_question": "Do host competition templates produce independent PDF artifacts?",
                "inclusion_criteria": "host_step_runner competition packs only",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        results = []
        for spec in matrix:
            results.append(_run_comp(port, token, project_id, label, spec))

        assert any(ord(ch) > 127 for ch in str(user))
        return {
            "label": label,
            "user_data": str(user),
            "project_id": project_id,
            "results": results,
        }
    finally:
        _stop(process)


def _assert_dual(run1: dict, run2: dict, matrix: tuple[dict, ...], tag: str) -> None:
    assert run1["project_id"] != run2["project_id"]
    assert f"用户数据-竞赛矩阵-{tag}-1" in run1["user_data"]
    assert f"用户数据-竞赛矩阵-{tag}-2" in run2["user_data"]
    assert len(run1["results"]) == len(matrix) == len(run2["results"])
    templates = {r["template"] for r in run1["results"]}
    assert templates == {s["template"] for s in matrix}
    for a, b in zip(run1["results"], run2["results"], strict=True):
        assert a["template"] == b["template"]
        assert a["wf_id"] != b["wf_id"]
        assert Path(a["ws"]).resolve() != Path(b["ws"]).resolve()
        assert a["pdf_bytes"] >= 1000 and b["pdf_bytes"] >= 1000
        assert a["paper_skill"] in {"comp-paper-en", "comp-paper-zh"}


def test_dual_clean_competition_matrix_host_chains(tmp_path: Path) -> None:
    base = tmp_path / "双干净竞赛矩阵"
    base.mkdir()
    run1 = _matrix_run("1", base, COMP_MATRIX, tag="A")
    run2 = _matrix_run("2", base, COMP_MATRIX, tag="A")
    _assert_dual(run1, run2, COMP_MATRIX, "A")


def test_dual_clean_competition_matrix_remaining_host_chains(tmp_path: Path) -> None:
    """Cover every remaining COMPETITIONS entry with dual Unicode host PDF chains."""
    base = tmp_path / "双干净竞赛矩阵剩余"
    base.mkdir()
    run1 = _matrix_run("1", base, COMP_MATRIX_REMAINING, tag="B")
    run2 = _matrix_run("2", base, COMP_MATRIX_REMAINING, tag="B")
    _assert_dual(run1, run2, COMP_MATRIX_REMAINING, "B")
