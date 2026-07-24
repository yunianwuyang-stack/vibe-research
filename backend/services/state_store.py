"""SQLite 状态持久化"""
from __future__ import annotations

import asyncio
import json
import logging
import platform as _platform
import shutil as _shutil
import subprocess as _subprocess
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiosqlite

from config import DB_PATH

try:
    del annotations
except NameError:
    pass

log = logging.getLogger(__name__)

_schema_path = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
_workflows_to_resume: list[str] = []
# Serialize in-process writers. SQLite WAL allows concurrent readers, but many
# long-lived writer connections still collapse into "database is locked" under
# matrix-scale workflow runs. One asyncio lock keeps commits ordered without
# changing the public state-store ABI. ContextVar depth makes the lock re-entrant
# for nested helpers such as update_workflow() inside a write worker.
#
# The lock is recreated per event loop so pytest/TestClient restarts do not keep
# a lock bound to a closed loop.
_write_lock: asyncio.Lock | None = None
_write_lock_loop: asyncio.AbstractEventLoop | None = None
_write_lock_depth: ContextVar[int] = ContextVar("state_store_write_lock_depth", default=0)
_MAX_WRITE_ATTEMPTS = 8
_AUTO_RESUME_LIMIT = 4


def _get_write_lock() -> asyncio.Lock:
    global _write_lock, _write_lock_loop
    loop = asyncio.get_running_loop()
    if _write_lock is None or _write_lock_loop is not loop:
        _write_lock = asyncio.Lock()
        _write_lock_loop = loop
    return _write_lock


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=30000")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA temp_store=MEMORY")
    return db


async def _get_db() -> aiosqlite.Connection:
    """Compatibility alias used by reconstructed routers and services."""
    return await get_db()


def _is_locked_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "locked" in text or "busy" in text


@asynccontextmanager
async def _writer_section():
    depth = _write_lock_depth.get()
    lock = _get_write_lock()
    if depth == 0:
        await lock.acquire()
    token = _write_lock_depth.set(depth + 1)
    try:
        yield
    finally:
        _write_lock_depth.reset(token)
        if depth == 0:
            lock.release()


