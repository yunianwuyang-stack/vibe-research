"""Local project preview endpoints used by the workflow editor."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import WORKSPACES_DIR
from services.project_server import project_server_manager

router = APIRouter(prefix="/api/editor", tags=["project-preview"])


class ServeRequest(BaseModel):
    mode: str = "both"


def _workspace(wf_id: str, *, require_exists: bool) -> Path:
    root = WORKSPACES_DIR.resolve()
    unresolved = root / wf_id
    if unresolved.is_symlink():
        raise HTTPException(status_code=400, detail="非法的工作流 ID")
    workspace = unresolved.resolve()
    try:
        relative = workspace.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法的工作流 ID") from exc
    if len(relative.parts) != 1 or not relative.parts[0]:
        raise HTTPException(status_code=400, detail="非法的工作流 ID")
    if require_exists and not workspace.is_dir():
        raise HTTPException(status_code=404, detail="工作流不存在")
    return workspace


def _code_dir(wf_id: str) -> Path:
    workspace = _workspace(wf_id, require_exists=True)
    unresolved = workspace / "code"
    if unresolved.is_symlink():
        raise HTTPException(status_code=400, detail="项目 code/ 目录不能是符号链接")
    code = unresolved.resolve()
    try:
        code.relative_to(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="项目目录越界") from exc
    if not code.is_dir():
        raise HTTPException(status_code=400, detail="该工作流还没有生成 code/ 项目目录")
    return code


@router.post("/{wf_id}/serve")
async def start_serve(wf_id: str, body: ServeRequest):
    code = _code_dir(wf_id)
    mode = (body.mode or "both").strip()
    if mode not in {"frontend", "backend", "both"}:
        raise HTTPException(status_code=400, detail="mode 必须是 frontend / backend / both")
    try:
        return await project_server_manager.start(wf_id, code, mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{wf_id}/serve")
async def stop_serve(wf_id: str, kind: str | None = None):
    _workspace(wf_id, require_exists=False)
    if kind is not None and kind not in {"frontend", "backend"}:
        raise HTTPException(status_code=400, detail="kind 必须是 frontend / backend")
    try:
        return await project_server_manager.stop(wf_id, kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{wf_id}/serve/status")
async def serve_status(wf_id: str):
    _workspace(wf_id, require_exists=False)
    return await project_server_manager.status(wf_id)
