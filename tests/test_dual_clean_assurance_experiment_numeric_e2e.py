"""Dual Unicode roots: full assurance PASS with experiment lineage + numeric draft.

Critical-path chain (no live LLM keys):
  offline literature → evidence approve → frozen hypothesis → narrative
  → multi-seed confirmatory experiment (stats PASS + lineage)
  → claim-experiment approve → innovation check → draft binds registry numbers
  → deterministic adversarial review → ASSURANCE envelope submission_ready
  → human approval

Proves report gates on one dual-clean path: claim-evidence, experiment
reproducibility, statistics/numeric, innovation, adversarial, scientific draft.
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

QUERY = "dual-clean assurance experiment numeric query"
PROVIDER = "openalex"
SOURCE_URL = "https://doi.org/10.1234/dual-clean-assurance-exp"
RECORD = {
    "title": "Dual Clean Assurance Experiment Paper",
    "authors": ["Researcher A", "Researcher B"],
    "year": 2024,
    "doi": "10.1234/dual-clean-assurance-exp",
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
        with urlopen(req, timeout=90) as response:
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


def _assurance_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-全门禁实验数字-{label}"
    user.mkdir(parents=True)
    snapshot_sha = _seed_literature_snapshot(user)
    token = f"dual-assure-exp-{label}"
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
                "title": f"Assurance experiment numeric dual-clean {label}",
                "research_question": "Does treatment improve score with dual-clean assurance?",
                "inclusion_criteria": "peer-reviewed experimental report",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        ws = user / "workspaces" / project_id

        # Evidence card path.
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
        card_id = project["evidence_cards"][0]["id"]
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
                "reason": "full text supports dual-clean assurance claim",
            },
        )
        assert status == 200, project

        # Frozen hypothesis.
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses",
            "POST",
            {
                "statement": "Treatment mean exceeds control mean under multi-seed dual-clean assurance",
                "mechanism": "Bounded two-condition ProcessSupervisor calculation",
                "prediction": "Positive difference with multi-seed statistics gate pass",
                "falsification_criteria": "Non-positive difference or statistics gate fail",
                "boundary_conditions": "numeric laboratory observations only",
                "actor": "researcher",
                "change_reason": "register dual-clean assurance hypothesis",
            },
        )
        assert status == 200, project
        hyp = project["hypotheses"][0]
        hyp_id = hyp["id"]
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{hyp_id}/freeze",
            "POST",
            {"actor": "researcher", "reason": "lock before confirmatory experiment"},
        )
        assert status == 200, project
        frozen = next(h for h in project["hypotheses"] if h["id"] == hyp_id)
        assert frozen["status"] == "frozen"
        version_id = (
            frozen.get("version_id")
            or (frozen.get("manifest") or {}).get("version_id")
            or frozen.get("id")
        )

        # Narrative map.
        status, narrative = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/narrative",
            "PUT",
            {
                "question": "Does treatment improve score with dual-clean assurance?",
                "tension": "Shared roots could mix experiment and draft ledgers",
                "mechanism": "Isolated user-data roots + confirmatory experiment registry",
                "hypotheses": [frozen["statement"]],
                "claims": ["C1"],
                "competing_explanations": ["path rebound", "silent mock numbers"],
                "boundaries": ["numeric dual-clean desktop runs"],
                "limitations": ["synthetic two-condition calculator"],
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

        # Only multi-seed confirmatory PASS run (failed stats runs would block assurance).
        status, run = _request(
            port,
            token,
            f"/api/experiments/projects/{project_id}",
            "POST",
            {
                "control": [1, 2, 3],
                "treatment": [2, 4, 6],
                "seeds": 3,
                "metric": "score",
                "analysis_mode": "confirmatory",
                "hypothesis_version_id": version_id,
            },
        )
        assert status == 200, run
        assert run["status"] == "completed", run
        assert run["statistics"]["passed"] is True, run["statistics"]
        assert run.get("result_sha256") and len(run["result_sha256"]) == 64
        assert run.get("manifest_sha256") and len(run["manifest_sha256"]) == 64
        assert Path(run["workspace_path"], "result.json").is_file()
        result = run.get("result") or json.loads(
            Path(run["workspace_path"], "result.json").read_text(encoding="utf-8")
        )
        treatment_mean = float(result.get("treatment_mean", 0))
        difference = float(result.get("difference", 0))

        # Claim-experiment support → graph gate.
        status, graph = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/claim-experiment-links",
            "POST",
            {
                "claim_id": "C1",
                "experiment_run_id": run["id"],
                "relation": "supports",
                "result_locator": "difference",
                "interpretation": "Positive treatment-control difference under multi-seed confirmatory mode",
                "evidence_card_ids": [card_id],
            },
        )
        assert status == 200, graph
        link_id = graph["experiment_links"][0]["id"]
        status, graph = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/claim-experiment-links/{link_id}/review",
            "POST",
            {
                "actor": "researcher",
                "decision": "approved",
                "reason": "locator difference matches confirmatory run with intact lineage",
            },
        )
        assert status == 200, graph
        assert graph["gate"]["passed"] is True, graph["gate"]
        graph_path = ws / graph["artifact"]["path"]
        assert graph_path.is_file(), graph_path
        assert hashlib.sha256(graph_path.read_bytes()).hexdigest() == graph["artifact"]["sha256"]

        # Innovation / novelty check.
        status, novelty = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/innovation-check",
            "POST",
            {
                "actor": "researcher",
                "claims": [
                    "A dual-clean Unicode assurance ledger that binds confirmatory multi-seed "
                    "experiment lineage hashes to registry-gated manuscript numbers"
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

        # Draft with eligible numeric registry (not empty placeholder).
        status, draft = _request(port, token, f"/api/research-projects/{project_id}/draft", "POST")
        assert status == 200, draft
        content = draft["content"]
        draft_path = ws / draft["path"]
        assert draft_path.is_file(), draft_path
        assert "尚无通过统计门禁的实验数字" not in content, content
        assert "尚无经验证的数字" not in content, content
        assert run["result_sha256"] in content or run["id"] in content, content
        assert any(
            key in content for key in ("treatment_mean", "control_mean", "difference", "score")
        ), content
        # Honest save preserves registry-bound numbers.
        ok_content = content.rstrip() + "\n\nResearcher note without fabricated experimental numbers. [claim:C1]\n"
        status, saved = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/draft",
            "PUT",
            {"content": ok_content},
        )
        assert status == 200, saved
        assert saved.get("ok") is True, saved

        # Deterministic adversarial review must pass after all gates.
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

        # Assurance envelope: all gates PASS, submission_ready.
        status, envelope = _request(port, token, f"/api/research-projects/{project_id}/assurance")
        assert status == 200, envelope
        assert envelope["status"] == "PASS", envelope
        assert envelope["submission_ready"] is True, envelope
        assert envelope.get("independent_from_generator") is True
        gate_map = {g["id"]: g["status"] for g in envelope["gates"]}
        for required in (
            "literature_evidence",
            "study_design",
            "innovation",
            "experiment_integrity",
            "statistical",
            "result_to_claim",
            "numerical_paper",
            "reporting",
            "final_submission",
        ):
            assert required in gate_map, gate_map
            assert gate_map[required] == "PASS", (required, gate_map, envelope.get("findings"))

        status, approved = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/approval",
            "POST",
            {
                "actor": "researcher",
                "approved": True,
                "reason": "all deterministic gates passed with confirmatory experiment under dual-clean",
            },
        )
        assert status == 200, approved
        assert approved["status"] == "approved", approved

        assert any(ord(ch) > 127 for ch in str(user))
        assert user.resolve() in ws.resolve().parents or str(user.resolve()) in str(ws.resolve())

        return {
            "label": label,
            "project_id": project_id,
            "user_data": str(user),
            "workspace": str(ws),
            "run_id": run["id"],
            "result_sha256": run["result_sha256"],
            "manifest_sha256": run["manifest_sha256"],
            "treatment_mean": treatment_mean,
            "difference": difference,
            "draft_sha256": saved.get("sha256") or draft.get("sha256"),
            "assurance_pass": True,
            "submission_ready": True,
            "approved": True,
            "gates": gate_map,
        }
    finally:
        _stop(process)


def test_dual_clean_assurance_with_experiment_and_numeric_draft(tmp_path: Path) -> None:
    base = tmp_path / "双干净全门禁实验数字"
    base.mkdir()
    run1 = _assurance_run("1", base)
    run2 = _assurance_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert run1["run_id"] != run2["run_id"]
    assert Path(run1["workspace"]).resolve() != Path(run2["workspace"]).resolve()
    assert "用户数据-全门禁实验数字-1" in run1["user_data"]
    assert "用户数据-全门禁实验数字-2" in run2["user_data"]
    for run in (run1, run2):
        assert run["assurance_pass"] and run["submission_ready"] and run["approved"]
        assert len(run["result_sha256"]) == 64 and len(run["manifest_sha256"]) == 64
        assert run["draft_sha256"]
        assert all(status == "PASS" for status in run["gates"].values()), run["gates"]
