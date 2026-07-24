"""(docstring)"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel

from config import WORKSPACES_DIR
from models.schemas import WorkflowCreate, WorkflowInfo
from services.workflow_engine import TEMPLATES, run_workflow, run_single_step
from services.workspace_paths import WorkspacePathError, resolve_workflow_workspace

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])


_tasks: Dict[str, asyncio.Task] = {}

_REQUIRED_INPUT_MESSAGES = {
    "paper_from_assets": "请先上传“题目 / 写作要求”文件。",
    "paper_slides": "请先上传已编译论文（paper/main.tex 或 main.pdf，以及 figures/）。",
    "paper_poster": "请先上传已编译论文（paper/main.tex 或 main.pdf，以及 figures/）。",
    "software_copyright": "请先上传源代码、界面截图或现有产品材料。",
}

_EXPORT_SKIP_DIRS = {"_sandbox", "node_modules", "__pycache__", "_templates", "_editor_backup", ".git", "_tmp"}
# Durable lineage/audit directories must travel with exports so dual-clean
# recovery and offline review keep claim/image/script evidence hashes.
_EXPORT_LINEAGE_DIRS = {
    ".image_audits",
    ".editor_runs",
    ".editor_compile",
    ".drawio_exports",
    ".mermaid_exports",
    ".image_generation",
    ".host_builds",
    ".docx_exports",
}
_EXPORT_SKIP_EXTS = {
    ".synctex.gz", ".fls", ".log", ".nav", ".toc", ".vrb", ".fdb_latexmk",
    ".out", ".aux", ".pyc", ".lot", ".snm", ".blg", ".bbl", ".lof", ".xdv",
}


async def _cancel_workflow_tasks(wf_id: str) -> None:
    """Stop orchestration tasks and every executor process for one workflow.

    A workflow can own the main task plus reruns/retries whose registry keys
    are prefixed with its id.  Awaiting their cancellation before mutating the
    database or deleting the workspace prevents a late runner from writing
    back into a reset/deleted workflow.
    """
    matches = [
        (key, task)
        for key, task in list(_tasks.items())
        if key == wf_id or key.startswith(f"{wf_id}_")
    ]
    for _, task in matches:
        if not task.done():
            task.cancel()

    from services.claude_runner import cancel_workflow_execution

    await cancel_workflow_execution(wf_id)
    pending = []
    for _, task in matches:
        if not isinstance(task, asyncio.Future):
            continue
        try:
            # Skip futures bound to a closed/foreign loop (TestClient restarts).
            if task.get_loop().is_closed():
                continue
        except Exception:
            continue
        pending.append(task)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for key, task in matches:
        if _tasks.get(key) is task:
            _tasks.pop(key, None)
_EXPORT_SKIP_NAMES = {"_created_files.json", "CLAUDE.md"}


class _BatchExportRequest(BaseModel):
    ids: List[str]


class _RecoveryRequest(BaseModel):
    reason: str = ""
    requested_by: str = "operator"


def _should_include_file(rel: Path) -> bool:
    """Return whether a workspace-relative file belongs in an export."""
    if any(part in _EXPORT_SKIP_DIRS for part in rel.parts):
        return False
    for part in rel.parts:
        if part.startswith(".") and part not in _EXPORT_LINEAGE_DIRS:
            return False
    if rel.name in _EXPORT_SKIP_NAMES:
        return False
    return rel.suffix.lower() not in _EXPORT_SKIP_EXTS


def _write_export_entries(zf: zipfile.ZipFile, prefix: str, workspace: Path | None, manifest: dict) -> None:
    manifest_name = f"{prefix}manifest.json"
    zf.writestr(manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2))
    if not workspace or not workspace.exists():
        return
    for item in sorted(workspace.rglob("*"), key=lambda path: path.as_posix().lower()):
        if not item.is_file():
            continue
        rel = item.relative_to(workspace)
        if _should_include_file(rel):
            zf.write(item, f"{prefix}workspace/{rel.as_posix()}")


def _build_export_zip(zip_path: str, wf_id: str, workspace: Path | None, manifest: dict):
    """Build one workflow export synchronously for use in a worker thread."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_export_entries(zf, "", workspace, manifest)