async def run_with_db_retry(operation_name: str, worker):
    """Retry a short DB critical section while the writer lock is held."""
    last_error: BaseException | None = None
    for attempt in range(_MAX_WRITE_ATTEMPTS):
        try:
            async with _writer_section():
                return await worker()
        except aiosqlite.OperationalError as exc:
            last_error = exc
            if not _is_locked_error(exc) or attempt == _MAX_WRITE_ATTEMPTS - 1:
                raise
            delay = min(2 ** attempt, 8)
            log.warning(
                "DB locked during %s (attempt %d/%d), retrying in %ss...",
                operation_name,
                attempt + 1,
                _MAX_WRITE_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


def _startup_cleanup():
    """清理 _pending_cleanup.txt 中记录的残留工作区"""
    try:
        from config import WORKSPACES_DIR

        cleanup_file = WORKSPACES_DIR / "_pending_cleanup.txt"
        if not cleanup_file.exists():
            return
        paths = cleanup_file.read_text(encoding="utf-8").strip().splitlines()
        cleaned = 0
        for path in paths:
            candidate = Path(path.strip())
            if candidate.is_dir():
                _shutil.rmtree(candidate, ignore_errors=True)
                cleaned += 1
        cleanup_file.unlink()
        if cleaned:
            log.info("Startup cleanup: removed %d leftover workspaces", cleaned)
    except Exception as exc:
        log.warning("Startup cleanup failed: %s", exc)


async def init_db():
    db = await get_db()
    try:
        schema = _schema_path.read_text(encoding="utf-8")
        await db.executescript(schema)
        # Schema evolution is owned by the forward-only migration runner.
        # New installs get lease columns from schema.sql; existing DBs receive
        # them exactly once via PRODUCT_MIGRATIONS (no ad-hoc schema mutation here).
        try:
            from infrastructure.persistence.migrations import MigrationRunner, PRODUCT_MIGRATIONS
            MigrationRunner(Path(DB_PATH), PRODUCT_MIGRATIONS).migrate()
        except Exception as exc:
            log.warning("PRODUCT_MIGRATIONS apply failed: %s", exc)

        # Schema evolution is owned by the forward-only migration runner.
        # Older desktop builds accepted project_id from the UI but discarded
        # it before persistence. Recover the closest matching project from the
        # workflow title/research question so existing tasks remain visible.
        cursor = await db.execute(
            "SELECT id, title, params, created_at FROM workflows WHERE project_id IS NULL"
        )
        try:
            legacy_workflows = await cursor.fetchall()
        finally:
            await cursor.close()
        for workflow in legacy_workflows:
            try:
                question = str(json.loads(workflow["params"] or "{}").get("research_question") or "").strip()
            except (TypeError, json.JSONDecodeError):
                question = ""
            if question:
                project_cursor = await db.execute(
                    "SELECT id FROM research_projects WHERE research_question=? "
                    "ORDER BY ABS(julianday(created_at)-julianday(?)), created_at DESC LIMIT 1",
                    (question, workflow["created_at"]),
                )
                try:
                    project = await project_cursor.fetchone()
                finally:
                    await project_cursor.close()
            else:
                project = None
            if project is None:
                project_cursor = await db.execute(
                    "SELECT id FROM research_projects WHERE title=? "
                    "ORDER BY ABS(julianday(created_at)-julianday(?)), created_at DESC LIMIT 1",
                    (workflow["title"], workflow["created_at"]),
                )
                try:
                    project = await project_cursor.fetchone()
                finally:
                    await project_cursor.close()
            if project is not None:
                await db.execute(
                    "UPDATE workflows SET project_id=? WHERE id=?",
                    (project["id"], workflow["id"]),
                )

        # Never kill processes by image name: only owned ProcessSupervisor children may be cancelled.

        await db.execute("UPDATE workflows SET status='paused', updated_at=CURRENT_TIMESTAMP WHERE status='running'")
        await db.execute("UPDATE workflow_steps SET status='pending', error_message=NULL WHERE status='running'")
        await db.execute(
            "UPDATE workflow_step_attempts SET status='interrupted', "
            "error_message=COALESCE(error_message, 'Application restarted during node execution'), "
            "finished_at=COALESCE(finished_at, CURRENT_TIMESTAMP) WHERE status='running'"
        )
        await db.execute(
            "UPDATE workflow_recovery_operations SET status='interrupted', "
            "error_message=COALESCE(error_message, 'Application restarted during recovery'), "
            "finished_at=COALESCE(finished_at, CURRENT_TIMESTAMP) "
            "WHERE status IN ('accepted','running')"
        )
        # Research runs are never silently resumed after a process crash.
        # Persisted runs return to paused and require an explicit human/API resume.
        await db.execute("UPDATE research_runs SET status='paused', updated_at=CURRENT_TIMESTAMP WHERE status='running'")
        await db.execute("UPDATE adversarial_reviews SET status='interrupted', verdict='error', failure_reason='Application restarted while adversarial review was running', updated_at=CURRENT_TIMESTAMP WHERE status='running'")
        await db.commit()

        # Auto-resume only the most recently interrupted workflows. Matrix-scale
        # restarts previously rehydrated dozens of runs at once, which recreated
        # the SQLite lock storm that failed nature-figure and similar steps.
        cursor = await db.execute(
            "SELECT id FROM workflows WHERE status='paused' "
            "AND updated_at > datetime('now', '-1 hour') "
            "ORDER BY updated_at DESC, created_at DESC"
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        global _workflows_to_resume
        all_resume_ids = [row["id"] for row in rows]
        _workflows_to_resume = all_resume_ids[:_AUTO_RESUME_LIMIT]
        if all_resume_ids:
            log.info(
                "Found %d interrupted workflows after restart; auto-resuming %d: %s%s",
                len(all_resume_ids),
                len(_workflows_to_resume),
                _workflows_to_resume,
                (
                    f"; deferred={all_resume_ids[_AUTO_RESUME_LIMIT:]}"
                    if len(all_resume_ids) > _AUTO_RESUME_LIMIT
                    else ""
                ),
            )
    finally:
        await db.close()

    _startup_cleanup()


async def create_workflow(db: aiosqlite.Connection, wf: dict) -> None:
    await db.execute(
        "INSERT INTO workflows (id, project_id, template, title, params, status, workspace_dir, enable_checkpoints) VALUES (?,?,?,?,?,?,?,?)",
        (
            wf["id"],
            wf.get("project_id"),
            wf["template"],
            wf["title"],
            json.dumps(wf.get("params", {})),
            wf.get("status", "pending"),
            wf.get("workspace_dir", ""),
            int(wf.get("enable_checkpoints", 0)),
        ),
    )
    await db.commit()


async def update_workflow(db: aiosqlite.Connection, wf_id: str, **fields) -> None:
    """更新工作流字段，带重试逻辑应对并发锁竞争。"""
    sets = ", ".join(f"{key}=?" for key in fields)
    values = list(fields.values())
    values.append(wf_id)
    sql = f"UPDATE workflows SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?"

    # Keep the recovered 3-attempt ABI for update_workflow while still serializing
    # writers so matrix-scale runs stop thrashing SQLite.
    for attempt in range(3):
        try:
            async with _writer_section():
                await db.execute(sql, values)
                await db.commit()
            return
        except aiosqlite.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 2:
                raise
            log.warning(
                "DB locked updating workflow %s (attempt %d/3), retrying...",
                wf_id,
                attempt + 1,
            )
            await asyncio.sleep(2**attempt)


async def get_workflow(db: aiosqlite.Connection, wf_id: str) -> Optional[Dict]:
    cursor = await db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,))
    row = await cursor.fetchone()
    if row:
        result = dict(row)
        result["params"] = json.loads(result["params"])
        return result
    return None


