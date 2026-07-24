"""Persistent asynchronous tasks for official Agent CLIs."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.agent_adapters import CliAdapter, AgentResult, StopReason, parse_agent_stream
from services.agent_bundle import build_adapter_manifest
from services.state_store import get_db

_running: dict[str, tuple[CliAdapter, asyncio.Task]] = {}
_LEASE_SECONDS = 90


def _structured_output(adapter: str, stdout: str) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    events: list[dict[str, Any]] = []; final_text = ""; usage: dict[str, Any] = {}
    for line in stdout.splitlines():
        try: value = json.loads(line)
        except json.JSONDecodeError: continue
        if not isinstance(value, dict): continue
        event_type = str(value.get("type", "event")); events.append({"type": event_type, "payload": value})
        if adapter == "codex":
            item = value.get("item") or {}
            if event_type == "item.completed" and item.get("type") == "agent_message": final_text = str(item.get("text", ""))
            if event_type == "turn.completed": usage = value.get("usage") or {}
        elif adapter == "claude":
            if event_type == "result": final_text = str(value.get("result", "")); usage = value.get("usage") or {}
            message = value.get("message") or {}; content = message.get("content") if isinstance(message, dict) else None
            if content and isinstance(content, list):
                texts = [str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"]
                if texts: final_text = "\n".join(texts)
    return events, final_text.strip(), usage


def resolve_cli_launch(executable: str) -> list[str]:
    """Resolve Windows npm ``.cmd`` shims to real binaries.

    Official Node installers ship ``codex.cmd`` / ``claude.cmd`` wrappers that
    re-expand ``%*`` and strip quotes around multi-word prompts.  Launching the
    underlying ``node`` + ``codex.js`` or ``claude.exe`` preserves argv and lets
    prompts containing spaces (and non-ASCII paths) round-trip.
    """
    raw = str(executable or "").strip()
    if not raw:
        return [raw]
    path = Path(raw)
    if os.name != "nt":
        return [raw]
    if path.suffix.lower() not in {".cmd", ".bat"}:
        return [raw]
    stem = path.stem.lower()
    parent = path.parent
    if stem == "claude":
        claude_exe = parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if claude_exe.is_file():
            return [str(claude_exe.resolve())]
        # Global installs sometimes place the native binary next to the shim.
        sibling = parent / "claude.exe"
        if sibling.is_file():
            return [str(sibling.resolve())]
    if stem == "codex":
        codex_js = parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = parent / "node.exe"
        if codex_js.is_file():
            if node.is_file():
                return [str(node.resolve()), str(codex_js.resolve())]
            which_node = shutil.which("node")
            if which_node:
                return [which_node, str(codex_js.resolve())]
    return [raw]


def _command(adapter: str, executable: str, workspace: Path) -> list[str]:
    launch = resolve_cli_launch(executable)
    if adapter == "codex":
        return [
            *launch,
            "exec",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "read-only",
            "--cd",
            str(workspace),
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
        ]
    if adapter == "claude":
        # --tools accepts a variadic value. The equals form prevents it from
        # consuming the positional prompt appended by CliAdapter.  Strict MCP
        # configuration is equally important: otherwise a user-level MCP
        # server can remain callable even when all built-in tools are disabled.
        # Claude requires --mcp-config to point at a real file path, not inline JSON.
        mcp_path = workspace / "vibe-empty-mcp.json"
        workspace.mkdir(parents=True, exist_ok=True)
        mcp_path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
        return [
            *launch,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "plan",
            "--tools=",
            "--setting-sources",
            "project,local",
            "--mcp-config",
            str(mcp_path),
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
        ]
    raise HTTPException(422, detail="Unsupported Agent adapter")


async def recover_interrupted() -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE agent_tasks SET status='interrupted',failure_reason='Application restarted while Agent task was running',updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running','cancelling')")
        await db.execute("UPDATE agent_task_leases SET released_at=CURRENT_TIMESTAMP WHERE released_at IS NULL")
        await db.commit()
    finally:
        await db.close()


async def _acquire_lease(task_id: str, owner: str) -> None:
    db = await get_db()
    try:
        expires = f"datetime('now', '+{_LEASE_SECONDS} seconds')"
        await db.execute(f"INSERT INTO agent_task_leases(task_id,owner,expires_at) VALUES (?,?,{expires})", (task_id, owner))
        await db.execute("UPDATE agent_tasks SET lease_owner=?,lease_expires_at=datetime('now', ?),heartbeat_at=CURRENT_TIMESTAMP WHERE id=?", (owner, f'+{_LEASE_SECONDS} seconds', task_id))
        await db.commit()
    finally:
        await db.close()


async def _heartbeat(task_id: str, owner: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("UPDATE agent_task_leases SET heartbeat_at=CURRENT_TIMESTAMP,expires_at=datetime('now', ?) WHERE task_id=? AND owner=? AND released_at IS NULL", (f'+{_LEASE_SECONDS} seconds', task_id, owner))
        await db.execute("UPDATE agent_tasks SET heartbeat_at=CURRENT_TIMESTAMP,lease_expires_at=datetime('now', ?) WHERE id=? AND lease_owner=?", (f'+{_LEASE_SECONDS} seconds', task_id, owner))
        await db.commit()
        return cursor.rowcount == 1
    finally:
        await db.close()


async def _release_lease(task_id: str, owner: str) -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE agent_task_leases SET released_at=CURRENT_TIMESTAMP WHERE task_id=? AND owner=?", (task_id, owner))
        await db.execute("UPDATE agent_tasks SET lease_owner=NULL,lease_expires_at=NULL WHERE id=? AND lease_owner=?", (task_id, owner))
        await db.commit()
    finally:
        await db.close()


async def _read(task_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,))).fetchone()
        if not row:
            raise HTTPException(404, detail="Agent task not found")
        result = dict(row)
        result["command"] = json.loads(result.pop("command_json"))
        result["events"] = json.loads(result.pop("events_json"))
        result["result"] = json.loads(result.pop("result_json"))
        result["cancellable"] = result["status"] in {"queued", "running"} and task_id in _running
        return result
    finally:
        await db.close()


async def list_tasks(project_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        rows = await (await db.execute("SELECT id FROM agent_tasks WHERE project_id=? ORDER BY created_at DESC", (project_id,))).fetchall()
    finally:
        await db.close()
    return [await _read(row["id"]) for row in rows]


async def _persist_result(task_id: str, result: dict[str, Any]) -> None:
    prior_status = (await _read(task_id))["status"]
    prior = await _read(task_id)
    parsed = parse_agent_stream(prior["adapter"], result["result"].get("stdout", ""), task_id)
    result["result"].update({"final_text": parsed.final_text, "usage": asdict(parsed.usage), "typed_status": parsed.status.value, "schema_error": parsed.error})
    status = "cancelled" if prior_status == "cancelling" else ("completed" if result["result"]["returncode"] == 0 and parsed.status is StopReason.COMPLETED else "failed")
    audit_path = str(WORKSPACES_DIR / "agent-audit" / f"{task_id}.json")
    artifact_path = Path(prior["workspace_path"]) / "agent-response.txt"; artifact_hash = None
    if status == "completed":
        artifact_path.write_text(parsed.final_text, encoding="utf-8"); artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        result["result"].update({"artifact_path": str(artifact_path), "artifact_sha256": artifact_hash})
    failure = None if status == "completed" else (result["result"].get("stderr") or ("Agent returned no final response" if result["result"]["returncode"] == 0 else f"Agent exited with {result['result']['returncode']}"))
    db = await get_db()
    try:
        await db.execute("UPDATE agent_tasks SET status=?,events_json=?,result_json=?,audit_path=?,failure_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, json.dumps(result["events"]), json.dumps(result["result"]), audit_path, failure, task_id))
        if status == "completed" and artifact_hash:
            await db.execute("INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, prior["project_id"], "agent.response", artifact_hash, f"agent:{task_id}", "verified"))
            await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (prior["project_id"], "agent_task_completed", "system", json.dumps({"task_id":task_id,"adapter":prior["adapter"],"artifact_sha256":artifact_hash,"usage":asdict(parsed.usage)})))
        await db.commit()
    finally:
        await db.close()


async def _lease_heartbeat(task_id: str, owner: str) -> None:
    try:
        while await _heartbeat(task_id, owner):
            await asyncio.sleep(_LEASE_SECONDS / 3)
    except asyncio.CancelledError:
        return

async def _worker(
    task_id: str,
    adapter: CliAdapter,
    prompt: str,
    timeout: float,
    environment: dict[str, str],
) -> None:
    owner = uuid.uuid4().hex
    await _acquire_lease(task_id, owner)
    heartbeat = asyncio.create_task(_lease_heartbeat(task_id, owner))
    db = await get_db()
    try:
        await db.execute("UPDATE agent_tasks SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,)); await db.commit()
    finally:
        await db.close()
    try:
        result = await adapter.run(prompt, timeout=timeout, run_id=task_id, env=environment)
        await _persist_result(task_id, result)
    except Exception as error:
        db = await get_db()
        try:
            await db.execute("UPDATE agent_tasks SET status='failed',failure_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(error), task_id)); await db.commit()
        finally:
            await db.close()
    finally:
        heartbeat.cancel()
        await _release_lease(task_id, owner)
        _running.pop(task_id, None)


async def start(project_id: str, adapter_name: str, prompt: str, timeout: float = 120, retry_of: str | None = None) -> dict[str, Any]:
    from services.llm_client import get_env_for_subprocess

    configured_environment = await get_env_for_subprocess()
    manifest = build_adapter_manifest(
        configured_overrides={
            "codex": configured_environment.get("CODEX_BIN", ""),
            "claude": configured_environment.get("CLAUDE_BIN", ""),
        }
    )["adapters"].get(adapter_name, {})
    if manifest.get("status") != "available":
        raise HTTPException(503, detail={"status": "unavailable", "action": manifest.get("action")})
    db = await get_db()
    try:
        project = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project:
            raise HTTPException(404, detail="Research project not found")
    finally:
        await db.close()
    task_id = uuid.uuid4().hex
    workspace = WORKSPACES_DIR / project_id / "agent" / task_id
    workspace.mkdir(parents=True, exist_ok=False)
    command = _command(adapter_name, manifest["executable"], workspace)
    allowed_base = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key in allowed_base}
    role_prefix = "REVIEWER_" if adapter_name == "codex" else "EXECUTOR_"
    environment.update({
        key: value for key, value in configured_environment.items()
        if key in allowed_base or key.startswith(role_prefix) or key in {"CODEX_BIN", "CLAUDE_BIN"}
    })
    model = (
        configured_environment.get("REVIEWER_MODEL_ID", "")
        if adapter_name == "codex"
        else configured_environment.get("EXECUTOR_MODEL_ID", "")
    ).strip()
    if model:
        command.extend(["--model", model])
    adapter = CliAdapter(adapter_name, command, workspace, WORKSPACES_DIR / "agent-audit")
    db = await get_db()
    try:
        await db.execute("INSERT INTO agent_tasks (id,project_id,adapter,prompt,status,workspace_path,command_json,retry_of) VALUES (?,?,?,?,?,?,?,?)", (task_id, project_id, adapter_name, prompt, "queued", str(workspace), json.dumps(command), retry_of)); await db.commit()
    finally:
        await db.close()
    task = asyncio.create_task(_worker(task_id, adapter, prompt, timeout, environment))
    _running[task_id] = (adapter, task)
    return await _read(task_id)


async def cancel(task_id: str) -> dict[str, Any]:
    current = await _read(task_id)
    if current["status"] not in {"queued", "running"}:
        raise HTTPException(409, detail="Only queued or running Agent tasks can be cancelled")
    active = _running.get(task_id)
    if not active:
        raise HTTPException(409, detail="Agent process is no longer owned by this application instance")
    db = await get_db()
    try:
        await db.execute("UPDATE agent_tasks SET status='cancelling',updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,)); await db.commit()
    finally:
        await db.close()
    await active[0].cancel(task_id)
    try:
        await asyncio.wait_for(asyncio.shield(active[1]), 10)
    except asyncio.TimeoutError:
        pass
    return await _read(task_id)


async def retry(task_id: str) -> dict[str, Any]:
    prior = await _read(task_id)
    if prior["status"] not in {"failed", "cancelled", "interrupted"}:
        raise HTTPException(409, detail="Only failed, cancelled or interrupted Agent tasks can retry")
    return await start(prior["project_id"], prior["adapter"], prior["prompt"], retry_of=task_id)
