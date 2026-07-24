"""Multi-agent collaboration: multi-role + optional CLI, real providers only.

Never fabricates model outputs. Missing credentials produce honest failed steps
and a durable collaboration report under the project workspace.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.state_store import get_db

ROLE_ORDER = ("executor", "reviewer", "editor_ai")
CLI_ADAPTERS = ("codex", "claude")
ROLE_PROMPTS = {
    "executor": (
        "You are the executor agent for Vibe Research. Produce a concrete, "
        "actionable research execution plan for the goal below. Use numbered steps, "
        "name required evidence, and list risks. Goal:\n{goal}"
    ),
    "reviewer": (
        "You are an independent scientific critic. Review the executor plan below. "
        "Attack unsupported claims, demand evidence, and list blocking issues. "
        "Goal:\n{goal}\n\nExecutor plan:\n{prior}"
    ),
    "editor_ai": (
        "You are the scientific editor. Rewrite the plan into a submission-ready "
        "research narrative outline that preserves critic constraints. "
        "Goal:\n{goal}\n\nPrior artifacts:\n{prior}"
    ),
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    workspace.relative_to(WORKSPACES_DIR.resolve())
    return workspace


async def _ensure_schema(db: Any) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_collaborations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL,
            goal TEXT NOT NULL,
            roles_json TEXT NOT NULL,
            cli_adapters_json TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            report_path TEXT,
            report_sha256 TEXT,
            failure_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_collaborations_project ON agent_collaborations(project_id)"
    )


def _serialize(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "status": row["status"],
        "goal": row["goal"],
        "roles": json.loads(row["roles_json"]),
        "cli_adapters": json.loads(row["cli_adapters_json"]),
        "steps": json.loads(row["steps_json"]),
        "report_path": row["report_path"],
        "report_sha256": row["report_sha256"],
        "failure_reason": row["failure_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _read(collab_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        await _ensure_schema(db)
        row = await (await db.execute("SELECT * FROM agent_collaborations WHERE id=?", (collab_id,))).fetchone()
        if not row:
            raise HTTPException(404, detail="Collaboration not found")
        return _serialize(row)
    finally:
        await db.close()


async def list_collaborations(project_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        await _ensure_schema(db)
        rows = await (
            await db.execute(
                "SELECT * FROM agent_collaborations WHERE project_id=? ORDER BY rowid DESC LIMIT 100",
                (project_id,),
            )
        ).fetchall()
        return [_serialize(row) for row in rows]
    finally:
        await db.close()


async def _role_step(role: str, goal: str, prior_text: str, timeout: float) -> dict[str, Any]:
    from services.llm_client import call_llm

    prompt = ROLE_PROMPTS[role].format(goal=goal, prior=prior_text or "(none)")
    started = time.time()
    try:
        text = await call_llm(role, prompt, timeout=int(timeout))
        output = (text or "").strip()
        if not output:
            return {
                "kind": "model_role",
                "role": role,
                "status": "failed",
                "error": "empty_model_response",
                "duration_seconds": round(time.time() - started, 3),
                "output": "",
                "output_sha256": None,
            }
        return {
            "kind": "model_role",
            "role": role,
            "status": "completed",
            "error": None,
            "duration_seconds": round(time.time() - started, 3),
            "output": output,
            "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        }
    except Exception as error:
        message = str(error).strip() or error.__class__.__name__
        return {
            "kind": "model_role",
            "role": role,
            "status": "failed",
            "error": message,
            "duration_seconds": round(time.time() - started, 3),
            "output": "",
            "output_sha256": None,
        }


async def _cli_step(project_id: str, adapter: str, goal: str, prior_text: str, timeout: float) -> dict[str, Any]:
    from services import agent_tasks

    prompt = (
        f"[Vibe Research multi-agent collaboration]\n"
        f"Adapter: {adapter}\nGoal: {goal}\n\n"
        f"Prior agent outputs:\n{prior_text or '(none)'}\n\n"
        "Produce a concise, auditable contribution. Do not claim credentials you lack."
    )
    started = time.time()
    try:
        task = await agent_tasks.start(project_id, adapter, prompt, timeout)
        task_id = task["id"]
        terminal = {"completed", "failed", "cancelled", "interrupted"}
        detail = task
        for _ in range(max(4, int(timeout * 4))):
            detail = await agent_tasks._read(task_id)
            if detail.get("status") in terminal:
                break
            await __import__("asyncio").sleep(0.25)
        status = detail.get("status")
        ok = status == "completed"
        final_text = ""
        result = detail.get("result") or {}
        if isinstance(result, dict):
            final_text = str(result.get("final_text") or result.get("stdout") or "")
        return {
            "kind": "cli_adapter",
            "role": adapter,
            "status": "completed" if ok else "failed",
            "error": None if ok else (detail.get("failure_reason") or f"cli_status_{status}"),
            "duration_seconds": round(time.time() - started, 3),
            "output": final_text,
            "output_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest() if final_text else None,
            "task_id": task_id,
            "audit_path": detail.get("audit_path"),
        }
    except Exception as error:
        message = str(error).strip() or error.__class__.__name__
        return {
            "kind": "cli_adapter",
            "role": adapter,
            "status": "failed",
            "error": message,
            "duration_seconds": round(time.time() - started, 3),
            "output": "",
            "output_sha256": None,
            "task_id": None,
            "audit_path": None,
        }


async def start(
    project_id: str,
    goal: str,
    roles: list[str] | None = None,
    cli_adapters: list[str] | None = None,
    timeout_seconds: float = 120,
) -> dict[str, Any]:
    goal = (goal or "").strip()
    if len(goal) < 3:
        raise HTTPException(422, detail="goal must be at least 3 characters")
    timeout_seconds = float(timeout_seconds)
    if not 5 <= timeout_seconds <= 1800:
        raise HTTPException(422, detail="timeout_seconds must be between 5 and 1800")

    selected_cli = []
    for name in cli_adapters or []:
        if name not in CLI_ADAPTERS:
            raise HTTPException(422, detail="cli_adapters must be codex and/or claude")
        if name not in selected_cli:
            selected_cli.append(name)
    # Default to full model role set only when the caller omitted roles entirely.
    # Explicit empty roles is allowed for CLI-only collaboration (no fake model steps).
    if roles is None:
        selected_roles = list(ROLE_ORDER)
    else:
        selected_roles = [role for role in ROLE_ORDER if role in set(roles)]
        if not selected_roles and not selected_cli:
            raise HTTPException(
                422,
                detail="roles must include executor, reviewer, and/or editor_ai when no CLI adapters are set",
            )
    if not selected_roles and not selected_cli:
        raise HTTPException(422, detail="At least one model role or CLI adapter is required")

    db = await get_db()
    try:
        await _ensure_schema(db)
        project = await (await db.execute("SELECT id FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project:
            raise HTTPException(404, detail="Research project not found")
        collab_id = uuid.uuid4().hex
        await db.execute(
            "INSERT INTO agent_collaborations "
            "(id,project_id,status,goal,roles_json,cli_adapters_json,steps_json,failure_reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                collab_id,
                project_id,
                "running",
                goal,
                json.dumps(selected_roles, ensure_ascii=False),
                json.dumps(selected_cli, ensure_ascii=False),
                "[]",
                None,
            ),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "agent_collaboration_started",
                "system",
                json.dumps({"collaboration_id": collab_id, "roles": selected_roles, "cli_adapters": selected_cli}, ensure_ascii=False),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    steps: list[dict[str, Any]] = []
    prior_chunks: list[str] = []
    for role in selected_roles:
        step = await _role_step(role, goal, "\n\n".join(prior_chunks), timeout_seconds)
        steps.append(step)
        if step["status"] == "completed" and step.get("output"):
            prior_chunks.append(f"## {role}\n{step['output']}")
    for adapter in selected_cli:
        step = await _cli_step(project_id, adapter, goal, "\n\n".join(prior_chunks), timeout_seconds)
        steps.append(step)
        if step["status"] == "completed" and step.get("output"):
            prior_chunks.append(f"## {adapter}\n{step['output']}")

    failed = [step for step in steps if step["status"] != "completed"]
    status = "completed" if steps and not failed else "failed"
    failure_reason = None
    if failed:
        failure_reason = "; ".join(
            f"{step.get('role')}:{step.get('error') or step.get('status')}" for step in failed
        )

    report = {
        "format_version": "agent-collaboration/v1",
        "id": collab_id,
        "project_id": project_id,
        "goal": goal,
        "roles": selected_roles,
        "cli_adapters": selected_cli,
        "status": status,
        "failure_reason": failure_reason,
        "steps": steps,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "vibe.agent-collaboration/1.0",
        "inputs_sha256": _sha({"goal": goal, "roles": selected_roles, "cli_adapters": selected_cli}),
    }
    relative = f"multi-agent/collaboration-{collab_id}.json"
    path = _workspace(project_id) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(report)
    digest = hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw)

    db = await get_db()
    try:
        await _ensure_schema(db)
        await db.execute(
            "UPDATE agent_collaborations SET status=?, steps_json=?, report_path=?, report_sha256=?, "
            "failure_reason=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                status,
                json.dumps(steps, ensure_ascii=False),
                relative,
                digest,
                failure_reason,
                collab_id,
            ),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "agent_collaboration_finished",
                "system",
                json.dumps(
                    {
                        "collaboration_id": collab_id,
                        "status": status,
                        "report_path": relative,
                        "report_sha256": digest,
                        "failure_reason": failure_reason,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return await _read(collab_id)


async def get_collaboration(collab_id: str) -> dict[str, Any]:
    return await _read(collab_id)
