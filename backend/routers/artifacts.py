"""(docstring)"""
from __future__ import annotations

import logging
import os
import shutil
import hashlib
import json
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from services.artifact_manager import record_artifact, workspace_path, write_artifact
from services.safe_archive import (
    MAX_UPLOAD_BYTES,
    extract_archive,
    is_supported_archive,
    safe_filename,
    safe_relative_path,
    within,
)
from services.workspace_paths import WorkspacePathError, resolve_workflow_workspace

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows/{wf_id}/artifacts", tags=["artifacts"])


def _workspace(wf_id: str) -> Path:
    try:
        d = resolve_workflow_workspace(wf_id, require_exists=True)
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workflow {wf_id} not found") from exc
    return d


def _input_dir(workspace: Path) -> Path:
    directory = workspace / "user_data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def _store_upload(file: UploadFile, destination: Path) -> int:
    """Stream an upload to disk so the 1 GiB contract never becomes RAM use."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds size limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        temporary = None
        return total
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _input_entry(path: Path, root: Path, status: dict, manifest: dict) -> dict:
    raw = path.read_bytes()
    relative = str(path.relative_to(root)).replace(os.sep, "/")
    item_status = status.get("files", {}).get(relative, {})
    return {
        "path": relative,
        "name": path.name,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "status": item_status.get("status", "uploaded"),
        "extracted_text": item_status.get("text_file"),
        "role": manifest.get("files", {}).get(relative, {}).get("role", "material"),
    }


def _extracted_paths(status: dict) -> set[str]:
    paths: set[str] = set()
    for source, item in status.get("files", {}).items():
        paths.add(f"{str(source).replace(chr(92), '/')}.txt")
        text_file = item.get("text_file")
        if text_file:
            paths.add(str(text_file).replace("\\", "/"))
    return paths


@router.get("")
async def list_artifacts(wf_id: str):
    """List durable workspace deliverables for a workflow.

    Historical builds only scanned ``uploads/``, which made completed papers,
    patents, and competition PDFs look empty in the API even when the workspace
    and ZIP export already contained them.  Mirror the run-center filter so the
    product surface, export, and operations ledger agree.
    """
    from routers.workflows import _should_include_file

    workspace = _workspace(wf_id)
    result = []
    for item in sorted(workspace.rglob("*"), key=lambda path: path.as_posix().lower()):
        if not item.is_file():
            continue
        try:
            relative = item.relative_to(workspace)
        except ValueError:
            continue
        if not _should_include_file(relative):
            continue
        result.append(
            {
                "path": relative.as_posix(),
                "size": item.stat().st_size,
            }
        )
    return result


@router.post("/upload")
async def upload_files(wf_id: str, files: List[UploadFile] = File(...)):
    """(docstring)"""
    workspace = _workspace(wf_id)
    upload_dir = workspace / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    from services.extract_worker import mark_pending, schedule_extract
    
    uploaded = []
    for f in files:
        try:
            filename = safe_filename(f.filename or "")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        dest = within(upload_dir, upload_dir / filename)
        await _store_upload(f, dest)
        if is_supported_archive(dest):
            try:
                extracted = extract_archive(dest, upload_dir / f"{dest.name.split('.')[0]}_extracted")
            except (ValueError, OSError) as e:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(e))
            uploaded.extend(extracted)
        else:
            mark_pending(upload_dir, filename)
            await schedule_extract(upload_dir, filename)
            uploaded.append(filename)
    
    return {"uploaded": uploaded}


@router.get("/inputs")
async def list_inputs(wf_id: str):
    """List user-supplied files with integrity and extraction state."""
    workspace = _workspace(wf_id)
    root = _input_dir(workspace)
    status_path = root / "_extract_status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"files": {}}
    except (OSError, ValueError):
        status = {"files": {}}
    manifest_path = root / "_input_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": {}}
    except (OSError, ValueError):
        manifest = {"files": {}}
    extracted_names = _extracted_paths(status)
    return [
        _input_entry(item, root, status, manifest)
        for item in sorted(root.rglob("*"))
        if item.is_file()
        and item.name not in {"_extract_status.json", "_input_manifest.json"}
        and str(item.relative_to(root)).replace(os.sep, "/") not in extracted_names
    ]


@router.post("/inputs/upload")
async def upload_inputs(
    wf_id: str,
    files: List[UploadFile] = File(...),
    role: str = Form("material"),
    relative_paths: List[str] = Form(default=[]),
):
    """Store declared workflow inputs under ``user_data`` and extract text."""
    workspace = _workspace(wf_id)
    root = _input_dir(workspace)
    from services.extract_worker import mark_pending, schedule_extract

    allowed_roles = {
        "material",
        "requirements",
        "code",
        "data",
        "figures",
        "results",
        "templates",
        "problem",
        "problem_images",
        "outline",
        "custom_requirements",
        "source",
        "paper",
    }
    if role not in allowed_roles:
        raise HTTPException(status_code=422, detail="Unknown workflow input role")
    manifest_path = root / "_input_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"version": 1, "files": {}}
    except (OSError, ValueError):
        manifest = {"version": 1, "files": {}}

    uploaded = []
    for index, file in enumerate(files):
        try:
            filename = safe_filename(file.filename or "")
            supplied_path = relative_paths[index] if index < len(relative_paths) else filename
            relative_path = safe_relative_path(supplied_path)
            if relative_path.name != filename:
                # Multipart clients may normalize the UploadFile filename; the
                # relative path is authoritative only for its directory parts.
                relative_path = relative_path.parent / filename
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        destination = within(root, root / relative_path)
        await _store_upload(file, destination)
        relative = str(destination.relative_to(root)).replace(os.sep, "/")
        manifest.setdefault("files", {})[relative] = {"role": role}
        if is_supported_archive(destination):
            try:
                extract_root = destination.parent / f"{destination.name.split('.')[0]}_extracted"
                extracted = extract_archive(destination, extract_root)
            except (ValueError, OSError) as exc:
                destination.unlink(missing_ok=True)
                manifest.setdefault("files", {}).pop(relative, None)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            uploaded.append(relative)
            for item in extracted:
                extracted_relative = str((extract_root / item).relative_to(root)).replace(os.sep, "/")
                mark_pending(root, extracted_relative)
                await schedule_extract(root, extracted_relative)
                uploaded.append(extracted_relative)
                manifest.setdefault("files", {})[extracted_relative] = {"role": role}
        else:
            mark_pending(root, relative)
            await schedule_extract(root, relative)
            uploaded.append(relative)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"uploaded": uploaded}


@router.get("/extract-status")
async def extract_status(wf_id: str):
    """(docstring)"""
    workspace = _workspace(wf_id)
    upload_dir = workspace / "uploads"
    if not upload_dir.exists():
        return {"files": {}}
    from services.extract_worker import get_status
    return get_status(upload_dir)


@router.post("/custom-requirements")
async def upload_custom_requirements(wf_id: str, file: UploadFile = File(...)):
    """(docstring)"""
    workspace = _workspace(wf_id)
    from services.upload_limits import read_limited
    from services.extract_worker import extract_text_file
    try:
        filename = safe_filename(file.filename or "requirements.md")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = await read_limited(file)
    original = _input_dir(workspace) / filename
    original.write_bytes(data)
    text = await extract_text_file(original)
    if not text or not text.strip():
        raise HTTPException(status_code=422, detail="无法从要求文档中提取文字，请上传 Word、PDF、Markdown、TXT 或 TeX 文件")
    artifact = write_artifact(workspace, "CUSTOM_REQUIREMENTS.md", text.strip() + "\n", kind="requirements")
    return {"ok": True, "path": artifact["path"], "source": f"user_data/{filename}", "sha256": artifact["sha256"]}


@router.put("/{path:path}")
async def update_artifact(wf_id: str, path: str, content: str = ""):
    """(docstring)"""
    workspace = _workspace(wf_id)
    try:
        artifact = write_artifact(workspace, path, content)
    except (ValueError, OSError):
        raise HTTPException(status_code=403, detail="Path traversal detected")
    return {"ok": True, "artifact": artifact}


@router.get("/export")
async def export_workspace(wf_id: str):
    """(docstring)"""
    workspace = _workspace(wf_id)
    
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in workspace.rglob("*"):
            if item.is_file() and not item.name.startswith("._"):
                rel = item.relative_to(workspace)
                zf.write(item, str(rel).replace(os.sep, "/"))
    buffer.seek(0)
    
    return StreamingResponse(buffer, media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename=workspace-{wf_id}.zip"
    })


@router.get("/{path:path}")
async def read_artifact(wf_id: str, path: str):
    """(docstring)"""
    workspace = _workspace(wf_id)
    try:
        filepath = workspace_path(workspace, path, allow_missing=False)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal detected")

    suffix = filepath.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".pdf", ".docx", ".xlsx", ".zip"):
        return FileResponse(str(filepath))
    

    content = filepath.read_text(encoding="utf-8", errors="replace")
    artifact = record_artifact(workspace, filepath)
    return {"path": path, "content": content, "sha256": artifact["sha256"]}
