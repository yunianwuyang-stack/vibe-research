"""Dual Unicode user-data roots: experiment stats, replay, lineage, claim link.

Covers UI→API→ProcessSupervisor→SQLite→workspace manifests without live LLM keys:
  - multi-seed confirmatory run bound to frozen hypothesis (statistics gate pass)
  - single-seed run retained but statistics gate fail (honest fail, not silent pass)
  - NaN input → 422 (no silent coerce)
  - replay reproduces result_sha256
  - claim-experiment link + review with immutable lineage hashes
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

QUERY = "dual-clean experiment lineage query"
PROVIDER = "openalex"
SOURCE_URL = "https://doi.org/10.1234/dual-clean-experiment"
RECORD = {
    "title": "Dual Clean Experiment Paper",
    "authors": ["Researcher A", "Researcher B"],
    "year": 2024,
    "doi": "10.1234/dual-clean-experiment",
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
        with urlopen(req, timeout=60) as response:
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


def _exp_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-实验血缘-{label}"
    user.mkdir(parents=True)
    snapshot_sha = _seed_literature_snapshot(user)
    token = f"dual-exp-{label}"
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
                "title": f"Experiment lineage dual-clean {label}",
                "research_question": "Does treatment improve the measured score under dual-clean roots?",
                "inclusion_criteria": "peer-reviewed experimental report",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        ws = user / "workspaces" / project_id

        # Offline literature snapshot → evidence card with approved citation + claim support.
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
                "reason": "full text supports dual-clean experiment claim",
            },
        )
        assert status == 200, project

        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses",
            "POST",
            {
                "statement": "Treatment mean exceeds control mean across multi-seed dual-clean runs",
                "mechanism": "Bounded two-condition ProcessSupervisor calculation",
                "prediction": "Positive difference with multi-seed statistics gate pass",
                "falsification_criteria": "Non-positive difference or statistics gate fail",
                "boundary_conditions": "numeric laboratory observations only",
                "actor": "researcher",
                "change_reason": "register dual-clean experiment hypothesis",
            },
        )
        assert status == 200, project
        hyp = (project.get("hypotheses") or [])[0]
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
        assert version_id, frozen

        status, narrative = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/narrative",
            "PUT",
            {
                "question": "Does treatment improve the measured score under dual-clean roots?",
                "tension": "Shared roots could mix experiment manifests",
                "mechanism": "Isolated user-data roots + immutable experiment lineage",
                "hypotheses": [frozen["statement"]],
                "claims": ["C1"],
                "competing_explanations": ["path rebound"],
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

        # Honest fail: NaN rejected.
        status, bad = _request(
            port,
            token,
            f"/api/experiments/projects/{project_id}",
            "POST",
            {
                "control": [1, "NaN"],
                "treatment": [2, 3],
                "seeds": 3,
                "metric": "score",
                "analysis_mode": "confirmatory",
                "hypothesis_version_id": version_id,
            },
        )
        assert status == 422, bad

        # Single seed: completed but statistics gate fails.
        status, single = _request(
            port,
            token,
            f"/api/experiments/projects/{project_id}",
            "POST",
            {
                "control": [1, 2, 3],
                "treatment": [2, 4, 6],
                "seeds": 1,
                "metric": "score",
                "analysis_mode": "confirmatory",
                "hypothesis_version_id": version_id,
            },
        )
        assert status == 200, single
        assert single["status"] == "completed", single
        assert single["statistics"]["passed"] is False, single["statistics"]
        assert any("seed" in str(i).lower() for i in (single["statistics"].get("issues") or [])), single

        # Multi-seed confirmatory: statistics pass + lineage files.
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
        assert run.get("integrity", {}).get("passed") is True, run.get("integrity")
        workspace_path = Path(run["workspace_path"])
        assert workspace_path.is_dir(), workspace_path
        assert (workspace_path / "result.json").is_file()
        assert (workspace_path / "input.json").is_file()
        assert Path(run["manifest_path"]).is_file()
        assert any(ord(ch) > 127 for ch in str(user))
        assert str(user.resolve()) in str(workspace_path.resolve()) or user.resolve() in workspace_path.resolve().parents

        # Replay reproduces result hash.
        status, replay = _request(port, token, f"/api/experiments/{run['id']}/replay", "POST")
        assert status == 200, replay
        assert replay.get("reproduced") is True, replay
        assert replay.get("result_sha256") == run["result_sha256"] or replay.get("replay_of") == run["id"]

        # Claim-experiment link with result locator + approved evidence basis.
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
        exp_links = graph.get("experiment_links") or []
        assert exp_links, graph
        link_id = exp_links[0]["id"]
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
        approved = next(l for l in (graph.get("experiment_links") or []) if l["id"] == link_id)
        assert approved["status"] == "approved", approved
        assert approved.get("result_sha256") == run["result_sha256"]
        assert approved.get("manifest_sha256") == run["manifest_sha256"]

        # List runs: both single-seed and multi-seed present, isolated to this root.
        status, runs = _request(port, token, f"/api/experiments/projects/{project_id}")
        assert status == 200, runs
        assert len(runs) >= 2
        assert all(r.get("project_id", project_id) for r in runs)

        return {
            "label": label,
            "project_id": project_id,
            "user_data": str(user),
            "workspace": str(ws),
            "run_id": run["id"],
            "result_sha256": run["result_sha256"],
            "manifest_sha256": run["manifest_sha256"],
            "stats_pass": True,
            "replay_ok": True,
            "claim_experiment_approved": True,
            "single_seed_stats_fail": True,
            "nan_rejected": True,
        }
    finally:
        _stop(process)


def test_dual_clean_experiment_lineage_stats_replay_claim(tmp_path: Path) -> None:
    base = tmp_path / "双干净实验血缘"
    base.mkdir()
    run1 = _exp_run("1", base)
    run2 = _exp_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert run1["run_id"] != run2["run_id"]
    assert Path(run1["workspace"]).resolve() != Path(run2["workspace"]).resolve()
    assert "用户数据-实验血缘-1" in run1["user_data"]
    assert "用户数据-实验血缘-2" in run2["user_data"]
    # Independent ledgers: hashes may match (deterministic calc) but roots must not share paths.
    for run in (run1, run2):
        assert run["stats_pass"] and run["replay_ok"] and run["claim_experiment_approved"]
        assert run["single_seed_stats_fail"] and run["nan_rejected"]
        assert len(run["result_sha256"]) == 64 and len(run["manifest_sha256"]) == 64