async def list_workflows(db: aiosqlite.Connection, project_id: str | None = None) -> list[dict]:
    if project_id:
        cursor = await db.execute(
            "SELECT * FROM workflows WHERE project_id=? OR project_id IS NULL ORDER BY created_at DESC",
            (project_id,),
        )
    else:
        cursor = await db.execute("SELECT * FROM workflows ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["params"] = json.loads(item["params"])
        result.append(item)
    return result


async def add_log(wf_id: str, step_name: str | None, level: str, message: str) -> None:
    """Persist a workflow log for reconstructed workflow-engine callers."""

    async def _write() -> None:
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO workflow_logs (workflow_id, step_name, level, message) VALUES (?, ?, ?, ?)",
                (wf_id, step_name, level, message),
            )
            await db.commit()
        finally:
            await db.close()

    await run_with_db_retry(f"add_log:{wf_id}", _write)


async def execute_write(operation_name: str, worker) -> None:
    """Run an open-connection write worker under the shared lock/retry policy."""
    await run_with_db_retry(operation_name, worker)


async def get_logs(wf_id: str, limit: int = 500) -> list[dict]:
    """Return chronological logs for reconstructed callers."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM workflow_logs WHERE workflow_id = ? ORDER BY id DESC LIMIT ?",
            (wf_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]
    finally:
        await db.close()


async def _heal_secret_marker(db: aiosqlite.Connection, key: str) -> None:
    """Clear a stale configured marker when the secret store no longer holds the key.

    Older builds could leave SQLite with ``__secret_configured__`` after the
    encrypted secret file was deleted, rotated, or only partially written. The
    UI would then claim a key existed while every live call failed with
    "未配置 API 密钥". Heal the marker on read so metadata and runtime agree.
    """
    await db.execute(
        "UPDATE settings SET value='', updated_at=CURRENT_TIMESTAMP WHERE key=? AND value=?",
        (key, "__secret_configured__"),
    )
    await db.commit()


async def get_all_settings() -> Dict[str, str]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        values = {row["key"]: row["value"] for row in rows}
        from services.secret_store import SECRET_KEYS, get_secret_store
        store = get_secret_store()
        for key in SECRET_KEYS:
            if values.get(key) != "__secret_configured__":
                continue
            secret = store.get(key)
            if secret:
                values[key] = secret
            else:
                values[key] = ""
                await _heal_secret_marker(db, key)
        return values
    finally:
        await db.close()


async def save_settings(data: Dict[str, str]) -> None:
    db = await get_db()
    try:
        from services.secret_store import SECRET_KEYS, get_secret_store
        store = get_secret_store()
        for key, value in data.items():
            if key in SECRET_KEYS:
                if value:
                    store.set(key, value)
                    value = "__secret_configured__"
                else:
                    store.clear(key)
            await db.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (key, value),
            )
        await db.commit()
    finally:
        await db.close()


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cursor.fetchone()
        value = row["value"] if row else default
        if value == "__secret_configured__":
            from services.secret_store import get_secret_store
            secret = get_secret_store().get(key)
            if secret:
                return secret
            await _heal_secret_marker(db, key)
            return default
        return value
    finally:
        await db.close()


async def get_settings_metadata() -> Dict[str, Dict[str, object]]:
    """Return user-visible settings without ever serializing a secret value."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        from services.secret_store import SECRET_KEYS, get_secret_store
        store = get_secret_store()
        result: Dict[str, Dict[str, object]] = {}
        for row in rows:
            key = row["key"]
            value = row["value"]
            if value == "__secret_configured__":
                # Only report configured when the secret store can actually
                # decrypt a non-empty value. Stale markers are healed so the
                # next read and the model-profile UI stay consistent.
                if key in SECRET_KEYS and store.get(key):
                    result[key] = {"configured": True}
                else:
                    if key in SECRET_KEYS:
                        await _heal_secret_marker(db, key)
                    result[key] = {"configured": False, "value": ""}
            else:
                result[key] = {"value": value}
        return result
    finally:
        await db.close()


