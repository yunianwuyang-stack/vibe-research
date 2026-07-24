"""Dual Unicode user-data: research-runs Golden Path with non-forgeable gates.

Proves epistemic orchestration surface under two clean roots:
  project create → research-run start → capability-graph
  → honest 409 when client claims gate_passed without verified artifacts
  → blocked step + retry recovery
  → successful contract advance using server-verified hypothesis.manifest
  → process kill/restart durability of run state on same user-data root
  → resume + cancel

No mock gates: advance requires research_artifacts status=verified.
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
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))

HYPOTHESIS = {
    "statement": "Dual-clean research runs persist non-forgeable Golden Path gates under Unicode roots.",
    "mechanism": "Server-verified hypothesis.manifest artifacts are the only gate authority.",
    "prediction": "Contract step completes only when verified artifact ids and provenance match.",
    "falsification_criteria": "If advance accepts client gate_passed without verified rows, fail.",
    "boundary_conditions": "Offline dual-clean E2E without live LLM keys.",
    "actor": "researcher",
    "change_reason": "dual-clean research-run seed",
}


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
    timeout: float = 90,
):
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=payload,
        method=method,
        headers={
            "X-Vibe-Session-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    log_path = user_data / "backend-start.log"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
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
            "info",
        ],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._vibe_log_file = log_file  # type: ignore[attr-defined]
    process._vibe_log_path = log_path  # type: ignore[attr-defined]
    last_status = last_body = last_error = None
    for _ in range(200):
        if process.poll() is not None:
            log_file.flush()
            out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            raise AssertionError(f"backend exited early ({process.returncode}): {out[-4000:]}")
        try:
            status, body = _request(port, token, "/api/health")
            last_status, last_body = status, body
            if status == 200:
                return process
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        time.sleep(0.1)
    process.kill()
    log_file.flush()
    out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    raise AssertionError(
        f"backend failed to start last_status={last_status} last_body={last_body} "
        f"last_error={last_error} log={out[-4000:]}"
    )


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()
    log_file = getattr(process, "_vibe_log_file", None)
    if log_file is not None:
        try:
            log_file.close()
        except Exception:
            pass


def _run_root(port: int, token: str, user_data: Path, label: str) -> dict:
    status, project = _request(
        port,
        token,
        "/api/research-projects",
        "POST",
        {
            "title": f"Research-run dual-clean {label}",
            "research_question": "Do dual-clean Unicode roots persist non-forgeable research runs?",
            "inclusion_criteria": "research-runs + verified artifact gate only",
        },
    )
    assert status == 200, project
    project_id = project["id"]

    status, hyp = _request(
        port,
        token,
        f"/api/research-projects/{project_id}/hypotheses",
        "POST",
        HYPOTHESIS,
    )
    assert status == 200, hyp
    # Hypothesis create writes verified research_artifacts row.
    status, project = _request(port, token, f"/api/research-projects/{project_id}")
    assert status == 200, project
    artifacts = project.get("artifacts") or []
    verified = [a for a in artifacts if a.get("status") == "verified"]
    assert verified, artifacts
    art = verified[0]
    art_id = art["id"]
    provenance = art.get("provenance") or ""
    assert provenance, art

    status, graph = _request(port, token, "/api/research-runs/capability-graph")
    assert status == 200, graph
    assert graph.get("schema_version") or graph.get("nodes"), graph
    golden = graph.get("golden_path") or {}
    golden_nodes = golden.get("nodes") or []
    node_names = {n.get("name") for n in golden_nodes if isinstance(n, dict)}
    assert "contract" in node_names, (node_names, golden)
    assert "adversarial_review" in node_names, node_names
    routes = graph.get("registered_routes") or []
    assert any(str(r).startswith("/api/research-runs") for r in routes), routes
    # Inventory nodes must include production routers (AST inventory).
    inventory = {n.get("name") for n in (graph.get("nodes") or []) if isinstance(n, dict)}
    assert "start" in inventory or "advance" in inventory, inventory

    status, run = _request(port, token, f"/api/research-runs/projects/{project_id}", "POST", {})
    assert status == 200, run
    run_id = run["id"]
    assert run.get("status") == "paused", run
    assert run.get("current_step") == "contract", run
    steps = {s["name"]: s for s in (run.get("steps") or [])}
    assert "contract" in steps and steps["contract"]["status"] == "pending", steps

    # Non-forgeable: client gate_passed without artifacts must 409.
    status, forged = _request(
        port,
        token,
        f"/api/research-runs/{run_id}/steps/contract",
        "POST",
        {
            "input": {"label": label},
            "artifacts": [],
            "provenance": [],
            "gate_passed": True,
            "failure_reason": None,
        },
    )
    assert status == 409, forged

    # Non-forgeable: fake artifact id must 409.
    status, fake = _request(
        port,
        token,
        f"/api/research-runs/{run_id}/steps/contract",
        "POST",
        {
            "input": {"label": label},
            "artifacts": [{"id": "deadbeef" * 4}],
            "provenance": [{"source": "hypothesis:fake"}],
            "gate_passed": True,
            "failure_reason": None,
        },
    )
    assert status == 409, fake

    # Honest block path.
    status, blocked = _request(
        port,
        token,
        f"/api/research-runs/{run_id}/steps/contract",
        "POST",
        {
            "input": {"label": label, "attempt": "block"},
            "artifacts": [],
            "provenance": [],
            "gate_passed": False,
            "failure_reason": "dual-clean intentional block",
        },
    )
    assert status == 200, blocked
    assert blocked.get("status") == "blocked", blocked
    contract = next(s for s in blocked["steps"] if s["name"] == "contract")
    assert contract["status"] == "blocked", contract
    assert contract.get("failure_reason") == "dual-clean intentional block", contract
    assert int(contract.get("attempts") or 0) >= 1, contract

    # Retry recovery.
    status, retried = _request(port, token, f"/api/research-runs/{run_id}/steps/contract/retry", "POST", {})
    assert status == 200, retried
    assert retried.get("status") == "paused", retried
    assert retried.get("current_step") == "contract", retried
    contract = next(s for s in retried["steps"] if s["name"] == "contract")
    assert contract["status"] == "pending", contract

    # Real gate pass with server-verified artifact.
    status, advanced = _request(
        port,
        token,
        f"/api/research-runs/{run_id}/steps/contract",
        "POST",
        {
            "input": {"label": label, "attempt": "pass"},
            "artifacts": [{"id": art_id}],
            "provenance": [{"source": provenance}],
            "gate_passed": True,
            "failure_reason": None,
        },
    )
    assert status == 200, advanced
    assert advanced.get("status") == "paused", advanced
    assert advanced.get("current_step") == "question", advanced
    contract = next(s for s in advanced["steps"] if s["name"] == "contract")
    assert contract["status"] == "completed", contract
    assert contract.get("artifacts") and contract["artifacts"][0]["id"] == art_id, contract

    # Resume paused run.
    status, resumed = _request(port, token, f"/api/research-runs/{run_id}/resume", "POST", {})
    assert status == 200, resumed
    assert resumed.get("status") == "running", resumed

    # Process restart durability on the same Unicode user-data root.
    return {
        "project_id": project_id,
        "run_id": run_id,
        "artifact_id": art_id,
        "provenance": provenance,
        "label": label,
        "user_data": str(user_data),
    }


def _assert_restart_and_cancel(port: int, token: str, seed: dict) -> dict:
    status, run = _request(port, token, f"/api/research-runs/{seed['run_id']}")
    assert status == 200, run
    assert run.get("id") == seed["run_id"], run
    # After restart, last status was running; if heartbeat not present it stays.
    assert run.get("status") in {"running", "paused"}, run
    assert run.get("current_step") == "question", run
    contract = next(s for s in run["steps"] if s["name"] == "contract")
    assert contract["status"] == "completed", contract

    # Project-scoped list restores active run without client-side run id cache.
    status, listed = _request(port, token, f"/api/research-runs/projects/{seed['project_id']}")
    assert status == 200, listed
    assert listed.get("project_id") == seed["project_id"], listed
    assert int(listed.get("count") or 0) >= 1, listed
    run_ids = {item.get("id") for item in (listed.get("runs") or [])}
    assert seed["run_id"] in run_ids, listed
    active = listed.get("active") or {}
    assert active.get("id") == seed["run_id"], listed
    assert active.get("current_step") == "question", active
    assert active.get("status") in {"running", "paused"}, active
    active_contract = next(s for s in (active.get("steps") or []) if s["name"] == "contract")
    assert active_contract["status"] == "completed", active_contract
    assert active_contract.get("artifacts") and active_contract["artifacts"][0]["id"] == seed["artifact_id"]

    status, project = _request(port, token, f"/api/research-projects/{seed['project_id']}")
    assert status == 200, project
    assert project.get("id") == seed["project_id"]
    assert any(a.get("id") == seed["artifact_id"] for a in (project.get("artifacts") or [])), project

    status, cancelled = _request(
        port,
        token,
        f"/api/research-runs/{seed['run_id']}/cancel",
        "POST",
        {"reason": f"dual-clean cancel {seed['label']}"},
    )
    assert status == 200, cancelled
    assert cancelled.get("status") == "cancelled", cancelled

    # After cancel, list still returns the run; active prefers remaining in-flight
    # runs, otherwise falls back to the latest row (cancelled is still durable).
    status, listed_after = _request(port, token, f"/api/research-runs/projects/{seed['project_id']}")
    assert status == 200, listed_after
    assert any(item.get("id") == seed["run_id"] for item in (listed_after.get("runs") or [])), listed_after
    assert listed_after.get("active"), listed_after

    # Start a second run; history must keep both, and GET by id opens the cancelled one
    # (workbench history list → openResearchRun path).
    status, second = _request(
        port, token, f"/api/research-runs/projects/{seed['project_id']}", "POST", {}
    )
    assert status == 200, second
    second_id = second["id"]
    assert second_id != seed["run_id"]
    status, history = _request(port, token, f"/api/research-runs/projects/{seed['project_id']}")
    assert status == 200, history
    hist_ids = {item.get("id") for item in (history.get("runs") or [])}
    assert seed["run_id"] in hist_ids and second_id in hist_ids, history
    assert int(history.get("count") or 0) >= 2, history
    active = history.get("active") or {}
    assert active.get("id") == second_id, history
    status, historical = _request(port, token, f"/api/research-runs/{seed['run_id']}")
    assert status == 200, historical
    assert historical.get("status") == "cancelled", historical
    assert historical.get("current_step") == cancelled.get("current_step")
    hist_contract = next(s for s in historical["steps"] if s["name"] == "contract")
    assert hist_contract["status"] == "completed", hist_contract

    return {
        "run_status": cancelled.get("status"),
        "current_step": cancelled.get("current_step"),
        "contract_status": contract["status"],
        "list_restored": True,
        "history_count": int(history.get("count") or 0),
        "second_run_id": second_id,
    }


def test_dual_clean_research_runs_gate_and_restart(tmp_path: Path) -> None:
    root_a = tmp_path / "用户数据甲-runs-α"
    root_b = tmp_path / "用户数据乙-runs-β"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)

    port_a, port_b = _free_port(), _free_port()
    token_a, token_b = "runs-token-a", "runs-token-b"
    proc_a = proc_b = None
    try:
        proc_a = _server(port_a, token_a, root_a)
        proc_b = _server(port_b, token_b, root_b)
        seed_a = _run_root(port_a, token_a, root_a, "甲")
        seed_b = _run_root(port_b, token_b, root_b, "乙")
    finally:
        if proc_a is not None:
            _stop(proc_a)
        if proc_b is not None:
            _stop(proc_b)

    # Restart each root independently and prove durability + cancel.
    proc_a = proc_b = None
    try:
        proc_a = _server(port_a, token_a, root_a)
        proc_b = _server(port_b, token_b, root_b)
        after_a = _assert_restart_and_cancel(port_a, token_a, seed_a)
        after_b = _assert_restart_and_cancel(port_b, token_b, seed_b)
    finally:
        if proc_a is not None:
            _stop(proc_a)
        if proc_b is not None:
            _stop(proc_b)

    assert seed_a["run_id"] != seed_b["run_id"]
    assert seed_a["project_id"] != seed_b["project_id"]
    assert seed_a["artifact_id"] != seed_b["artifact_id"]
    assert after_a["run_status"] == "cancelled" and after_b["run_status"] == "cancelled"
    assert after_a["contract_status"] == "completed" and after_b["contract_status"] == "completed"
    # Roots must not share databases.
    assert (root_a / "vibe.db").is_file() or any(root_a.rglob("*.db")), list(root_a.rglob("*"))[:20]
    assert (root_b / "vibe.db").is_file() or any(root_b.rglob("*.db")), list(root_b.rglob("*"))[:20]
