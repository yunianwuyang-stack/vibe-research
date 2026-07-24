"""Dual Unicode user-data roots: full_pipeline host chain + terminal assurance.

Proves UI→API→host executor→persistence→artifact for the doctoral full pipeline:
research-lit → idea → novelty → review → refine → experiment-bridge → paper-plan
→ (skip drawio) → paper-write → paper-compile → ASSURANCE_ENVELOPE.

Requires bound project_id and seeded deterministic research gates so the
terminal assurance gate can honestly pass offline (no live provider keys).
"""
from __future__ import annotations

import hashlib
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

QUERY = "dual-clean full pipeline evidence query"
PROVIDER = "openalex"
SOURCE_URL = "https://doi.org/10.1234/dual-clean-full-pipeline"
RECORD = {
    "title": "Dual Clean Full Pipeline Paper",
    "authors": ["Researcher A", "Researcher B"],
    "year": 2024,
    "doi": "10.1234/dual-clean-full-pipeline",
    "url": SOURCE_URL,
}


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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
    for _ in range(140):
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
        time.sleep(0.6)
    raise AssertionError(f"workflow {wf_id} did not reach terminal state: {detail}")


def _approve_if_waiting(port: int, token: str, wf_id: str, detail: dict) -> dict:
    hops = 0
    while detail.get("status") == "waiting_checkpoint" and hops < 16:
        status, cp = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/checkpoint",
            "POST",
            {"action": "approve", "data": {"feedback": "dual-clean full_pipeline auto-approve"}},
        )
        assert status == 200, cp
        detail = _wait_terminal(port, token, wf_id, seconds=480)
        hops += 1
    return detail


def _assert_pdf(path: Path) -> None:
    assert path.is_file() and path.stat().st_size >= 1000, path
    assert path.read_bytes()[:4] == b"%PDF"


def _seed_literature_snapshot(user_data: Path) -> str:
    cache = user_data / "workspaces" / "literature-cache"
    cache.mkdir(parents=True, exist_ok=True)
    content_sha = hashlib.sha256(_canonical([RECORD])).hexdigest()
    envelope = {
        "provider": PROVIDER,
        "query": QUERY,
        "retrieved_at": "2026-07-16T00:00:00+00:00",
        "records": [RECORD],
        "content_sha256": content_sha,
    }
    path = cache / f"{PROVIDER}-{hashlib.sha256(QUERY.encode()).hexdigest()}.json"
    raw = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _project_workspace(user_data: Path, project_id: str) -> Path:
    return user_data / "workspaces" / project_id