def _safe_name(value: str, fallback: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in "_-")
    return cleaned[:80] or fallback


def _temporary_zip_path() -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    path = handle.name
    handle.close()
    return path


@router.post("")
async def create(body: WorkflowCreate):
    """(docstring)"""
    from services.workflow_engine import create_new_workflow
    from services.workflow_options import ALIASES, normalize_workflow_params, _canonical_paper_template

    raw_template = ALIASES.get(body.template.value, body.template.value)
    template = _canonical_paper_template(raw_template, body.params)
    normalized_params = normalize_workflow_params(raw_template, body.params)
    wf_id = await create_new_workflow(
        template=template,
        title=body.title,
        params=normalized_params,
        enable_checkpoints=body.enable_checkpoints,
        project_id=body.project_id,
    )
    return {"id": wf_id, "ok": True, "template": template}


@router.get("/catalog")
async def get_catalog():
    """Return the complete workflow option/default contract used by the UI."""
    from services.workflow_options import catalog
    return catalog()


@router.get("")
async def list_all(project_id: str | None = None):
    """(docstring)"""
    from services.state_store import _get_db, list_workflows
    db = await _get_db()
    try:
        return await list_workflows(db, project_id)
    finally:
        await db.close()


@router.get("/operations")
async def get_operations(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Aggregate persisted workflow runs across research projects."""
    from services.workflow_operations import get_operations_overview

    return await get_operations_overview(
        project_id=project_id, status=status, limit=limit, offset=offset,
    )


@router.get("/operations/events")
async def operation_events(
    request: Request,
    after_id: int = 0,
    project_id: str | None = None,
    workflow_id: str | None = None,
    once: bool = False,
):
    """Replay and tail the durable global workflow event stream via SSE."""
    from services.workflow_operations import stream_events

    if after_id <= 0:
        try:
            after_id = int(request.headers.get("last-event-id") or 0)
        except ValueError:
            after_id = 0
    return StreamingResponse(
        stream_events(
            request,
            after_id=after_id,
            project_id=project_id,
            workflow_id=workflow_id,
            one_shot=once,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/operations/{wf_id}")
async def get_operation(wf_id: str):
    """Return one run with attempts, logs, checkpoints and artifact lineage."""
    from services.workflow_operations import get_operation_detail

    detail = await get_operation_detail(wf_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return detail


def _workflow_response(row: object) -> dict:
    workflow = dict(row)
    workflow["params"] = json.loads(workflow.get("params") or "{}")
    workflow["enable_checkpoints"] = bool(workflow.get("enable_checkpoints"))
    return workflow


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extracted_input_paths(status: dict) -> set[str]:
    paths: set[str] = set()
    for source, item in status.get("files", {}).items():
        paths.add(f"{str(source).replace(chr(92), '/')}.txt")
        text_file = item.get("text_file")
        if text_file:
            paths.add(str(text_file).replace("\\", "/"))
    return paths


def _workflow_workspace_path(wf_id: str, workspace_dir: str | None = None) -> Path:
    """Resolve the on-disk workspace for a workflow.

    Prefer the persisted ``workspace_dir`` so API validation, export and engine
    execution stay aligned even when tests or custom roots rebind WORKSPACES_DIR.
    """
    if workspace_dir:
        candidate = Path(str(workspace_dir)).expanduser()
        if candidate.is_absolute() or candidate.exists():
            return candidate.resolve(strict=False)
    try:
        return resolve_workflow_workspace(wf_id, fallback_root=Path(WORKSPACES_DIR))
    except WorkspacePathError:
        return (Path(WORKSPACES_DIR) / wf_id).resolve(strict=False)


async def _validate_start_inputs(wf_id: str) -> None:
    """Keep the start contract enforceable for API clients as well as the UI."""
    from services.state_store import _get_db

    db = await _get_db()
    try:
        row = await (
            await db.execute(
                "SELECT template, params, workspace_dir FROM workflows WHERE id=?",
                (wf_id,),
            )
        ).fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    template = str(row["template"])
    try:
        params = json.loads(row["params"] or "{}") if isinstance(row["params"], str) else dict(row["params"] or {})
    except (TypeError, ValueError):
        params = {}
    message = _REQUIRED_INPUT_MESSAGES.get(template)
    if template.startswith("comp_") and template != "comp_stats" and params.get("require_competition_input", True):
        message = "请上传赛题文件，或在赛题补充说明中填写赛题内容。"
        if str(params.get("problem_statement") or "").strip():
            return
    if not message:
        return
    workspace = _workflow_workspace_path(wf_id, row["workspace_dir"] if "workspace_dir" in row.keys() else None)
    root = workspace / "user_data"
    status_path = root / "_extract_status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"files": {}}
    except (OSError, ValueError):
        status = {"files": {}}
    extracted_names = _extracted_input_paths(status)
    has_input = root.is_dir() and any(
        path.is_file()
        and path.name not in {"_extract_status.json", "_input_manifest.json"}
        and str(path.relative_to(root)).replace(os.sep, "/") not in extracted_names
        for path in root.rglob("*")
    )
    manifest_path = root / "_input_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except (OSError, ValueError):
        manifest = {}
    roles = {
        str(item.get("role") or "material")
        for item in manifest.get("files", {}).values()
        if isinstance(item, dict)
    }
    needs_declared_role = (
        template in {"paper_from_assets", "paper_slides", "paper_poster"}
        or (template.startswith("comp_") and template != "comp_stats")
    )
    if template == "paper_from_assets":
        required_role = "requirements"
    elif template in {"paper_slides", "paper_poster"}:
        required_role = "paper"
    else:
        required_role = "problem"
    # Templates that require a declared role must not soft-accept bare files when
    # the manifest is empty or wiped. Competition templates still accept any input
    # file when the operator has not assigned roles yet (legacy uploads).
    if roles:
        has_required_role = required_role in roles
    elif template in {"paper_from_assets", "paper_slides", "paper_poster"}:
        has_required_role = False
    else:
        has_required_role = has_input

    # Communication templates can be seeded with an already-compiled paper in the
    # workspace root (paper/main.tex or paper/main.pdf), not only via user_data
    # uploads. Accept either path so host/API clients match the desktop UI.
    if template in {"paper_slides", "paper_poster"}:
        paper_dir = workspace / "paper"
        has_compiled_paper = any(
            (paper_dir / name).is_file() and (paper_dir / name).stat().st_size > 0
            for name in ("main.tex", "main.pdf")
        )
        if has_compiled_paper or has_required_role:
            return

    if not has_input or (needs_declared_role and not has_required_role):
        raise HTTPException(status_code=400, detail=message)


@router.get("/{wf_id}/run-center")
async def get_run_center(wf_id: str):
    """Return the single persisted snapshot consumed by the run-center UI."""
    from services.state_store import _get_db

    db = await _get_db()
    try:
        workflow_row = await (
            await db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,))
        ).fetchone()
        if not workflow_row:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow = _workflow_response(workflow_row)
        step_rows = await (
            await db.execute(
                "SELECT skill_name, display_name, step_order, status, has_checkpoint, checkpoint_type, "
                "output_files, started_at, completed_at, error_message "
                "FROM workflow_steps WHERE workflow_id=? ORDER BY step_order",
                (wf_id,),
            )
        ).fetchall()
        steps = []
        producer_steps: list[tuple[str, str]] = []
        for row in step_rows:
            step = dict(row)
            step["output_files"] = json.loads(step.get("output_files") or "[]")
            step["has_checkpoint"] = bool(step["has_checkpoint"])
            steps.append(step)
            producer_steps.extend((str(output).replace("\\", "/"), step["skill_name"]) for output in step["output_files"])
        workflow["steps"] = steps

        log_rows = await (
            await db.execute(
                "SELECT id, step_name, level, message, created_at FROM workflow_logs "
                "WHERE workflow_id=? ORDER BY id DESC LIMIT 500",
                (wf_id,),
            )
        ).fetchall()
        logs = [dict(row) for row in reversed(log_rows)]

        checkpoint_row = await (
            await db.execute(
                "SELECT id, workflow_id, step_name, checkpoint_type, data, status, created_at, resolved_at "
                "FROM checkpoints WHERE workflow_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                (wf_id,),
            )
        ).fetchone()
        checkpoint = dict(checkpoint_row) if checkpoint_row else None
        if checkpoint is not None:
            checkpoint["data"] = json.loads(checkpoint.get("data") or "{}")

        workspace = _workflow_workspace_path(wf_id, workflow.get("workspace_dir"))
        artifacts = []
        if workspace.is_dir():
            for file_path in sorted(workspace.rglob("*"), key=lambda path: path.as_posix().lower()):
                if not file_path.is_file():
                    continue
                relative_path = file_path.relative_to(workspace)
                if not _should_include_file(relative_path):
                    continue
                path_text = relative_path.as_posix()
                producer_step = next(
                    (
                        skill_name
                        for declared_path, skill_name in producer_steps
                        if path_text == declared_path
                        or (declared_path.endswith("/") and path_text.startswith(declared_path))
                    ),
                    None,
                )
                artifacts.append(
                    {
                        "path": path_text,
                        "size": file_path.stat().st_size,
                        "sha256": _sha256_file(file_path),
                        "producer_step": producer_step,
                    }
                )

        return {"workflow": workflow, "logs": logs, "checkpoint": checkpoint, "artifacts": artifacts}
    finally:
        await db.close()


@router.get("/{wf_id}")
async def get_one(wf_id: str):
    """(docstring)"""
    from services.state_store import _get_db, get_workflow
    db = await _get_db()
    try:
        workflow_row = await (await db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,))).fetchone()
        if not workflow_row:
            raise HTTPException(status_code=404, detail="Workflow not found")
        wf = _workflow_response(workflow_row)

        cursor = await db.execute("SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY step_order", (wf_id,))
        steps = [dict(r) for r in await cursor.fetchall()]
        for s in steps:
            s["output_files"] = json.loads(s.get("output_files", "[]"))
            s["has_checkpoint"] = bool(s["has_checkpoint"])
        wf["steps"] = steps
        return wf
    finally:
        await db.close()


@router.get("/{wf_id}/logs")
async def get_logs(wf_id: str, limit: int = 500):
    """(docstring)"""
    from services.state_store import _get_db
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM workflow_logs WHERE workflow_id = ? ORDER BY id DESC LIMIT ?",
            (wf_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        await db.close()


@router.post("/{wf_id}/start")
async def start(wf_id: str):
    """(docstring)"""
    if wf_id in _tasks and not _tasks[wf_id].done():
        raise HTTPException(status_code=409, detail="Workflow already running")
    await _validate_start_inputs(wf_id)
    task = asyncio.create_task(run_workflow(wf_id))
    _tasks[wf_id] = task
    return {"ok": True, "wf_id": wf_id}


@router.post("/{wf_id}/pause")
async def pause(wf_id: str):
    """(docstring)"""
    from services.state_store import _get_db, update_workflow
    await _cancel_workflow_tasks(wf_id)
    db = await _get_db()
    try:
        await update_workflow(db, wf_id, status="paused")
    finally:
        await db.close()
    return {"ok": True}


@router.post("/{wf_id}/resume")
async def resume(wf_id: str):
    """(docstring)"""
    from services.state_store import _get_db, update_workflow
    db = await _get_db()
    try:
        await update_workflow(db, wf_id, status="running")
    finally:
        await db.close()
    if wf_id not in _tasks or _tasks[wf_id].done():
        task = asyncio.create_task(run_workflow(wf_id))
        _tasks[wf_id] = task
    return {"ok": True}


@router.post("/{wf_id}/checkpoint")
async def submit_checkpoint(wf_id: str, body: dict):
    """(docstring)"""
    from services.workflow_engine import resolve_checkpoint
    resolve_checkpoint(wf_id, body)
    return {"ok": True}


@router.post("/{wf_id}/restart")
async def restart(wf_id: str):
    """(docstring)"""
    from services.state_store import _get_db, update_workflow
    from services.project_server import project_server_manager
    await _cancel_workflow_tasks(wf_id)
    await project_server_manager.stop(wf_id)
    await _validate_start_inputs(wf_id)
    db = await _get_db()
    try:
        await db.execute("UPDATE workflow_steps SET status = 'pending', started_at = NULL, completed_at = NULL, error_message = NULL WHERE workflow_id = ?", (wf_id,))
        await update_workflow(db, wf_id, status="pending", current_step=None)
        await db.commit()
    finally:
        await db.close()
    task = asyncio.create_task(run_workflow(wf_id))
    _tasks[wf_id] = task
    return {"ok": True}


async def _request_recovery(
    wf_id: str,
    skill_name: str | None,
    body: _RecoveryRequest,
    mode: str,
):
    from services.workflow_operations import request_step_recovery

    try:
        operation = await request_step_recovery(
            wf_id,
            skill_name,
            mode=mode,
            reason=body.reason,
            requested_by=body.requested_by,
            registry=_tasks,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "ok": True,
        "operation_id": operation["id"],
        "workflow_id": operation["workflow_id"],
        "skill_name": operation["skill_name"],
        "status": operation["status"],
    }


@router.post("/{wf_id}/steps/{skill_name}/retry", status_code=202)
async def retry_failed_step(wf_id: str, skill_name: str, body: _RecoveryRequest):
    """Retry a failed node through the real workflow executor and continue."""
    return await _request_recovery(wf_id, skill_name, body, "retry")


@router.post("/{wf_id}/recover", status_code=202)
async def recover_workflow(wf_id: str, body: _RecoveryRequest):
    """Resume the persisted failed/interrupted node selected by the ledger."""
    return await _request_recovery(wf_id, None, body, "recover")


@router.post("/{wf_id}/steps/{skill_name}/rerun")
async def rerun_step(wf_id: str, skill_name: str):
    """(docstring)"""
    task = asyncio.create_task(run_single_step(wf_id, skill_name))
    _tasks[f"{wf_id}_{skill_name}"] = task
    return {"ok": True}


@router.delete("/{wf_id}")
async def delete(wf_id: str):
    """(docstring)"""
    from services.state_store import _get_db
    from services.project_server import project_server_manager

    await _cancel_workflow_tasks(wf_id)
    await project_server_manager.stop(wf_id)
    
    # Resolve the durable workspace *before* dropping the ledger row so dual
    # clean user-data roots and rebound WORKSPACES_DIR still delete the right tree.
    workspace = _workflow_workspace_path(wf_id)

    db = await _get_db()
    try:
        await db.execute("DELETE FROM workflow_operation_events WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM workflow_artifact_lineage WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM workflow_step_attempts WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM workflow_recovery_operations WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM workflow_logs WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM workflow_steps WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM checkpoints WHERE workflow_id = ?", (wf_id,))
        await db.execute("DELETE FROM workflows WHERE id = ?", (wf_id,))
        await db.commit()
    finally:
        await db.close()

    if workspace.exists():
        shutil.rmtree(str(workspace), ignore_errors=True)

    return {"ok": True}


@router.get("/{wf_id}/export")
async def export_one(wf_id: str):
    """Export one workflow as a ZIP containing its manifest and workspace."""
    from services.state_store import export_workflow_data
    data = await export_workflow_data(wf_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workspace = _workflow_workspace_path(
        wf_id,
        (data.get("workflow") or {}).get("workspace_dir"),
    )
    zip_path = _temporary_zip_path()
    await asyncio.to_thread(_build_export_zip, zip_path, wf_id, workspace if workspace.exists() else None, data)

    title = _safe_name(data["workflow"].get("title", ""), wf_id)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"VibeResearch_{title}_{timestamp}.zip",
        background=BackgroundTask(os.unlink, zip_path),
    )


@router.post("/export-batch")
async def export_batch(body: _BatchExportRequest):
    """Export multiple workflows into a single ZIP."""
    from services.state_store import export_workflow_data
    exports = []
    for wf_id in body.ids:
        data = await export_workflow_data(wf_id)
        if data is not None:
            workspace = _workflow_workspace_path(
                wf_id,
                (data.get("workflow") or {}).get("workspace_dir"),
            )
            title = _safe_name(data["workflow"].get("title", ""), "workflow")
            exports.append((f"{title}_{wf_id}/", workspace if workspace.exists() else None, data))

    zip_path = _temporary_zip_path()

    def _build_batch():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for prefix, workspace, manifest in exports:
                _write_export_entries(zf, prefix, workspace, manifest)

    await asyncio.to_thread(_build_batch)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"VibeResearch_batch_{len(exports)}_{timestamp}.zip",
        background=BackgroundTask(os.unlink, zip_path),
    )


@router.post("/import")
async def import_workflows(file: UploadFile = File(...)):
    """Import one or more workflow exports."""
    from services.state_store import import_workflow_data

    content = await file.read()
    imported = []

    def _safe_relative(name: str) -> Path | None:
        normalized = name.replace("\\", "/").strip("/")
        parts = Path(normalized).parts
        if not normalized or any(part in {"", ".", ".."} for part in parts):
            return None
        return Path(*parts)

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid ZIP file") from exc

    with zf:
        names = zf.namelist()
        manifests: list[tuple[str, str]] = []
        if "manifest.json" in names:
            manifests.append(("", "manifest.json"))
        elif "_manifest.json" in names:
            manifests.append(("", "_manifest.json"))
        else:
            for name in names:
                if name.endswith("/manifest.json") or name.endswith("/_manifest.json"):
                    manifests.append((name.rsplit("/", 1)[0] + "/", name))

        for prefix, manifest_name in manifests:
            try:
                manifest = json.loads(zf.read(manifest_name))
            except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid manifest: {manifest_name}") from exc

            new_id = str(uuid.uuid4())[:8]
            workspace = WORKSPACES_DIR / new_id
            workspace.mkdir(parents=True, exist_ok=True)

            for name in names:
                if name == manifest_name or not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
                if rel.startswith("workspace/"):
                    rel = rel[len("workspace/"):]
                elif manifest_name.endswith("manifest.json") and not manifest_name.endswith("_manifest.json"):
                    continue
                safe_rel = _safe_relative(rel)
                if safe_rel is None or name.endswith("/"):
                    continue
                filepath = workspace / safe_rel
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_bytes(zf.read(name))

            await import_workflow_data(manifest, new_id, str(workspace))
            imported.append(new_id)

    if not imported:
        raise HTTPException(status_code=400, detail="No workflow manifest found")
    return {"imported": imported}


# ============================================================

# ============================================================

def start_heartbeat():
    """(docstring)"""
    from services.state_store import get_workflows_to_resume
    
    async def _heartbeat():
        while True:
            await asyncio.sleep(60)
            try:
                resume_ids = get_workflows_to_resume()
                for wf_id in resume_ids:
                    if wf_id in _tasks and not _tasks[wf_id].done():
                        continue
                    log.info("Heartbeat: auto-resuming workflow %s", wf_id)
                    task = asyncio.create_task(run_workflow(wf_id))
                    _tasks[wf_id] = task
            except Exception as e:
                log.warning("Heartbeat error: %s", e)
    
    asyncio.create_task(_heartbeat())