def get_workflows_to_resume() -> list[str]:
    """返回需要恢复的工作流 ID 列表，调用后清空。"""
    result = list(_workflows_to_resume)
    _workflows_to_resume.clear()
    return result


async def export_workflow_data(wf_id: str) -> Optional[Dict]:
    """导出工作流的完整 DB 数据（workflow + steps + logs），返回 dict 或 None。"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,))
        wf_row = await cursor.fetchone()
        if not wf_row:
            return None

        cursor = await db.execute(
            "SELECT skill_name, display_name, step_order, status, has_checkpoint, checkpoint_type, "
            "output_files, started_at, completed_at, error_message FROM workflow_steps "
            "WHERE workflow_id=? ORDER BY step_order",
            (wf_id,),
        )
        steps = []
        for row in await cursor.fetchall():
            step = dict(row)
            step["has_checkpoint"] = bool(step["has_checkpoint"])
            step["output_files"] = json.loads(step["output_files"])
            steps.append(step)

        cursor = await db.execute(
            "SELECT step_name, level, message, created_at FROM workflow_logs "
            "WHERE workflow_id=? ORDER BY id DESC LIMIT 2000",
            (wf_id,),
        )
        log_rows = await cursor.fetchall()
        logs = [dict(row) for row in reversed(log_rows)]

        workflow = {
            "id": wf_row["id"],
            "template": wf_row["template"],
            "title": wf_row["title"],
            "params": json.loads(wf_row["params"]),
            "status": wf_row["status"],
            "current_step": wf_row["current_step"],
            "enable_checkpoints": wf_row["enable_checkpoints"],
            "created_at": wf_row["created_at"],
            "updated_at": wf_row["updated_at"],
        }
        return {"workflow": workflow, "steps": steps, "logs": logs}
    finally:
        await db.close()


async def import_workflow_data(data: Dict, new_id: str, workspace_dir: str) -> None:
    """从导出的 manifest 数据导入工作流到 DB。"""
    db = await get_db()
    try:
        workflow = data["workflow"]
        await db.execute(
            "INSERT INTO workflows (id, template, title, params, status, current_step, workspace_dir, "
            "enable_checkpoints, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            (
                new_id,
                workflow["template"],
                workflow["title"],
                json.dumps(workflow.get("params", {})),
                workflow.get("status", "completed"),
                workflow.get("current_step"),
                workspace_dir,
                int(workflow.get("enable_checkpoints", 0)),
                workflow.get("created_at", datetime.now().isoformat()),
            ),
        )

        for step in data.get("steps", []):
            await db.execute(
                "INSERT INTO workflow_steps (workflow_id, skill_name, display_name, step_order, status, "
                "has_checkpoint, checkpoint_type, output_files, started_at, completed_at, error_message) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    step["skill_name"],
                    step["display_name"],
                    step["step_order"],
                    step.get("status", "completed"),
                    int(step.get("has_checkpoint", 0)),
                    step.get("checkpoint_type"),
                    json.dumps(step.get("output_files", [])),
                    step.get("started_at"),
                    step.get("completed_at"),
                    step.get("error_message"),
                ),
            )

        for entry in data.get("logs", []):
            await db.execute(
                "INSERT INTO workflow_logs (workflow_id, step_name, level, message, created_at) VALUES (?,?,?,?,?)",
                (
                    new_id,
                    entry.get("step_name", ""),
                    entry.get("level", "info"),
                    entry["message"],
                    entry.get("created_at"),
                ),
            )

        await db.commit()
    finally:
        await db.close()
