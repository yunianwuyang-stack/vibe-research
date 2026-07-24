"""DOCX export for workflow Markdown sources with durable lineage audits."""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import TOOLS_DIR, WORKSPACES_DIR, PANDOC_BIN
from services.docx_tool_loader import get_markdown_to_docx
from services.workspace_paths import WorkspacePathError, resolve_workflow_workspace

log = logging.getLogger(__name__)
router = APIRouter(tags=["docx_export"])

_SKIP_FILES = {
    "checkpoint_feedback.md", "CLAUDE.md",
    "EXECUTION_SUMMARY.md", "EXECUTION_SUMMARY.txt",
    "CUSTOM_REQUIREMENTS.md",
}
_SOURCE_CANDIDATES = [
    "paper/main.md", "PROPOSAL.md", "LITERATURE_REVIEW.md",
    "COURSE_PAPER.md", "COURSE_REPORT.md", "REPORT.md",
    "RESULTS.md", "MODELING_REPORT.md",
]


class DocxExportRequest(BaseModel):
    source_file: Optional[str] = None
    style_profile: Optional[str] = None
    engine: Optional[str] = "auto"


def _resolve_source(workspace: Path, explicit: Optional[str]) -> Optional[Path]:
    """Resolve a Markdown source under the workflow workspace."""
    root = workspace.resolve()

    def safe(candidate: Path) -> Path | None:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() and not resolved.is_symlink() and resolved.suffix == ".md" else None

    if explicit:
        return safe(workspace / explicit)
    for candidate in _SOURCE_CANDIDATES:
        p = safe(workspace / candidate)
        if p:
            return p
    return None


def _rel(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except Exception:
        return path.name


def _write_docx_lineage(
    workspace: Path,
    *,
    source: Path,
    output_path: Path,
    engine: str,
    style_profile: Optional[str],
    wf_id: str,
) -> dict[str, Any]:
    """Persist export provenance under .docx_exports for recovery and ZIP export."""
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    audit_dir = workspace / ".docx_exports"
    audit_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "operation": "export-docx",
        "skill_name": "export-docx",
        "executor": "docx_export",
        "workflow_id": wf_id,
        "engine": engine,
        "source": _rel(workspace, source),
        "output": _rel(workspace, output_path),
        "style_profile": style_profile,
        "bytes": int(output_path.stat().st_size),
        "sha256": digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
    }
    audit_path = audit_dir / f"{stamp}-{digest[:12]}.json"
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["audit_path"] = _rel(workspace, audit_path)
    return payload


@router.post("/api/workflows/{wf_id}/export-docx")
async def export_docx(wf_id: str, body: DocxExportRequest = DocxExportRequest()):
    """Convert workspace Markdown to DOCX via node/python/pandoc engines."""
    try:
        workspace = resolve_workflow_workspace(
            wf_id,
            require_exists=True,
            fallback_root=Path(WORKSPACES_DIR),
        )
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workflow {wf_id} not found") from exc

    source = _resolve_source(workspace, body.source_file)
    if source is None:
        raise HTTPException(status_code=404, detail="No Markdown source found")

    engine = body.engine or "auto"
    if engine == "auto":
        node_bin = shutil.which("node")
        md_to_docx_script = TOOLS_DIR / "docx-cn-engine" / "md_to_docx.js"
        if node_bin and md_to_docx_script.exists():
            engine = "node"
        else:
            try:
                get_markdown_to_docx()
                engine = "python"
            except (FileNotFoundError, ImportError):
                pass
        if engine == "auto" and (PANDOC_BIN or shutil.which("pandoc")):
            engine = "pandoc"
        elif engine == "auto":
            raise HTTPException(status_code=500, detail="No DOCX engine available")

    output_path = source.with_suffix(".docx")

    if engine == "node":
        import asyncio

        md_to_docx_script = TOOLS_DIR / "docx-cn-engine" / "md_to_docx.js"
        node_bin = shutil.which("node")
        if not node_bin or not md_to_docx_script.exists():
            raise HTTPException(status_code=500, detail="Node DOCX engine is not available")
        cmd = [node_bin, str(md_to_docx_script), "--source", str(source), "--output", str(output_path), "--workspace", str(workspace)]
        if body.style_profile:
            profile = TOOLS_DIR / "docx_style_profiles" / body.style_profile
            cmd.extend(["--profile", str(profile)])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0 or not output_path.exists():
            raise HTTPException(
                status_code=500,
                detail=f"DOCX export failed: {stderr.decode('utf-8', errors='replace')[:500]}",
            )
    elif engine == "python":
        import asyncio

        try:
            converter = get_markdown_to_docx()
            if converter is None:
                raise FileNotFoundError("tools/docx_export.py[c]")
            style_profile = None
            if body.style_profile:
                candidate = TOOLS_DIR / "docx_style_profiles" / body.style_profile
                style_profile = candidate if candidate.exists() else None
            await asyncio.to_thread(
                converter,
                source,
                output_path,
                style_profile,
                workspace,
                "python",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Python DOCX export failed: {str(exc)[:500]}",
            ) from exc
        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Python DOCX export produced no file")
    elif engine == "pandoc":
        pandoc_bin = PANDOC_BIN or shutil.which("pandoc")
        if not pandoc_bin:
            raise HTTPException(status_code=500, detail="Pandoc is not available")
        cmd = [pandoc_bin, "-f", "markdown", "-t", "docx", "-o", str(output_path), str(source)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not output_path.exists():
            raise HTTPException(status_code=500, detail=f"Pandoc failed: {result.stderr[:500]}")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported DOCX engine: {engine}")

    try:
        _write_docx_lineage(
            workspace,
            source=source,
            output_path=output_path,
            engine=str(engine),
            style_profile=body.style_profile,
            wf_id=wf_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("docx lineage write failed for %s: %s", wf_id, exc)

    return FileResponse(
        str(output_path),
        headers={"Content-Disposition": f'attachment; filename="{source.stem}.docx"'},
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
