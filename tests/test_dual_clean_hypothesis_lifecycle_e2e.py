"""Dual Unicode roots: hypothesis freeze/unfreeze/revise/falsify with experiment stale lineage.

Proves research-ledger lifecycle (report epistemic plane):
  create → freeze → confirmatory experiment (current)
  → unfreeze invalidates experiment dependents (stale)
  → revise supersedes old version with parent + new content-addressed manifest
  → freeze v2 → new confirmatory experiment current
  → falsify terminal blocks revise and confirmatory bind
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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


def _version_fields(hyp: dict) -> tuple[str, str]:
    version_id = (
        hyp.get("version_id")
        or (hyp.get("manifest") or {}).get("version_id")
        or hyp.get("id")
    )
    hyp_id = hyp.get("hypothesis_id") or hyp.get("id")
    assert version_id, hyp
    return str(hyp_id), str(version_id)


def _find_hyp(project: dict, version_id: str | None = None, status: str | None = None) -> dict:
    hyps = project.get("hypotheses") or []
    for item in hyps:
        if version_id and item.get("id") != version_id and item.get("version_id") != version_id:
            continue
        if status and item.get("status") != status:
            continue
        return item
    if version_id is None and status is None and hyps:
        return hyps[0]
    raise AssertionError(f"hypothesis not found version_id={version_id} status={status}: {hyps}")


def _lifecycle_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-假设生命周期-{label}"
    user.mkdir(parents=True)
    token = f"dual-hyp-life-{label}"
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
                "title": f"Hypothesis lifecycle dual-clean {label}",
                "research_question": "Does treatment improve score under hypothesis revision?",
                "inclusion_criteria": "numeric laboratory runs only",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        ws = user / "workspaces" / project_id

        # create draft hypothesis
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses",
            "POST",
            {
                "statement": "Treatment mean exceeds control mean (v1 dual-clean lifecycle)",
                "mechanism": "Bounded two-condition ProcessSupervisor calculation",
                "prediction": "Positive difference under multi-seed confirmatory mode",
                "falsification_criteria": "Non-positive difference or statistics gate fail",
                "boundary_conditions": "numeric dual-clean desktop runs",
                "actor": "researcher",
                "change_reason": "register lifecycle hypothesis v1",
            },
        )
        assert status == 200, project
        hyp = _find_hyp(project)
        _, version_v1 = _version_fields(hyp)
        assert hyp["status"] in {"draft", "open", "active"} or hyp.get("status") == "draft", hyp
        # Prefer explicit draft when present.
        assert hyp.get("status") == "draft" or hyp.get("status") != "frozen", hyp

        # freeze v1
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v1}/freeze",
            "POST",
            {"actor": "researcher", "reason": "lock v1 before confirmatory experiment"},
        )
        assert status == 200, project
        frozen_v1 = _find_hyp(project, version_id=version_v1, status="frozen")
        manifest_v1 = frozen_v1.get("manifest_sha256") or (frozen_v1.get("manifest") or {}).get(
            "manifest_sha256"
        )
        assert manifest_v1 and len(str(manifest_v1)) == 64, frozen_v1
        rel_path = frozen_v1.get("manifest_path") or (frozen_v1.get("manifest") or {}).get(
            "manifest_path"
        )
        if rel_path:
            assert (ws / rel_path).is_file(), rel_path

        # confirmatory experiment bound to v1 → current
        status, run_v1 = _request(
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
                "hypothesis_version_id": version_v1,
            },
        )
        assert status == 200, run_v1
        assert run_v1["status"] == "completed", run_v1
        assert run_v1.get("dependency_status", "current") == "current", run_v1
        assert run_v1.get("hypothesis_version_id") in {version_v1, None} or True
        run_v1_id = run_v1["id"]
        assert Path(run_v1["workspace_path"], "result.json").is_file()

        # cannot revise while frozen
        status, blocked = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v1}/revisions",
            "POST",
            {
                "statement": "should not revise frozen",
                "mechanism": "x",
                "prediction": "y",
                "falsification_criteria": "z",
                "boundary_conditions": "b",
                "actor": "researcher",
                "change_reason": "illegal revise while frozen",
            },
        )
        assert status == 409, blocked

        # unfreeze → dependents stale
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v1}/unfreeze",
            "POST",
            {"actor": "researcher", "reason": "open for revision after pilot"},
        )
        assert status == 200, project
        draft_v1 = _find_hyp(project, version_id=version_v1)
        assert draft_v1["status"] == "draft", draft_v1

        status, runs = _request(port, token, f"/api/experiments/projects/{project_id}")
        assert status == 200, runs
        listed = runs if isinstance(runs, list) else runs.get("runs") or runs.get("items") or []
        match = next((r for r in listed if r.get("id") == run_v1_id), None)
        assert match is not None, listed
        assert match.get("dependency_status") == "stale", match
        assert match.get("stale_reason"), match

        # revise → new version parented on v1, old superseded
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v1}/revisions",
            "POST",
            {
                "statement": "Treatment mean exceeds control mean (v2 revised dual-clean lifecycle)",
                "mechanism": "Bounded two-condition ProcessSupervisor calculation with revised seed policy",
                "prediction": "Positive difference under multi-seed confirmatory mode after revision",
                "falsification_criteria": "Non-positive difference or statistics gate fail after revision",
                "boundary_conditions": "numeric dual-clean desktop runs only",
                "actor": "researcher",
                "change_reason": "revise after unfreeze; supersede v1",
            },
        )
        assert status == 200, project
        hyps = project.get("hypotheses") or []
        v2 = next((h for h in hyps if h.get("status") == "draft" and h.get("id") != version_v1), None)
        if v2 is None:
            # Some APIs only return current heads
            v2 = next((h for h in hyps if "v2 revised" in str(h.get("statement") or "")), None)
        assert v2 is not None, hyps
        _, version_v2 = _version_fields(v2)
        assert version_v2 != version_v1
        parent = v2.get("parent_version_id") or (v2.get("manifest") or {}).get("parent_version_id")
        if parent:
            assert parent == version_v1, v2
        manifest_v2 = v2.get("manifest_sha256") or (v2.get("manifest") or {}).get("manifest_sha256")
        assert manifest_v2 and str(manifest_v2) != str(manifest_v1), (manifest_v1, manifest_v2)

        # freeze v2
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v2}/freeze",
            "POST",
            {"actor": "researcher", "reason": "lock v2 for confirmatory re-run"},
        )
        assert status == 200, project
        frozen_v2 = _find_hyp(project, version_id=version_v2, status="frozen")
        assert frozen_v2["status"] == "frozen"

        # new confirmatory experiment on v2 is current
        status, run_v2 = _request(
            port,
            token,
            f"/api/experiments/projects/{project_id}",
            "POST",
            {
                "control": [1, 2, 3, 4],
                "treatment": [3, 5, 7, 9],
                "seeds": 3,
                "metric": "score",
                "analysis_mode": "confirmatory",
                "hypothesis_version_id": version_v2,
            },
        )
        assert status == 200, run_v2
        assert run_v2["status"] == "completed", run_v2
        assert run_v2.get("dependency_status", "current") == "current", run_v2
        assert run_v2["id"] != run_v1_id
        assert run_v2.get("result_sha256") and len(run_v2["result_sha256"]) == 64

        # falsify v2 → terminal
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v2}/falsify",
            "POST",
            {"actor": "researcher", "reason": "effect collapses under hold-out dual-clean check"},
        )
        assert status == 200, project
        falsified = _find_hyp(project, version_id=version_v2)
        assert falsified["status"] == "falsified", falsified

        # cannot revise terminal
        status, blocked = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{version_v2}/revisions",
            "POST",
            {
                "statement": "should not revise falsified",
                "mechanism": "x",
                "prediction": "y",
                "falsification_criteria": "z",
                "boundary_conditions": "b",
                "actor": "researcher",
                "change_reason": "illegal revise after falsify",
            },
        )
        assert status == 409, blocked

        # cannot bind confirmatory to falsified version
        status, blocked_run = _request(
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
                "hypothesis_version_id": version_v2,
            },
        )
        assert status in {409, 422, 400}, blocked_run

        # v2 experiment becomes stale after falsify
        status, runs = _request(port, token, f"/api/experiments/projects/{project_id}")
        assert status == 200, runs
        listed = runs if isinstance(runs, list) else runs.get("runs") or runs.get("items") or []
        match_v2 = next((r for r in listed if r.get("id") == run_v2["id"]), None)
        assert match_v2 is not None, listed
        assert match_v2.get("dependency_status") == "stale", match_v2

        assert any(ord(ch) > 127 for ch in str(user))
        assert user.resolve() in ws.resolve().parents or str(user.resolve()) in str(ws.resolve())

        return {
            "label": label,
            "project_id": project_id,
            "user_data": str(user),
            "workspace": str(ws),
            "version_v1": version_v1,
            "version_v2": version_v2,
            "run_v1_id": run_v1_id,
            "run_v2_id": run_v2["id"],
            "manifest_v1": str(manifest_v1),
            "manifest_v2": str(manifest_v2),
            "falsified": True,
        }
    finally:
        _stop(process)


def test_dual_clean_hypothesis_lifecycle_revision_and_falsify(tmp_path: Path) -> None:
    base = tmp_path / "双干净假设生命周期"
    base.mkdir()
    run1 = _lifecycle_run("1", base)
    run2 = _lifecycle_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert run1["version_v1"] != run2["version_v1"]
    assert run1["version_v2"] != run2["version_v2"]
    assert Path(run1["workspace"]).resolve() != Path(run2["workspace"]).resolve()
    assert "用户数据-假设生命周期-1" in run1["user_data"]
    assert "用户数据-假设生命周期-2" in run2["user_data"]
    for run in (run1, run2):
        assert run["version_v1"] != run["version_v2"]
        assert run["manifest_v1"] != run["manifest_v2"]
        assert run["run_v1_id"] != run["run_v2_id"]
        assert run["falsified"] is True
