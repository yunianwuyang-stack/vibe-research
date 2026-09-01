"""Persisted cross-project workflow operations and recovery orchestration.

The workflow engine remains the only executor.  This module records its
observable attempts/events/artifacts and provides a durable control-plane for
retrying an actually failed node and continuing the original workflow.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, MutableMapping

from services.state_store import get_db
from services.state_planes import project_state_planes

log = logging.getLogger(__name__)

_INVOCATION: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "workflow_operation_invocation", default=None,
)

_SKIP_DIRS = {
    ".git", "_sandbox", "_templates", "_tmp", "__pycache__", "node_modules",
}
_SKIP_NAMES = {"CLAUDE.md", "_created_files.json"}
_SKIP_SUFFIXES = {
    ".aux", ".bbl", ".blg", ".fdb_latexmk", ".fls", ".lof", ".log",
    ".lot", ".nav", ".out", ".pyc", ".snm", ".synctex.gz", ".toc",
    ".vrb", ".xdv",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _included(relative: Path) -> bool:
    if any(part.startswith(".") or part in _SKIP_DIRS for part in relative.parts):
        return False
    if relative.name in _SKIP_NAMES:
        return False
    return not any(relative.name.lower().endswith(suffix) for suffix in _SKIP_SUFFIXES)


def _workspace_artifact_count(workspace_value: Any) -> int:
    """Count only files that currently exist and are visible as run artifacts."""
    workspace = Path(str(workspace_value or ""))
    if not workspace.is_dir():
        return 0
    return sum(
        1
        for path in workspace.rglob("*")
        if path.is_file() and _included(path.relative_to(workspace))
    )


def _safe_workspace_file(workspace: Path, value: str) -> tuple[Path, str] | None:
    normalized = str(value or "").replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return None
    relative = Path(normalized)
    if relative.is_absolute() or ".." in relative.parts or not _included(relative):
        return None
    root = workspace.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate, relative.as_posix()


@contextmanager
def recovery_invocation(operation_id: str, target_step: str, mode: str):
    """Tag attempts created while one persisted recovery operation is active."""
    token = _INVOCATION.set(
        {"operation_id": operation_id, "target_step": target_step, "mode": mode},
    )
    try:
        yield
    finally:
        _INVOCATION.reset(token)


async def begin_step_attempt(workflow_id: str, skill_name: str) -> str:
    """Create a durable attempt before the real executor is invoked."""
    invocation_context = _INVOCATION.get() or {}
    operation_id = invocation_context.get("operation_id")
    if operation_id:
        invocation = (
            invocation_context.get("mode", "recovery")
            if invocation_context.get("target_step") == skill_name
            else "recovery_continuation"
        )
    else:
        invocation = "workflow"

    attempt_id = uuid.uuid4().hex
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (
            await db.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) AS value "
                "FROM workflow_step_attempts WHERE workflow_id=? AND skill_name=?",
                (workflow_id, skill_name),
            )
        ).fetchone()
        number = int(row["value"]) + 1
        await db.execute(
            "INSERT INTO workflow_step_attempts "
            "(id, workflow_id, skill_name, attempt_number, invocation, status, "
            " recovery_operation_id, started_at) VALUES (?,?,?,?,?,'running',?,?)",
            (attempt_id, workflow_id, skill_name, number, invocation, operation_id, _now()),
        )
        await db.commit()
        return attempt_id
    finally:
        await db.close()


async def finish_step_attempt(
    attempt_id: str,
    *,
    cancelled: bool = False,
    unhandled_error: str | None = None,
) -> None:
    """Seal an attempt and hash every output the engine attributed to it."""
    db = await get_db()
    try:
        attempt = await (
            await db.execute(
                "SELECT workflow_id, skill_name FROM workflow_step_attempts WHERE id=?",
                (attempt_id,),
            )
        ).fetchone()
        if attempt is None:
            return
        workflow_id = str(attempt["workflow_id"])
        skill_name = str(attempt["skill_name"])
        workflow = await (
            await db.execute(
                "SELECT workspace_dir FROM workflows WHERE id=?", (workflow_id,),
            )
        ).fetchone()
        step = await (
            await db.execute(
                "SELECT status, output_files, error_message FROM workflow_steps "
                "WHERE workflow_id=? AND skill_name=? ORDER BY step_order LIMIT 1",
                (workflow_id, skill_name),
            )
        ).fetchone()

        step_status = str(step["status"]) if step else "failed"
        if cancelled:
            status = "interrupted"
        elif unhandled_error:
            status = "failed"
        elif step_status in {"completed", "skipped"}:
            status = step_status
        elif step_status == "failed":
            status = "failed"
        else:
            status = "interrupted"
        # Always materialise a non-empty error string for failed/interrupted
        # attempts.  Persisting NULL here forces every consumer (UI, recovery
        # operations table, SSE) to fall back to the opaque "node execution
        # failed", which made the real cause undiagnosable for the
        # fb4f4e5b7272 paper-figure failures.
        if unhandled_error:
            error = unhandled_error
        elif step and step["error_message"]:
            error = str(step["error_message"])
        elif status == "failed":
            error = (
                f"step '{skill_name}' failed but recorded no error_message; "
                "this attempt likely crashed before the engine could persist stderr"
            )
        elif status == "interrupted" and not cancelled:
            error = (
                f"step '{skill_name}' ended in unexpected state '{step_status}'; "
                "treating as interrupted"
            )
        else:
            error = ""
        outputs = _loads(step["output_files"], []) if step else []
        outputs = outputs if isinstance(outputs, list) else []

        artifact_count = 0
        if status in {"completed", "skipped"} and workflow:
            workspace = Path(str(workflow["workspace_dir"] or ""))
            for output in outputs:
                safe = _safe_workspace_file(workspace, str(output))
                if safe is None:
                    continue
                path, relative = safe
                if not path.is_file():
                    continue
                sha256 = await asyncio.to_thread(_sha256_file, path)
                previous = await (
                    await db.execute(
                        "SELECT id, sha256 FROM workflow_artifact_lineage "
                        "WHERE workflow_id=? AND path=? AND state='current' "
                        "ORDER BY id DESC LIMIT 1",
                        (workflow_id, relative),
                    )
                ).fetchone()
                predecessor = str(previous["sha256"]) if previous else None
                if previous:
                    await db.execute(
                        "UPDATE workflow_artifact_lineage SET state='superseded' "
                        "WHERE workflow_id=? AND path=? AND state='current'",
                        (workflow_id, relative),
                    )
                await db.execute(
                    "INSERT OR REPLACE INTO workflow_artifact_lineage "
                    "(workflow_id, step_name, attempt_id, path, sha256, predecessor_sha256, "
                    " size, state, recorded_at) VALUES (?,?,?,?,?,?,?,'current',?)",
                    (
                        workflow_id, skill_name, attempt_id, relative, sha256,
                        predecessor, path.stat().st_size, _now(),
                    ),
                )
                artifact_count += 1

        await db.execute(
            "UPDATE workflow_step_attempts SET status=?, output_files=?, artifact_count=?, "
            "error_message=?, finished_at=? WHERE id=?",
            (status, _json(outputs), artifact_count, error[:2000] if error else None, _now(), attempt_id),
        )
        await db.commit()
    finally:
        await db.close()


async def record_workflow_event(workflow_id: str, payload: dict[str, Any]) -> int:
    """Append an event before it is delivered to live subscribers."""
    event = dict(payload)
    event.setdefault("workflow_id", workflow_id)
    event_type = str(event.get("type") or "workflow_event")
    db = await get_db()
    try:
        workflow = await (
            await db.execute("SELECT project_id FROM workflows WHERE id=?", (workflow_id,))
        ).fetchone()
        cursor = await db.execute(
            "INSERT INTO workflow_operation_events "
            "(workflow_id, project_id, event_type, payload_json, created_at) VALUES (?,?,?,?,?)",
            (
                workflow_id,
                str(workflow["project_id"]) if workflow and workflow["project_id"] else None,
                event_type,
                _json(event),
                _now(),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)
    finally:
        await db.close()


async def publish_workflow_event(workflow_id: str, payload: dict[str, Any]) -> None:
    """Durably record an engine event, then mirror it to workflow/global WS."""
    event = dict(payload)
    try:
        event_id = await record_workflow_event(workflow_id, event)
        event["operation_event_id"] = event_id
    except Exception as exc:  # real-time delivery must survive a telemetry fault
        log.warning("Unable to persist workflow event %s: %s", workflow_id, exc)
    from routers.ws import manager

    await manager.broadcast(workflow_id, event)


async def list_events(
    *,
    after_id: int = 0,
    project_id: str | None = None,
    workflow_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses = ["id > ?"]
    params: list[Any] = [max(0, int(after_id))]
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if workflow_id:
        clauses.append("workflow_id = ?")
        params.append(workflow_id)
    params.append(max(1, min(int(limit), 1000)))
    db = await get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT id, workflow_id, project_id, event_type, payload_json, created_at "
                f"FROM workflow_operation_events WHERE {' AND '.join(clauses)} "
                "ORDER BY id LIMIT ?",
                params,
            )
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "workflow_id": row["workflow_id"],
                "project_id": row["project_id"],
                "type": row["event_type"],
                "payload": _loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        await db.close()


async def stream_events(
    request: Any,
    *,
    after_id: int = 0,
    project_id: str | None = None,
    workflow_id: str | None = None,
    one_shot: bool = False,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    """Replay persisted events and then tail them without losing reconnects."""
    cursor = max(0, int(after_id))
    heartbeat_at = asyncio.get_running_loop().time()
    yield "retry: 1500\n\n"
    while True:
        if await request.is_disconnected():
            return
        events = await list_events(
            after_id=cursor, project_id=project_id, workflow_id=workflow_id, limit=200,
        )
        if events:
            for event in events:
                cursor = int(event["id"])
                yield (
                    f"id: {cursor}\n"
                    f"event: {event['type']}\n"
                    f"data: {_json(event)}\n\n"
                )
            heartbeat_at = asyncio.get_running_loop().time()
            if one_shot:
                return
            continue
        if one_shot:
            return
        now = asyncio.get_running_loop().time()
        if now - heartbeat_at >= max(0.0, heartbeat_seconds):
            yield f": heartbeat {_now()}\n\n"
            heartbeat_at = now
        await asyncio.sleep(0.75)


def _step_counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(steps), "pending": 0, "running": 0,
        "waiting_checkpoint": 0, "completed": 0, "failed": 0, "skipped": 0,
    }
    for step in steps:
        key = str(step.get("status") or "pending")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _recovery_target(workflow: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_order = sorted(steps, key=lambda item: int(item.get("step_order") or 0))
    failed = next((item for item in by_order if item.get("status") == "failed"), None)
    if failed is None and workflow.get("status") == "paused":
        current = str(workflow.get("current_step") or "")
        failed = next(
            (
                item for item in by_order
                if item.get("skill_name") == current and item.get("status") in {"pending", "failed"}
            ),
            None,
        )
        failed = failed or next((item for item in by_order if item.get("status") == "pending"), None)
    if failed is None:
        return None
    return {
        "skill_name": failed.get("skill_name"),
        "display_name": failed.get("display_name"),
        "status": failed.get("status"),
        "reason": failed.get("error_message") or (
            "Execution was interrupted and can continue from this node"
            if workflow.get("status") == "paused" else "Node failed"
        ),
    }


async def get_operations_overview(
    *,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    clauses: list[str] = []
    params: list[Any] = []
    if project_id:
        clauses.append("w.project_id=?")
        params.append(project_id)
    statuses = [part.strip() for part in str(status or "").split(",") if part.strip()]
    if statuses:
        clauses.append(f"w.status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    db = await get_db()
    try:
        total_row = await (
            await db.execute(f"SELECT COUNT(*) AS value FROM workflows w {where}", params)
        ).fetchone()
        workflow_rows = await (
            await db.execute(
                "SELECT w.*, p.title AS project_title FROM workflows w "
                "LEFT JOIN research_projects p ON p.id=w.project_id "
                f"{where} ORDER BY w.updated_at DESC, w.created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
        ).fetchall()
        ids = [str(row["id"]) for row in workflow_rows]
        steps_by_workflow: dict[str, list[dict[str, Any]]] = {item: [] for item in ids}
        latest_logs: dict[str, dict[str, Any]] = {}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            step_rows = await (
                await db.execute(
                    "SELECT workflow_id, skill_name, display_name, step_order, status, output_files, "
                    "error_message, started_at, completed_at FROM workflow_steps "
                    f"WHERE workflow_id IN ({placeholders}) ORDER BY workflow_id, step_order",
                    ids,
                )
            ).fetchall()
            for row in step_rows:
                item = dict(row)
                item["output_files"] = _loads(item.get("output_files"), [])
                steps_by_workflow[str(row["workflow_id"])].append(item)
            log_rows = await (
                await db.execute(
                    "SELECT l.* FROM workflow_logs l JOIN ("
                    " SELECT workflow_id, MAX(id) AS max_id FROM workflow_logs "
                    f" WHERE workflow_id IN ({placeholders}) GROUP BY workflow_id"
                    ") latest ON latest.max_id=l.id",
                    ids,
                )
            ).fetchall()
            latest_logs = {str(row["workflow_id"]): dict(row) for row in log_rows}

        runs: list[dict[str, Any]] = []
        workspace_counts = await asyncio.gather(
            *(
                asyncio.to_thread(_workspace_artifact_count, row["workspace_dir"])
                for row in workflow_rows
            )
        )
        for row, workspace_count in zip(workflow_rows, workspace_counts):
            workflow = dict(row)
            workflow["params"] = _loads(workflow.get("params"), {})
            workflow["enable_checkpoints"] = bool(workflow.get("enable_checkpoints"))
            workflow["state"] = project_state_planes(workflow)
            steps = steps_by_workflow.get(str(row["id"]), [])
            counts = _step_counts(steps)
            completed = counts.get("completed", 0) + counts.get("skipped", 0)
            target = _recovery_target(workflow, steps)
            runs.append(
                {
                    **workflow,
                    "step_counts": counts,
                    "progress": {
                        "completed": completed,
                        "total": counts["total"],
                        "percent": round(completed * 100 / counts["total"], 1) if counts["total"] else 0.0,
                    },
                    "latest_log": latest_logs.get(str(row["id"])),
                    # The UI labels this as an artifact count, so declared but
                    # absent outputs and stale lineage records must not inflate it.
                    "artifact_count": workspace_count,
                    "recoverable": target is not None,
                    "recovery_target": target,
                }
            )
        summary = {
            "total": int(total_row["value"]),
            "pending": 0, "running": 0, "paused": 0,
            "failed": 0, "completed": 0, "recoverable": 0,
        }
        # Summary applies to the filtered result set rather than only one page.
        status_rows = await (
            await db.execute(
                f"SELECT w.status, COUNT(*) AS value FROM workflows w {where} GROUP BY w.status",
                params,
            )
        ).fetchall()
        for item in status_rows:
            summary[str(item["status"])] = int(item["value"])
        recovery_where = (
            f"{where} AND " if where else "WHERE "
        ) + (
            "((w.status='failed' AND EXISTS ("
            " SELECT 1 FROM workflow_steps s WHERE s.workflow_id=w.id AND s.status='failed'"
            ")) OR (w.status='paused' AND EXISTS ("
            " SELECT 1 FROM workflow_steps s WHERE s.workflow_id=w.id AND s.status IN ('pending','failed')"
            ")))"
        )
        recoverable_row = await (
            await db.execute(
                f"SELECT COUNT(*) AS value FROM workflows w {recovery_where}", params,
            )
        ).fetchone()
        summary["recoverable"] = int(recoverable_row["value"])
        return {
            "summary": summary,
            "runs": runs,
            "pagination": {"limit": limit, "offset": offset, "total": int(total_row["value"])},
            "generated_at": _now(),
        }
    finally:
        await db.close()


async def get_operation_detail(workflow_id: str) -> dict[str, Any] | None:
    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT w.*, p.title AS project_title FROM workflows w "
                "LEFT JOIN research_projects p ON p.id=w.project_id WHERE w.id=?",
                (workflow_id,),
            )
        ).fetchone()
        if row is None:
            return None
        workflow = dict(row)
        workflow["params"] = _loads(workflow.get("params"), {})
        workflow["enable_checkpoints"] = bool(workflow.get("enable_checkpoints"))
        workflow["state"] = project_state_planes(workflow)
        step_rows = await (
            await db.execute(
                "SELECT * FROM workflow_steps WHERE workflow_id=? ORDER BY step_order", (workflow_id,),
            )
        ).fetchall()
        steps = []
        producer_paths: list[tuple[str, str]] = []
        for step_row in step_rows:
            step = dict(step_row)
            step["output_files"] = _loads(step.get("output_files"), [])
            step["has_checkpoint"] = bool(step.get("has_checkpoint"))
            producer_paths.extend(
                (str(path).replace("\\", "/"), str(step["skill_name"]))
                for path in step["output_files"]
            )
            steps.append(step)
        workflow["steps"] = steps
        log_rows = await (
            await db.execute(
                "SELECT id, step_name, level, message, created_at FROM workflow_logs "
                "WHERE workflow_id=? ORDER BY id DESC LIMIT 1000", (workflow_id,),
            )
        ).fetchall()
        logs = [dict(item) for item in reversed(log_rows)]
        checkpoint_row = await (
            await db.execute(
                "SELECT id, workflow_id, step_name, checkpoint_type, data, status, created_at, resolved_at "
                "FROM checkpoints WHERE workflow_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                (workflow_id,),
            )
        ).fetchone()
        checkpoint = dict(checkpoint_row) if checkpoint_row else None
        if checkpoint:
            checkpoint["data"] = _loads(checkpoint.get("data"), {})
        attempt_rows = await (
            await db.execute(
                "SELECT * FROM workflow_step_attempts WHERE workflow_id=? "
                "ORDER BY started_at, attempt_number", (workflow_id,),
            )
        ).fetchall()
        attempts = []
        for attempt_row in attempt_rows:
            attempt = dict(attempt_row)
            attempt["output_files"] = _loads(attempt.get("output_files"), [])
            attempts.append(attempt)
        recovery_rows = await (
            await db.execute(
                "SELECT * FROM workflow_recovery_operations WHERE workflow_id=? "
                "ORDER BY created_at DESC", (workflow_id,),
            )
        ).fetchall()
        recoveries = [dict(item) for item in recovery_rows]
        event_rows = await (
            await db.execute(
                "SELECT id, workflow_id, project_id, event_type, payload_json, created_at "
                "FROM workflow_operation_events WHERE workflow_id=? ORDER BY id DESC LIMIT 500",
                (workflow_id,),
            )
        ).fetchall()
        events = [
            {
                "id": int(item["id"]), "workflow_id": item["workflow_id"],
                "project_id": item["project_id"], "type": item["event_type"],
                "payload": _loads(item["payload_json"], {}), "created_at": item["created_at"],
            }
            for item in reversed(event_rows)
        ]
        lineage_rows = await (
            await db.execute(
                "SELECT * FROM workflow_artifact_lineage WHERE workflow_id=? ORDER BY id",
                (workflow_id,),
            )
        ).fetchall()
        lineage = {str(item["path"]): dict(item) for item in lineage_rows if item["state"] == "current"}
    finally:
        await db.close()

    artifacts: list[dict[str, Any]] = []
    workspace = Path(str(workflow.get("workspace_dir") or ""))
    existing: set[str] = set()
    if workspace.is_dir():
        for file_path in sorted(workspace.rglob("*"), key=lambda value: value.as_posix().lower()):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(workspace)
            if not _included(relative):
                continue
            path_text = relative.as_posix()
            existing.add(path_text)
            producer = next(
                (
                    skill for declared, skill in producer_paths
                    if path_text == declared or (declared.endswith("/") and path_text.startswith(declared))
                ),
                None,
            )
            sha256 = await asyncio.to_thread(_sha256_file, file_path)
            provenance = lineage.get(path_text) or {}
            artifacts.append(
                {
                    "path": path_text, "size": file_path.stat().st_size, "sha256": sha256,
                    "producer_step": provenance.get("step_name") or producer,
                    "attempt_id": provenance.get("attempt_id"),
                    "predecessor_sha256": provenance.get("predecessor_sha256"),
                    "recorded_at": provenance.get("recorded_at"),
                    "lineage_verified": provenance.get("sha256") == sha256,
                    "exists": True,
                }
            )
    for path_text, provenance in lineage.items():
        if path_text in existing:
            continue
        artifacts.append(
            {
                "path": path_text, "size": int(provenance.get("size") or 0),
                "sha256": provenance.get("sha256"), "producer_step": provenance.get("step_name"),
                "attempt_id": provenance.get("attempt_id"),
                "predecessor_sha256": provenance.get("predecessor_sha256"),
                "recorded_at": provenance.get("recorded_at"),
                "lineage_verified": False, "exists": False,
            }
        )
    artifacts.sort(key=lambda item: str(item["path"]).lower())
    return {
        "workflow": workflow,
        "logs": logs,
        "checkpoint": checkpoint,
        "artifacts": artifacts,
        "attempts": attempts,
        "recoveries": recoveries,
        "events": events,
        "recovery_target": _recovery_target(workflow, steps),
    }


async def _set_operation_status(
    operation_id: str,
    status: str,
    *,
    error: str | None = None,
    started: bool = False,
) -> None:
    db = await get_db()
    try:
        fields = ["status=?", "error_message=?"]
        params: list[Any] = [status, error[:2000] if error else None]
        if started:
            fields.append("started_at=COALESCE(started_at, ?)")
            params.append(_now())
        if status in {"completed", "failed", "interrupted"}:
            fields.append("finished_at=?")
            params.append(_now())
        params.append(operation_id)
        await db.execute(
            f"UPDATE workflow_recovery_operations SET {', '.join(fields)} WHERE id=?", params,
        )
        await db.commit()
    finally:
        await db.close()


async def _execute_recovery_operation(
    operation: dict[str, Any],
    registry: MutableMapping[str, asyncio.Task],
) -> None:
    operation_id = str(operation["id"])
    workflow_id = str(operation["workflow_id"])
    skill_name = str(operation["skill_name"])
    mode = str(operation["mode"])
    await _set_operation_status(operation_id, "running", started=True)
    await publish_workflow_event(
        workflow_id,
        {
            "type": "recovery_started", "operation_id": operation_id,
            "step": skill_name, "mode": mode,
        },
    )
    try:
        from services.workflow_engine import run_workflow

        with recovery_invocation(operation_id, skill_name, mode):
            await run_workflow(workflow_id)
        db = await get_db()
        try:
            workflow = await (
                await db.execute("SELECT status, current_step FROM workflows WHERE id=?", (workflow_id,))
            ).fetchone()
            step = await (
                await db.execute(
                    "SELECT status, error_message FROM workflow_steps "
                    "WHERE workflow_id=? AND skill_name=? ORDER BY step_order LIMIT 1",
                    (workflow_id, skill_name),
                )
            ).fetchone()
            failed_step = await (
                await db.execute(
                    "SELECT skill_name, error_message FROM workflow_steps "
                    "WHERE workflow_id=? AND status='failed' ORDER BY step_order LIMIT 1",
                    (workflow_id,),
                )
            ).fetchone()
        finally:
            await db.close()
        workflow_status = str(workflow["status"]) if workflow else "failed"
        step_status = str(step["status"]) if step else "failed"
        if workflow_status == "failed" or step_status == "failed":
            if failed_step is not None:
                error = (
                    f"{failed_step['skill_name']}: "
                    f"{failed_step['error_message'] or 'node execution failed'}"
                )
            elif step is not None:
                error = str(step["error_message"] or "Recovery execution failed")
            else:
                error = "Workflow disappeared"
            await _set_operation_status(operation_id, "failed", error=error)
            event_type = "recovery_failed"
        elif step_status in {"completed", "skipped", "waiting_checkpoint"}:
            await _set_operation_status(operation_id, "completed")
            event_type = "recovery_completed"
            error = None
        else:
            error = f"Recovery stopped with workflow={workflow_status}, step={step_status}"
            await _set_operation_status(operation_id, "interrupted", error=error)
            event_type = "recovery_interrupted"
        await publish_workflow_event(
            workflow_id,
            {
                "type": event_type, "operation_id": operation_id, "step": skill_name,
                "workflow_status": workflow_status, "step_status": step_status,
                **({"error": error} if error else {}),
            },
        )
    except asyncio.CancelledError:
        await _set_operation_status(operation_id, "interrupted", error="Recovery task was interrupted")
        await publish_workflow_event(
            workflow_id,
            {
                "type": "recovery_interrupted", "operation_id": operation_id,
                "step": skill_name, "error": "Recovery task was interrupted",
            },
        )
        raise
    except Exception as exc:
        await _set_operation_status(operation_id, "failed", error=str(exc))
        await publish_workflow_event(
            workflow_id,
            {
                "type": "recovery_failed", "operation_id": operation_id,
                "step": skill_name, "error": str(exc),
            },
        )
        log.exception("Recovery operation %s failed", operation_id)


def _schedule_operation(
    operation: dict[str, Any],
    registry: MutableMapping[str, asyncio.Task],
) -> asyncio.Task:
    key = f"{operation['workflow_id']}_recovery_{operation['id']}"
    task = asyncio.create_task(_execute_recovery_operation(operation, registry))
    registry[key] = task

    def cleanup(done: asyncio.Task) -> None:
        if registry.get(key) is done:
            registry.pop(key, None)

    task.add_done_callback(cleanup)
    return task


def _has_active_task(registry: MutableMapping[str, asyncio.Task], workflow_id: str) -> bool:
    return any(
        (key == workflow_id or key.startswith(f"{workflow_id}_")) and not task.done()
        for key, task in list(registry.items())
    )


async def request_step_recovery(
    workflow_id: str,
    skill_name: str | None,
    *,
    mode: str,
    reason: str,
    requested_by: str,
    registry: MutableMapping[str, asyncio.Task],
) -> dict[str, Any]:
    """Persist and schedule a real failed-node continuation.

    Raises ``LookupError`` for missing records and ``ValueError`` for an
    invalid transition; the HTTP adapter maps those to explicit 404/409
    responses rather than pretending the operation was accepted.
    """
    if _has_active_task(registry, workflow_id):
        raise ValueError("Workflow already has an active executor")
    db = await get_db()
    try:
        workflow_row = await (
            await db.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,))
        ).fetchone()
        if workflow_row is None:
            raise LookupError("Workflow not found")
        workflow = dict(workflow_row)
        step_rows = await (
            await db.execute(
                "SELECT * FROM workflow_steps WHERE workflow_id=? ORDER BY step_order", (workflow_id,),
            )
        ).fetchall()
        steps = [dict(item) for item in step_rows]
        if skill_name is None:
            target = _recovery_target(workflow, steps)
            if target is None:
                raise ValueError("Workflow has no failed or interrupted node to recover")
            skill_name = str(target["skill_name"])
        step = next((item for item in steps if item["skill_name"] == skill_name), None)
        if step is None:
            raise LookupError("Workflow step not found")
        if step["status"] not in {"failed", "pending"} or workflow["status"] not in {"failed", "paused"}:
            raise ValueError(
                f"Only a failed/interrupted node can be recovered (workflow={workflow['status']}, step={step['status']})"
            )

        operation_id = uuid.uuid4().hex
        created_at = _now()
        await db.execute("BEGIN IMMEDIATE")
        active_operation = await (
            await db.execute(
                "SELECT id FROM workflow_recovery_operations WHERE workflow_id=? "
                "AND status IN ('accepted','running') ORDER BY created_at DESC LIMIT 1",
                (workflow_id,),
            )
        ).fetchone()
        if active_operation is not None:
            raise ValueError("Workflow already has an accepted recovery operation")
        await db.execute(
            "UPDATE workflow_recovery_operations SET status='superseded', finished_at=? "
            "WHERE workflow_id=? AND status='interrupted'",
            (created_at, workflow_id),
        )
        await db.execute(
            "UPDATE workflow_steps SET status='pending', error_message=NULL, started_at=NULL, "
            "completed_at=NULL WHERE workflow_id=? AND skill_name=?",
            (workflow_id, skill_name),
        )
        await db.execute(
            "UPDATE workflows SET status='paused', current_step=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (skill_name, workflow_id),
        )
        await db.execute(
            "INSERT INTO workflow_recovery_operations "
            "(id, workflow_id, skill_name, mode, status, reason, requested_by, created_at) "
            "VALUES (?,?,?,?, 'accepted', ?,?,?)",
            (
                operation_id, workflow_id, skill_name, mode,
                reason.strip() or "Retry failed workflow node", requested_by.strip() or "operator", created_at,
            ),
        )
        await db.commit()
    finally:
        await db.close()

    operation = {
        "id": operation_id, "workflow_id": workflow_id, "skill_name": skill_name,
        "mode": mode, "status": "accepted",
    }
    await publish_workflow_event(
        workflow_id,
        {
            "type": "recovery_requested", "operation_id": operation_id,
            "step": skill_name, "mode": mode,
            "reason": reason.strip() or "Retry failed workflow node",
            "requested_by": requested_by.strip() or "operator",
        },
    )
    _schedule_operation(operation, registry)
    return operation


async def resume_interrupted_operations(
    registry: MutableMapping[str, asyncio.Task],
) -> list[str]:
    """Resume the newest interrupted recovery per workflow after a restart."""
    db = await get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT r.* FROM workflow_recovery_operations r JOIN ("
                " SELECT workflow_id, MAX(created_at) AS newest FROM workflow_recovery_operations "
                " WHERE status='interrupted' GROUP BY workflow_id"
                ") x ON x.workflow_id=r.workflow_id AND x.newest=r.created_at "
                "ORDER BY r.created_at"
            )
        ).fetchall()
        operations = [dict(item) for item in rows]
        resumed: list[dict[str, Any]] = []
        for operation in operations:
            workflow_id = str(operation["workflow_id"])
            if _has_active_task(registry, workflow_id):
                continue
            workflow = await (
                await db.execute("SELECT status FROM workflows WHERE id=?", (workflow_id,))
            ).fetchone()
            if workflow is None:
                continue
            incomplete = await (
                await db.execute(
                    "SELECT COUNT(*) AS value FROM workflow_steps WHERE workflow_id=? "
                    "AND status NOT IN ('completed','skipped')",
                    (workflow_id,),
                )
            ).fetchone()
            incomplete_count = int(incomplete["value"])
            if workflow["status"] == "completed" and incomplete_count == 0:
                # The process can terminate after the engine's terminal write
                # but before the operation wrapper seals its own row.
                await db.execute(
                    "UPDATE workflow_recovery_operations SET status='completed', "
                    "error_message=NULL, finished_at=? WHERE id=?",
                    (_now(), operation["id"]),
                )
                continue
            if workflow["status"] == "completed" and incomplete_count:
                # run_single_step commits intermediate success; if a crash
                # lands between nodes the remaining DAG still needs recovery.
                await db.execute(
                    "UPDATE workflows SET status='paused', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (workflow_id,),
                )
            elif workflow["status"] not in {"paused", "failed"}:
                continue
            await db.execute(
                "UPDATE workflow_recovery_operations SET status='accepted', finished_at=NULL, "
                "error_message=NULL, resume_count=resume_count+1 WHERE id=?",
                (operation["id"],),
            )
            operation["status"] = "accepted"
            resumed.append(operation)
        await db.commit()
    finally:
        await db.close()

    for operation in resumed:
        _schedule_operation(operation, registry)
    return [str(item["id"]) for item in resumed]