def _seed_submission_ready_gates(
    port: int,
    token: str,
    project_id: str,
    user_data: Path,
    *,
    label: str,
) -> dict:
    """Populate deterministic gates so full_pipeline terminal assurance can PASS."""
    snapshot_sha = _seed_literature_snapshot(user_data)
    ws = _project_workspace(user_data, project_id)

    status, project = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/evidence-cards",
        "POST",
        {
            "provider": PROVIDER,
            "query": QUERY,
            "source_url": SOURCE_URL,
            "snapshot_sha256": snapshot_sha,
        },
    )
    assert status == 200, project
    cards = project.get("evidence_cards") or []
    assert cards, project
    card_id = cards[0]["id"]

    status, project = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/evidence-cards/{card_id}/review",
        "POST",
        {"actor": "researcher", "decision": "approved", "reason": "metadata verified offline"},
    )
    assert status == 200, project
    status, project = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/evidence-cards/{card_id}/claim-support",
        "POST",
        {
            "actor": "researcher",
            "decision": "approved",
            "reason": "full text supports the dual-clean full pipeline claim",
        },
    )
    assert status == 200, project

    status, screening = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/screening/protocol",
        "PUT",
        {
            "title": "Peer-reviewed screening",
            "inclusion_criteria": "peer-reviewed experimental report",
            "exclusion_criteria": "preprint without peer review",
            "source_strategy": "offline provider snapshot + human decision",
            "actor": "researcher",
        },
    )
    assert status == 200, screening
    status, screening = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/screening/activate",
        "POST",
        {"actor": "researcher"},
    )
    assert status == 200, screening
    status, screening = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/screening/evidence-cards/{card_id}",
        "POST",
        {"decision": "included", "reason": "matches inclusion criteria", "actor": "researcher"},
    )
    assert status == 200, screening
    status, prisma = _request(
        port, token, f"/api/research-projects/{project_id}/screening/prisma", "POST"
    )
    assert status == 200, prisma

    status, project = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/hypotheses",
        "POST",
        {
            "statement": f"Full pipeline host chain under dual-clean root {label} preserves lineage",
            "mechanism": "Host step runner + bound project assurance envelope",
            "prediction": "ASSURANCE_ENVELOPE submission_ready after host write/compile",
            "falsification_criteria": "Missing PDF, host lineage, or failed assurance without artifact",
            "boundary_conditions": "offline host path with skip_drawio and skip_improvement_loop",
            "actor": "researcher",
            "change_reason": "register full_pipeline dual-clean hypothesis",
        },
    )
    assert status == 200, project
    hyp_id = project["hypotheses"][0]["id"]
    status, project = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/hypotheses/{hyp_id}/freeze",
        "POST",
        {"actor": "researcher", "reason": "lock before full_pipeline"},
    )
    assert status == 200, project
    frozen = next(h for h in project["hypotheses"] if h["id"] == hyp_id)

    status, narrative = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/narrative",
        "PUT",
        {
            "question": "Does full_pipeline host glue complete under dual-clean Unicode roots?",
            "tension": "Long multi-skill chains often silently degrade or skip assurance",
            "mechanism": "Host domain builders + terminal assurance.read on project_id",
            "hypotheses": [frozen["statement"]],
            "claims": ["C1"],
            "competing_explanations": ["Claude-only path without host fallback"],
            "boundaries": ["skip_drawio", "skip_improvement_loop", "offline literature snapshot"],
            "limitations": ["no live provider keys in this harness"],
        },
    )
    assert status == 200, narrative
    status, narrative = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/narrative/approve",
        "POST",
        {"actor": "researcher"},
    )
    assert status == 200, narrative

    status, graph = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/claim-evidence-links",
        "POST",
        {
            "claim_id": "C1",
            "evidence_card_id": card_id,
            "relation": "supports",
            "passage": "The dual-clean full pipeline retains host lineage and assurance artifacts.",
            "locator": "p.3",
        },
    )
    assert status == 200, graph
    link_id = graph["links"][0]["id"]
    status, graph = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/claim-evidence-links/{link_id}/review",
        "POST",
        {"actor": "researcher", "decision": "approved", "reason": "passage supports C1"},
    )
    assert status == 200, graph
    assert graph["gate"]["passed"] is True

    status, novelty = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/innovation-check",
        "POST",
        {
            "actor": "researcher",
            "claims": [
                "A dual-clean full_pipeline host executor with terminal independent assurance binding"
            ],
            "overrides": {},
            "provider": None,
        },
    )
    assert status == 200, novelty
    assert novelty["gate"]["passed"] is True, novelty

    status, draft = _request(port, token, f"/api/research-projects/{project_id}/draft", "POST")
    assert status == 200, draft

    status, review = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/adversarial-reviews",
        "POST",
        {"mode": "deterministic"},
    )
    assert status == 200, review
    assert review["status"] == "completed" and review["verdict"] == "pass", review

    status, envelope = _request(port, token, f"/api/research-projects/{project_id}/assurance")
    assert status == 200, envelope
    assert envelope.get("submission_ready") is True, envelope
    assert envelope.get("status") == "PASS", envelope

    return {"workspace": str(ws), "card_id": card_id, "hyp_id": hyp_id}


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-全流程-{label}"
    user.mkdir(parents=True)
    token = f"dual-fullpipe-{label}"
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
                "title": f"Full pipeline dual-clean {label}",
                "research_question": "Does full_pipeline host glue complete under dual-clean roots?",
                "inclusion_criteria": "host executor artifacts with assurance lineage",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        _seed_submission_ready_gates(port, token, project_id, user, label=label)

        # Bound project: full host chain must complete with submission_ready envelope.
        # (Missing-project BLOCKED path is covered by test_full_pipeline_assurance_artifact.)
        status, wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "full_pipeline",
                "title": f"Evidence-native Full Pipeline {label}",
                "params": {
                    "topic": f"evidence-native research agent full pipeline dual-clean {label}",
                    "language": "en",
                    "paper_branch": "general",
                    "skip_drawio": True,
                    "skip_improvement_loop": True,
                    "seed": 7,
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

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _approve_if_waiting(
            port, token, wf_id, _wait_terminal(port, token, wf_id, seconds=600)
        )
        assert final["status"] == "completed", final

        for rel in (
            "literature_review.md",
            "references.bib",
            "IDEA_REPORT.md",
            "novelty_check_report.md",
            "review_report.md",
            "refine-logs/FINAL_PROPOSAL.md",
            "refine-logs/EXPERIMENT_PLAN.md",
            "experiment_results.md",
            "figures/experiment_data.json",
            "figures/latex_includes.tex",
            "figures/fig_metrics.pdf",
            "PAPER_PLAN.md",
            "paper/main.tex",
            "paper/references.bib",
            "paper/main.pdf",
            "ASSURANCE_ENVELOPE.json",
        ):
            path = ws / rel
            assert path.is_file() and path.stat().st_size > 40, path

        _assert_pdf(ws / "paper" / "main.pdf")
        env = json.loads((ws / "ASSURANCE_ENVELOPE.json").read_text(encoding="utf-8"))
        assert env.get("submission_ready") is True, env
        assert env.get("status") == "PASS", env
        assert env.get("format_version") == "assurance-envelope/v1"
        assert env.get("independent_from_generator") is True

        host_skills = (
            "research-lit",
            "idea-creator",
            "novelty-check",
            "research-review",
            "research-refine-pipeline",
            "experiment-bridge",
            "paper-plan",
            "paper-write",
            "paper-compile",
        )
        for skill in host_skills:
            lineage = ws / ".host_builds" / f"{skill}.json"
            assert lineage.is_file(), skill
            payload = json.loads(lineage.read_text(encoding="utf-8"))
            assert payload.get("executor") == "host_step_runner", skill

        # Drawio/html figure step must be skipped, not silently mock-rendered.
        steps = final.get("steps") or detail.get("steps") or []
        if not steps:
            status, refreshed = _request(port, token, f"/api/workflows/{wf_id}")
            assert status == 200, refreshed
            steps = refreshed.get("steps") or []
        drawio_like = [
            s for s in steps
            if str(s.get("skill_name") or "") in {"paper-figure-drawio", "paper-figure-html"}
        ]
        if drawio_like:
            assert all(str(s.get("status")) == "skipped" for s in drawio_like), drawio_like

        exp_data = json.loads((ws / "figures" / "experiment_data.json").read_text(encoding="utf-8"))
        assert exp_data.get("main_results", {}).get("method_beats_baseline") is True

        tex = (ws / "paper" / "main.tex").read_text(encoding="utf-8")
        assert "experiment" in tex.lower() or "Experiment" in tex
        assert (ws / "paper" / "main.tex").stat().st_size >= 1500

        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/recover",
            "POST",
            {"reason": "dual-clean full_pipeline recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        status, export_blob = _request(
            port, token, f"/api/workflows/{wf_id}/export", raw=True, timeout=120
        )
        assert status == 200, export_blob[:200]
        assert export_blob[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_blob)) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
            assert any(n.endswith("ASSURANCE_ENVELOPE.json") for n in names), names[:60]
            assert any("paper/main.pdf" in n or n.endswith("main.pdf") for n in names), names[:60]

        return {
            "label": label,
            "project_id": project_id,
            "wf_id": wf_id,
            "ws": str(ws),
            "user_data": str(user),
            "pdf_bytes": (ws / "paper" / "main.pdf").stat().st_size,
            "tex_bytes": (ws / "paper" / "main.tex").stat().st_size,
            "assurance_pass": True,
            "export_ok": True,
            "recovery_status": recover_status,
        }
    finally:
        _stop(process)


def test_dual_clean_full_pipeline_host_chain(tmp_path: Path) -> None:
    base = tmp_path / "双干净全流程"
    base.mkdir()
    run1 = _clean_run("A", base)
    run2 = _clean_run("B", base)

    assert run1["project_id"] != run2["project_id"]
    assert run1["wf_id"] != run2["wf_id"]
    assert Path(run1["ws"]).resolve() != Path(run2["ws"]).resolve()
    assert Path(run1["user_data"]).resolve() != Path(run2["user_data"]).resolve()
    assert "用户数据-全流程-A" in run1["user_data"]
    assert "用户数据-全流程-B" in run2["user_data"]

    for run in (run1, run2):
        assert run["assurance_pass"]
        assert run["pdf_bytes"] >= 1000
        assert run["tex_bytes"] >= 1500
        assert run["export_ok"]
        assert Path(run["ws"], "ASSURANCE_ENVELOPE.json").is_file()
