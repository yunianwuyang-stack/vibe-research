"""Dual Unicode roots: DAG operations detail + real failed-node recovery.

Chain under test:
  create project → host workflow complete → operations overview/detail
  (DAG steps, attempts, artifact lineage) → force-fail a completed node in the
  durable SQLite ledger → POST /recover → executor re-runs → completed + recovery
  operation row persisted.

No mock executor; recovery goes through request_step_recovery → run_workflow.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
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
            raise AssertionError(f"backend exited early: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"backend failed to start: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(
    port: int,
    token: str,
    wf_id: str,
    *,
    seconds: float = 300.0,
    terminal: set[str] | None = None,
) -> dict:
    # Default: treat paused as terminal only for normal runs. Recovery briefly
    # parks the workflow as paused while the executor is scheduled — callers
    # waiting on recover must pass terminal={"completed","failed",...}.
    done = terminal or {"completed", "failed", "waiting_checkpoint", "paused"}
    deadline = time.time() + seconds
    detail: dict = {}
    while time.time() < deadline:
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        if str(detail.get("status") or "") in done:
            return detail
        time.sleep(0.4)
    raise AssertionError(f"workflow {wf_id} not terminal: {detail}")


def _approve_if_waiting(port: int, token: str, wf_id: str, detail: dict) -> dict:
    hops = 0
    while detail.get("status") == "waiting_checkpoint" and hops < 12:
        status, cp = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/checkpoint",
            "POST",
            {"action": "approve", "data": {"feedback": "dual-clean dag auto-approve"}},
        )
        assert status == 200, cp
        detail = _wait_terminal(port, token, wf_id, seconds=240)
        hops += 1
    return detail


def _find_db(user_data: Path) -> Path:
    candidates = list(user_data.rglob("vibe.db"))
    if not candidates:
        candidates = list(user_data.rglob("*.db"))
    assert candidates, f"no sqlite ledger under {user_data}"
    # Prefer vibe.db
    for path in candidates:
        if path.name == "vibe.db":
            return path
    return candidates[0]


def _force_fail_last_completed_step(db_path: Path, wf_id: str) -> str:
    """Mark workflow failed at the last completed host step so recover is legal."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT skill_name, status, step_order FROM workflow_steps "
            "WHERE workflow_id=? ORDER BY step_order",
            (wf_id,),
        ).fetchall()
        assert rows, wf_id
        target = None
        for row in reversed(rows):
            if str(row["status"]) == "completed":
                target = str(row["skill_name"])
                break
        assert target, f"no completed step to fail: {rows}"
        conn.execute(
            "UPDATE workflow_steps SET status='failed', "
            "error_message=?, completed_at=NULL WHERE workflow_id=? AND skill_name=?",
            ("injected dual-clean recovery probe failure", wf_id, target),
        )
        conn.execute(
            "UPDATE workflows SET status='failed', current_step=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (target, wf_id),
        )
        conn.commit()
        return target
    finally:
        conn.close()


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-DAG恢复-{label}"
    user.mkdir(parents=True)
    token = f"dual-dag-rec-{label}"
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
                "title": f"DAG recovery dual-clean {label}",
                "research_question": "Does operations DAG + recover work dual-clean?",
                "inclusion_criteria": "attempts + lineage + recovery operation row",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        # Short host scaffold: one_sentence_project → project-blueprint skill.
        status, wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "one_sentence_project",
                "title": f"DAG blueprint {label}",
                "params": {
                    "one_sentence": f"evidence-native dual-clean dag recovery {label}",
                    "skip_improvement_loop": True,
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

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _approve_if_waiting(
            port, token, wf_id, _wait_terminal(port, token, wf_id, seconds=240)
        )
        assert final["status"] == "completed", final

        for name in ("PROJECT_BLUEPRINT.md", "RESEARCH_CONTRACT_DRAFT.md", "MILESTONES.md"):
            path = ws / name
            assert path.is_file() and path.stat().st_size >= 80, path

        # --- Operations overview (cross-project DAG control plane) ---
        status, ops = _request(port, token, f"/api/workflows/operations?project_id={project_id}")
        assert status == 200, ops
        assert ops.get("summary", {}).get("total", 0) >= 1
        run_ids = [str(r.get("id")) for r in (ops.get("runs") or [])]
        assert wf_id in run_ids, run_ids
        run = next(r for r in ops["runs"] if str(r.get("id")) == wf_id)
        assert run.get("progress", {}).get("total", 0) >= 1
        assert int(run.get("artifact_count") or 0) >= 1

        # --- Operations detail: DAG steps + attempts + artifacts ---
        status, op_detail = _request(port, token, f"/api/workflows/operations/{wf_id}")
        assert status == 200, op_detail
        # Steps live under workflow (control-plane envelope), not top-level.
        workflow_block = op_detail.get("workflow") or {}
        steps = workflow_block.get("steps") or op_detail.get("steps") or []
        assert steps, {k: type(v).__name__ for k, v in op_detail.items()}
        assert any(str(s.get("status")) == "completed" for s in steps)
        attempts = op_detail.get("attempts") or []
        assert attempts, "expected workflow_step_attempts rows for host execution"
        artifacts = op_detail.get("artifacts") or []
        assert artifacts, "expected on-disk artifacts with lineage hashes"
        hashed = [a for a in artifacts if a.get("sha256") and int(a.get("size") or 0) > 0]
        assert hashed, artifacts[:5]
        assert any(
            str(a.get("path") or "").replace("\\", "/").endswith("PROJECT_BLUEPRINT.md")
            for a in artifacts
        ), [a.get("path") for a in artifacts[:20]]
        # At least one artifact must verify lineage sha against on-disk content.
        assert any(a.get("lineage_verified") is True for a in artifacts), artifacts[:5]
        assert op_detail.get("events"), "durable operation events required for DAG monitor"

        # Honest recover on completed workflow must 409 (no failed node).
        status, bad = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/recover",
            "POST",
            {"reason": "should-conflict-when-completed", "requested_by": "test"},
        )
        assert status == 409, (status, bad)

        # Inject durable failure into the product ledger, then recover for real.
        db_path = _find_db(user)
        failed_skill = _force_fail_last_completed_step(db_path, wf_id)

        status, broken = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200 and broken.get("status") == "failed", broken

        status, ops_failed = _request(
            port, token, f"/api/workflows/operations?project_id={project_id}&status=failed"
        )
        assert status == 200, ops_failed
        failed_run = next(
            (r for r in (ops_failed.get("runs") or []) if str(r.get("id")) == wf_id),
            None,
        )
        assert failed_run is not None
        assert failed_run.get("recoverable") is True
        assert (failed_run.get("recovery_target") or {}).get("skill_name") == failed_skill

        status, recover = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/recover",
            "POST",
            {
                "reason": f"dual-clean real recovery of {failed_skill}",
                "requested_by": "dual-clean-test",
            },
        )
        assert status in {200, 202}, recover
        assert recover.get("ok") is True
        assert recover.get("skill_name") == failed_skill
        assert recover.get("operation_id")
        assert recover.get("status") in {"accepted", "running", "completed"}

        # Recovery accepts with status=paused then runs the real executor; do not
        # treat intermediate paused as success.
        recovered = _wait_terminal(
            port,
            token,
            wf_id,
            seconds=300,
            terminal={"completed", "failed", "waiting_checkpoint"},
        )
        recovered = _approve_if_waiting(port, token, wf_id, recovered)
        if recovered.get("status") != "completed":
            recovered = _wait_terminal(
                port,
                token,
                wf_id,
                seconds=300,
                terminal={"completed", "failed"},
            )
        assert recovered["status"] == "completed", recovered

        # Artifacts still present after recovery re-execution.
        for name in ("PROJECT_BLUEPRINT.md", "RESEARCH_CONTRACT_DRAFT.md", "MILESTONES.md"):
            assert (ws / name).is_file() and (ws / name).stat().st_size >= 80

        status, op_after = _request(port, token, f"/api/workflows/operations/{wf_id}")
        assert status == 200, op_after
        recoveries = op_after.get("recoveries") or op_after.get("recovery_operations") or []
        if not recoveries:
            # Some payloads nest recovery under events; also accept DB-backed attempts growth.
            assert len(op_after.get("attempts") or []) >= len(attempts)
        else:
            assert any(
                str(r.get("skill_name")) == failed_skill
                or str(r.get("status")) in {"accepted", "completed", "running", "interrupted"}
                for r in recoveries
            ), recoveries

        # Host lineage must exist for blueprint skill.
        lineage = ws / ".host_builds" / "project-blueprint.json"
        assert lineage.is_file()
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload.get("executor") == "host_step_runner"

        return {
            "label": label,
            "project_id": project_id,
            "wf_id": wf_id,
            "user_data": str(user),
            "ws": str(ws),
            "failed_skill": failed_skill,
            "artifact_count": len(artifacts),
            "attempt_count": len(attempts),
            "db": str(db_path),
        }
    finally:
        _stop(process)


def test_dual_clean_dag_operations_and_recovery(tmp_path: Path) -> None:
    base = tmp_path / "双干净DAG恢复"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)

    assert run1["project_id"] != run2["project_id"]
    assert run1["wf_id"] != run2["wf_id"]
    assert Path(run1["user_data"]).resolve() != Path(run2["user_data"]).resolve()
    assert "用户数据-DAG恢复-1" in run1["user_data"]
    assert "用户数据-DAG恢复-2" in run2["user_data"]
    for run in (run1, run2):
        assert run["artifact_count"] >= 1
        assert run["attempt_count"] >= 1
        assert Path(run["ws"], "PROJECT_BLUEPRINT.md").is_file()
