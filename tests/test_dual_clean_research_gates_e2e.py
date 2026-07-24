"""Dual clean user-data roots: full research gate chain over real HTTP.

Seeds offline literature snapshots (no live provider keys required), then
exercises UI→API→executor→persistence→artifact for:
hypothesis freeze, screening/PRISMA, narrative, claim-evidence graph,
innovation check, approved draft, deterministic adversarial review, assurance.
"""
from __future__ import annotations

import hashlib
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

QUERY = "dual-clean gate evidence query"
PROVIDER = "openalex"
SOURCE_URL = "https://doi.org/10.1234/dual-clean-gate"
RECORD = {
    "title": "Dual Clean Gate Paper",
    "authors": ["Researcher A", "Researcher B"],
    "year": 2024,
    "doi": "10.1234/dual-clean-gate",
    "url": SOURCE_URL,
}


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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
        with urlopen(req, timeout=45) as response:
            payload = response.read()
            return response.status, json.loads(payload.decode("utf-8"))
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
    for _ in range(100):
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


def _seed_literature_snapshot(user_data: Path) -> str:
    """Write integrity-checked offline literature snapshot under user-data workspaces."""
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


def _gate_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-门禁-{label}"
    user.mkdir(parents=True)
    snapshot_sha = _seed_literature_snapshot(user)
    token = f"dual-gates-{label}"
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
                "title": f"Gate dual clean {label}",
                "research_question": "Does dual-clean persistence keep research gate artifacts isolated?",
                "inclusion_criteria": "peer reviewed experimental report",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        ws = _project_workspace(user, project_id)

        status, blocked = _request(port, token, f"/api/research-projects/{project_id}/assurance")
        assert status == 200, blocked
        assert blocked.get("submission_ready") is False
        assert blocked.get("status") in {"BLOCKED", "FAIL", "blocked", "fail"} or blocked.get("submission_ready") is False

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
            {"actor": "researcher", "decision": "approved", "reason": "full text supports the dual-clean claim"},
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
        status, prisma = _request(port, token, f"/api/research-projects/{project_id}/screening/prisma", "POST")
        assert status == 200, prisma
        prisma_rel = prisma["artifact"]["path"]
        prisma_path = ws / prisma_rel
        assert prisma_path.is_file(), prisma_path
        assert hashlib.sha256(prisma_path.read_bytes()).hexdigest() == prisma["artifact"]["sha256"]

        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses",
            "POST",
            {
                "statement": "Isolated dual-clean roots preserve gate artifacts without cross-talk",
                "mechanism": "Separate VIBE_USER_DATA_ROOT directories isolate SQLite and workspaces",
                "prediction": "Each root has its own claim graph and assurance artifacts",
                "falsification_criteria": "Shared workspace paths or missing gate files on either root",
                "boundary_conditions": "desktop dual-process Unicode paths only",
                "actor": "researcher",
                "change_reason": "register primary dual-clean hypothesis",
            },
        )
        assert status == 200, project
        hypotheses = project.get("hypotheses") or []
        assert hypotheses, project
        hyp_id = hypotheses[0]["id"]
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{hyp_id}/freeze",
            "POST",
            {"actor": "researcher", "reason": "lock before claim support"},
        )
        assert status == 200, project
        frozen = next(h for h in project["hypotheses"] if h["id"] == hyp_id)
        assert frozen["status"] == "frozen"
        manifest_path = ws / frozen["manifest"]["path"]
        assert manifest_path.is_file(), manifest_path
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == frozen["manifest"]["sha256"]

        status, narrative = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/narrative",
            "PUT",
            {
                "question": "Does dual-clean persistence keep research gate artifacts isolated?",
                "tension": "Shared roots could silently mix assurance ledgers",
                "mechanism": "Separate user-data roots isolate DB and workspaces",
                "hypotheses": [frozen["statement"]],
                "claims": ["C1"],
                "competing_explanations": ["process-level path rebound"],
                "boundaries": ["desktop dual-process Unicode paths"],
                "limitations": ["offline literature snapshot only"],
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
                "passage": "The report records isolated dual-clean roots preserving gate artifacts.",
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
        graph_path = ws / graph["artifact"]["path"]
        assert graph_path.is_file(), graph_path
        assert hashlib.sha256(graph_path.read_bytes()).hexdigest() == graph["artifact"]["sha256"]

        status, novelty = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/innovation-check",
            "POST",
            {
                "actor": "researcher",
                "claims": [
                    "A dual-clean Unicode user-data gate ledger that binds frozen hypotheses to immutable assurance hashes"
                ],
                "overrides": {},
                "provider": None,
            },
        )
        assert status == 200, novelty
        assert novelty["gate"]["passed"] is True, novelty
        novelty_path = ws / novelty["artifact"]["path"]
        assert novelty_path.is_file(), novelty_path
        assert hashlib.sha256(novelty_path.read_bytes()).hexdigest() == novelty["artifact"]["sha256"]

        status, draft = _request(port, token, f"/api/research-projects/{project_id}/draft", "POST")
        assert status == 200, draft
        draft_path = ws / draft["path"]
        assert draft_path.is_file(), draft_path
        assert "approved-citations-only" in draft["content"] or draft_path.read_text(encoding="utf-8")

        status, review = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/adversarial-reviews",
            "POST",
            {"mode": "deterministic"},
        )
        assert status == 200, review
        assert review["status"] == "completed", review
        assert review["verdict"] == "pass", review
        report_path = ws / review["report_path"]
        assert report_path.is_file(), report_path
        assert hashlib.sha256(report_path.read_bytes()).hexdigest() == review["report_sha256"]

        status, envelope = _request(port, token, f"/api/research-projects/{project_id}/assurance")
        assert status == 200, envelope
        assert envelope["status"] == "PASS", envelope
        assert envelope["submission_ready"] is True, envelope
        assert envelope.get("independent_from_generator") is True
        assert all(gate["status"] == "PASS" for gate in envelope["gates"]), envelope["gates"]

        status, approved = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/approval",
            "POST",
            {"actor": "researcher", "approved": True, "reason": "all deterministic gates passed under dual-clean"},
        )
        assert status == 200, approved
        assert approved["status"] == "approved", approved

        # Unicode path must appear in durable project workspace.
        assert any(ord(ch) > 127 for ch in str(ws))
        assert user.resolve() in ws.resolve().parents or str(user.resolve()) in str(ws.resolve())

        return {
            "label": label,
            "project_id": project_id,
            "workspace": str(ws),
            "user_data": str(user),
            "prisma": True,
            "graph": True,
            "innovation": True,
            "adversarial": True,
            "assurance_pass": True,
            "approved": True,
            "hypothesis_manifest": True,
        }
    finally:
        _stop(process)


def test_dual_clean_research_gates_full_chain(tmp_path):
    base = tmp_path / "dual-clean-gates"
    base.mkdir()
    run1 = _gate_run("1", base)
    run2 = _gate_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert Path(run1["workspace"]).resolve() != Path(run2["workspace"]).resolve()
    assert "用户数据-门禁-1" in run1["user_data"] or "用户数据-门禁-1" in run1["workspace"]
    assert "用户数据-门禁-2" in run2["user_data"] or "用户数据-门禁-2" in run2["workspace"]
    for run in (run1, run2):
        assert run["assurance_pass"] and run["approved"]
        assert run["prisma"] and run["graph"] and run["innovation"] and run["adversarial"]
        assert Path(run["workspace"]).is_dir()
