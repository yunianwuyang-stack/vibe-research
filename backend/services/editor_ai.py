"""Editor AI service - AI-assisted editing, translation, figure generation."""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import html
from io import BytesIO
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import (
    TOOLS_DIR,
    WORKSPACES_DIR,
    IS_DESKTOP,
    RUNTIME_TEXLIVE,
    RUNTIME_DRAWIO,
    RUNTIME_PYTHON,
    PANDOC_BIN,
    SKILLS_DIR,
)
from services.workspace_paths import WorkspacePathError, resolve_workflow_workspace

log = logging.getLogger(__name__)

_IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
_IMAGE_MAX_BYTES = 100 * 1024 * 1024
_IMAGE_MAX_PIXELS = 100_000_000
_IMAGE_AUDIT_MAX_FILES = 250
_IMAGE_SUFFIXES_BY_FORMAT = {
    "AVIF": {".avif"}, "BMP": {".bmp"}, "GIF": {".gif"}, "ICO": {".ico"},
    "JPEG": {".jpeg", ".jpg"}, "PNG": {".png"}, "TIFF": {".tif", ".tiff"}, "WEBP": {".webp"},
}
_IMAGE_EXTENSION_BY_FORMAT = {"AVIF": ".avif", "BMP": ".bmp", "GIF": ".gif", "ICO": ".ico", "JPEG": ".jpg", "PNG": ".png", "TIFF": ".tiff", "WEBP": ".webp"}
_DRAWIO_FORMATS = {"png", "pdf", "svg"}
_DRAWIO_SOURCE_MAX_BYTES = 2 * 1024 * 1024
_MERMAID_FORMATS = {"png", "pdf", "svg"}
_MERMAID_SOURCE_MAX_BYTES = 512 * 1024


def _workspace_root(wf_id: str) -> Path:
    """Resolve a workflow directory from durable ledger state when available."""
    try:
        # Prefer the create-time absolute path; fall back to this module's
        # WORKSPACES_DIR so unit tests that monkeypatch it keep working.
        return resolve_workflow_workspace(wf_id, fallback_root=Path(WORKSPACES_DIR))
    except WorkspacePathError as exc:
        raise ValueError("Invalid workspace") from exc


def _workspace_path(wf_id: str, relative_path: str) -> Path:
    """Resolve a user-supplied workspace path without permitting traversal."""
    workspace = _workspace_root(wf_id)
    target = (workspace / relative_path).resolve()
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("Path traversal detected") from exc
    return target


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _agent_state_path(wf_id: str) -> Path:
    workspace = _workspace_root(wf_id)
    state_dir = workspace / ".editor_agent"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "staging.json"


def _load_agent_state(wf_id: str) -> dict:
    state_path = _agent_state_path(wf_id)
    if not state_path.exists():
        return {"proposals": []}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_agent_state(wf_id: str, state: dict) -> None:
    _agent_state_path(wf_id).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

LATEX_SYSTEM_PROMPT = """You are a LaTeX editor assistant. Help the user edit, fix, and improve their LaTeX paper.
Rules:
- Always output complete file content, not just changes.
- Preserve existing content structure.
- Use proper LaTeX formatting."""

MARKDOWN_SYSTEM_PROMPT = """You are a Markdown editor assistant. Help the user edit, fix, and improve their Markdown document.
Rules:
- Always output complete file content, not just changes.
- Preserve existing content structure.
- Use proper Markdown formatting."""


def _append_chat_history(wf_id: str, entry: dict) -> list:
    """Persist an append-only editor chat turn beside the workspace."""
    workspace = _workspace_root(wf_id)
    history_path = workspace / "_chat_history.json"
    history: list = []
    if history_path.exists():
        try:
            loaded = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = loaded
        except (OSError, ValueError, TypeError):
            history = []
    history.append(entry)
    history = history[-50:]
    temporary = history_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(history_path)
    return history


async def ai_edit(
    message: str,
    current_file: str,
    current_content: str,
    workspace_files: list[str],
    compile_log: str = "",
    extra_context: str = "",
    history: list = None,
    role: str = "latex",
    chat_summary: str = "",
    *,
    wf_id: str | None = None,
) -> dict:
    """Call LLM to edit file content and optionally persist the chat turn."""
    from services.llm_client import call_llm, get_all_settings

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must not be empty")
    if not isinstance(current_file, str) or not current_file.strip():
        raise ValueError("current_file is required")

    settings = await get_all_settings()
    if not settings.get("editor_ai_api_key", "").strip() or not settings.get("editor_ai_base_url", "").strip():
        raise RuntimeError("agent_provider_unavailable")

    system_prompt = LATEX_SYSTEM_PROMPT if role == "latex" else MARKDOWN_SYSTEM_PROMPT
    history_block = ""
    if history:
        clipped = history[-8:] if isinstance(history, list) else []
        rendered = []
        for item in clipped:
            if not isinstance(item, dict):
                continue
            role_name = str(item.get("role") or "user")
            text = str(item.get("content") or item.get("message") or "").strip()
            if text:
                rendered.append(f"{role_name}: {text[:1200]}")
        if rendered:
            history_block = "Conversation so far:\n" + "\n".join(rendered)

    user_msg = f"""You are editing: {current_file}

Current content:
```
{current_content[:8000]}
```

Other files in workspace: {', '.join(str(item) for item in (workspace_files or [])[:20])}
{f"Compile log: {compile_log[:2000]}" if compile_log else ""}
{f"Extra context: {extra_context}" if extra_context else ""}
{f"Previous conversation summary: {chat_summary}" if chat_summary else ""}
{history_block}

User request: {message}

Please output the complete updated file content. If you cannot help, explain why."""

    response = await call_llm("editor_ai", f"{system_prompt}\n\n{user_msg}", timeout=300)
    result = {
        "content": response,
        "file": current_file,
        "message": message,
        "role": role,
        "status": "completed",
    }
    if wf_id:
        persisted = _append_chat_history(wf_id, {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "request": message,
            "file": current_file,
            "content": response,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        result["history"] = persisted
        result["history_path"] = "_chat_history.json"
    return result


def get_mode(wf_id: str) -> str:
    """Return editor mode (latex or markdown)."""
    workspace = _workspace_root(wf_id)
    if (workspace / "paper" / "main.tex").exists():
        return "latex"
    if (workspace / "paper" / "main.md").exists():
        return "markdown"
    for candidate in ["COURSE_PAPER.md", "COURSE_REPORT.md", "REPORT.md", "RESULTS.md", "MODELING_REPORT.md"]:
        if (workspace / candidate).exists():
            return "markdown"
    return "latex"


def list_files(wf_id: str) -> list[dict]:
    """List workspace file tree."""
    workspace = _workspace_root(wf_id)
    if not workspace.exists():
        return []
    
    result = []
    for item in sorted(workspace.rglob("*")):
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "_editor_backup") for part in item.parts):
            continue
        if item.is_file():
            rel = str(item.relative_to(workspace)).replace("\\", "/")
            result.append({"path": rel, "size": item.stat().st_size})
    return result


def read_file(wf_id: str, path: str) -> str:
    """Read workspace file."""
    filepath = _workspace_path(wf_id, path)
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return filepath.read_text(encoding="utf-8", errors="replace")


async def save_file(wf_id: str, path: str, content: str) -> None:
    """Save workspace file."""
    filepath = _workspace_path(wf_id, path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")


async def upload_file(wf_id: str, path: str, file_data: bytes) -> None:
    """Upload file to workspace."""
    filepath = _workspace_path(wf_id, path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(file_data)


async def create_file(wf_id: str, path: str) -> None:
    filepath = _workspace_path(wf_id, path)
    if filepath.exists():
        raise FileExistsError(f"File already exists: {path}")
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.touch()


async def delete_file(wf_id: str, path: str) -> None:
    filepath = _workspace_path(wf_id, path)
    if not filepath.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    filepath.unlink()


def download_file(wf_id: str, path: str) -> Path:
    filepath = _workspace_path(wf_id, path)
    if not filepath.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return filepath


def file_preview_html(wf_id: str, path: str) -> str:
    return f"<pre>{html.escape(read_file(wf_id, path))}</pre>"


def get_stats(wf_id: str, path: str = "") -> dict:
    if path:
        content = read_file(wf_id, path)
        files = [path]
    else:
        files = [item["path"] for item in list_files(wf_id)]
        content = "\n".join(read_file(wf_id, item) for item in files if item.endswith((".md", ".tex", ".txt")))
    return {"files": len(files), "characters": len(content), "words": len(content.split())}


def get_docx(wf_id: str) -> Path:
    """Return .docx file path if exists."""
    workspace = _workspace_root(wf_id)
    for candidate in ["COURSE_PAPER.docx", "COURSE_REPORT.docx", "paper/main.docx"]:
        p = workspace / candidate
        if p.exists():
            return p
    raise FileNotFoundError("No .docx file found")


def get_pdf(wf_id: str) -> Path:
    """Return PDF file path."""
    workspace = _workspace_root(wf_id)
    pdf_path = workspace / "paper" / "main.pdf"
    if pdf_path.exists():
        return pdf_path
    raise FileNotFoundError("No PDF file found")


def _workspace(wf_id: str) -> Path:
    workspace = _workspace_root(wf_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _artifact_metadata(workspace: Path, path: Path) -> dict:
    resolved = path.resolve()
    resolved.relative_to(workspace)
    return {
        "path": resolved.relative_to(workspace).as_posix(),
        "sha256": _file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_workspace_files(workspace: Path) -> list[Path]:
    candidates: list[Path] = []
    for candidate in workspace.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.casefold() not in _IMAGE_SUFFIXES:
            continue
        try:
            relative = candidate.resolve().relative_to(workspace)
        except ValueError:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        candidates.append(candidate)
    return sorted(candidates)


def _image_audit_entry(workspace: Path, image_path: Path) -> dict:
    source = _artifact_metadata(workspace, image_path)
    entry: dict = {"source": source, "status": "failed", "warnings": []}
    if source["bytes"] > _IMAGE_MAX_BYTES:
        entry["failure_reason"] = f"Image exceeds the {_IMAGE_MAX_BYTES // (1024 * 1024)} MB audit limit"
        return entry
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise RuntimeError("Bundled Pillow runtime is unavailable; image audit cannot run") from error
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            pixel_count = width * height
            if pixel_count > _IMAGE_MAX_PIXELS:
                entry["failure_reason"] = f"Image exceeds the {_IMAGE_MAX_PIXELS:,} pixel audit limit"
                return entry
            image_format = str(image.format or "unknown").upper()
            expected_suffixes = _IMAGE_SUFFIXES_BY_FORMAT.get(image_format)
            if expected_suffixes and image_path.suffix.casefold() not in expected_suffixes:
                entry["warnings"].append("filename_extension_does_not_match_detected_format")
            entry.update({
                "status": "valid",
                "format": image_format,
                "mime_type": Image.MIME.get(image_format, "application/octet-stream"),
                "width": width,
                "height": height,
                "pixels": pixel_count,
                "mode": str(image.mode),
                "frames": int(getattr(image, "n_frames", 1)),
                "animated": bool(getattr(image, "is_animated", False)),
                "has_alpha": "A" in str(image.mode) or "transparency" in image.info,
                "metadata_keys": sorted(str(key) for key in image.info.keys())[:32],
            })
        with Image.open(image_path) as verification_image:
            verification_image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
        entry["failure_reason"] = f"Image structure validation failed: {type(error).__name__}: {error}"
    return entry


def _image_description(entry: dict) -> str:
    source_path = entry["source"]["path"]
    if entry["status"] != "valid":
        return f"{source_path} failed deterministic image structure validation: {entry.get('failure_reason', 'unknown failure')}"
    return (
        f"Deterministic local metadata audit for {source_path}: {entry['format']} "
        f"{entry['width']}x{entry['height']} pixels, mode {entry['mode']}, "
        f"{entry['frames']} frame(s), SHA256 {entry['source']['sha256']}."
    )


async def audit_images(wf_id: str, path: str = "") -> dict:
    """Audit image structure and metadata without inventing visual semantics."""
    workspace = _workspace(wf_id)
    if path:
        candidate = _workspace_path(wf_id, path)
        if candidate.is_symlink() or not candidate.is_file():
            raise FileNotFoundError(f"Image file not found: {path}")
        if candidate.suffix.casefold() not in _IMAGE_SUFFIXES:
            raise ValueError("Image audit supports AVIF, BMP, GIF, ICO, JPEG, PNG, TIFF, and WebP files")
        images = [candidate]
        scope = candidate.relative_to(workspace).as_posix()
    else:
        images = _image_workspace_files(workspace)
        if len(images) > _IMAGE_AUDIT_MAX_FILES:
            raise ValueError(f"Workspace contains {len(images)} images; audit a specific path or reduce it to {_IMAGE_AUDIT_MAX_FILES} images")
        scope = "workspace"

    started = datetime.now(timezone.utc).isoformat()
    entries = [_image_audit_entry(workspace, image_path) for image_path in images]
    summary = {
        "files_scanned": len(entries),
        "valid": sum(entry["status"] == "valid" for entry in entries),
        "failed": sum(entry["status"] != "valid" for entry in entries),
    }
    status = "no_images" if not entries else ("completed" if summary["failed"] == 0 else "completed_with_failures")
    run_id = uuid.uuid4().hex
    manifest = {
        "format_version": "1.0",
        "operation": "deterministic_image_audit",
        "id": run_id,
        "status": status,
        "scope": scope,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "limits": {"max_bytes_per_file": _IMAGE_MAX_BYTES, "max_pixels_per_file": _IMAGE_MAX_PIXELS, "max_files_per_workspace_audit": _IMAGE_AUDIT_MAX_FILES},
        "summary": summary,
        "images": entries,
    }
    audit_dir = workspace / ".image_audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audit_dir / f"{run_id}.json"
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_path.write_bytes(raw)
    return {
        "status": status,
        "scope": scope,
        "summary": summary,
        "images": entries,
        "manifest": {"path": manifest_path.relative_to(workspace).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()},
    }


async def describe_image(wf_id: str, path: str) -> dict:
    """Return an auditable metadata description, never an invented vision caption."""
    if not path.strip():
        raise ValueError("An image path is required")
    audit = await audit_images(wf_id, path)
    image = audit["images"][0]
    return {**audit, "image": image, "description": _image_description(image), "description_kind": "deterministic_metadata"}


def _write_operation_manifest(workspace: Path, directory: str, manifest: dict) -> dict:
    audit_dir = workspace / directory
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{manifest['id']}.json"
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return {"path": path.relative_to(workspace).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def _generated_image_format(image_bytes: bytes) -> str:
    try:
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = str(image.format or "").upper()
        with Image.open(BytesIO(image_bytes)) as verification_image:
            verification_image.verify()
    except ImportError as error:
        raise RuntimeError("Bundled Pillow runtime is unavailable; image generation cannot validate output") from error
    except (OSError, ValueError, SyntaxError) as error:
        raise ValueError(f"Image provider returned an invalid image: {type(error).__name__}: {error}") from error
    if image_format not in _IMAGE_EXTENSION_BY_FORMAT:
        raise ValueError(f"Image provider returned unsupported format: {image_format or 'unknown'}")
    return image_format


async def generate_image(wf_id: str, prompt: str, model: str = "", size: str = "1024x1024") -> dict:
    """Generate, validate, and persist a provider image with hash-addressed evidence."""
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Image prompt is required")
    if len(prompt) > 12_000:
        raise ValueError("Image prompt exceeds the 12,000 character limit")
    workspace = _workspace(wf_id)
    run_id = uuid.uuid4().hex
    started = datetime.now(timezone.utc).isoformat()
    provider_info: dict = {}
    try:
        from services import llm_client
        image_bytes, provider_info = await llm_client.generate_image("editor_ai", prompt, model, size)
        image_format = _generated_image_format(image_bytes)
        output_dir = workspace / "figures" / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{run_id}{_IMAGE_EXTENSION_BY_FORMAT[image_format]}"
        output.write_bytes(image_bytes)
        image = _image_audit_entry(workspace, output)
        if image["status"] != "valid":
            raise ValueError(image.get("failure_reason", "Generated image did not pass validation"))
        manifest = {
            "format_version": "1.0",
            "operation": "provider_image_generation",
            "id": run_id,
            "status": "completed",
            "started_at_utc": started,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "request": {"prompt": prompt, "prompt_sha256": _content_hash(prompt), "model": provider_info.get("model_id"), "size": provider_info.get("size")},
            "provider": {"kind": provider_info.get("provider"), "base_url": provider_info.get("base_url")},
            "response": {"bytes_sha256": hashlib.sha256(image_bytes).hexdigest(), "revised_prompt": provider_info.get("revised_prompt")},
            "image": image,
        }
    except RuntimeError as error:
        message = str(error)
        # Missing credentials / wrong protocol: fail closed with structured 503.
        # Other provider failures: durable failed manifest (never mock success).
        if any(
            token in message
            for token in (
                "API 密钥",
                "服务地址（Base URL）",
                "需要使用 OpenAI 兼容协议",
                "未配置",
                "不支持的服务商",
            )
        ):
            raise RuntimeError(message) from error
        manifest = {
            "format_version": "1.0", "operation": "provider_image_generation", "id": run_id, "status": "failed",
            "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "request": {"prompt": prompt, "prompt_sha256": _content_hash(prompt), "model": model, "size": size},
            "provider": {"kind": provider_info.get("provider"), "base_url": provider_info.get("base_url")},
            "failure_reason": message[:2000],
        }
    except ValueError as error:
        manifest = {
            "format_version": "1.0", "operation": "provider_image_generation", "id": run_id, "status": "failed",
            "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "request": {"prompt": prompt, "prompt_sha256": _content_hash(prompt), "model": model, "size": size},
            "provider": {"kind": provider_info.get("provider"), "base_url": provider_info.get("base_url")},
            "failure_reason": str(error)[:2000],
        }
    manifest_ref = _write_operation_manifest(workspace, ".image_generation", manifest)
    return {"status": manifest["status"], "image": manifest.get("image"), "manifest": manifest_ref, "failure_reason": manifest.get("failure_reason"), "revised_prompt": manifest.get("response", {}).get("revised_prompt")}


def _drawio_executable() -> Path:
    override = os.environ.get("VIBE_DRAWIO_BIN", "").strip()
    candidates = [Path(override)] if override else []
    if RUNTIME_DRAWIO:
        runtime = Path(RUNTIME_DRAWIO)
        candidates.extend([runtime / "draw.io.exe", runtime / "drawio.exe", runtime / "draw.io"])
    system_binary = shutil.which("drawio")
    if system_binary:
        candidates.append(Path(system_binary))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Draw.io runtime is unavailable; install or bundle draw.io.exe before exporting diagrams")


def _validate_drawio_source(source: str) -> None:
    data = source.encode("utf-8")
    if not source.strip():
        raise ValueError("Draw.io source is required")
    if len(data) > _DRAWIO_SOURCE_MAX_BYTES:
        raise ValueError("Draw.io source exceeds the 2 MB export limit")
    lowered = source.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("Draw.io source may not contain DTD or entity declarations")
    if any(value in lowered for value in ("http://", "https://", "file://", "\\\\")):
        raise ValueError("Draw.io source may not contain external URI or file references")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise ValueError(f"Draw.io source is not valid XML: {error}") from error
    if root.tag.rsplit("}", 1)[-1] not in {"mxfile", "mxGraphModel"}:
        raise ValueError("Draw.io source root must be mxfile or mxGraphModel")


async def _drawio_process(command: list[str], workspace: Path, timeout: float = 90) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill(); await process.wait()
        return -1, "", f"Draw.io timed out after {timeout}s"
    return process.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _validate_drawio_output(workspace: Path, output: Path, output_format: str) -> dict:
    if not output.is_file() or output.stat().st_size == 0:
        raise ValueError("Draw.io did not create a non-empty output artifact")
    if output_format == "png":
        value = _image_audit_entry(workspace, output)
        if value["status"] != "valid":
            raise ValueError(value.get("failure_reason", "Generated PNG failed image validation"))
        return value
    raw = output.read_bytes()
    if output_format == "pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Draw.io output is not a valid PDF header")
    elif output_format == "svg":
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as error:
            raise ValueError(f"Draw.io SVG is invalid XML: {error}") from error
        if root.tag.rsplit("}", 1)[-1].casefold() != "svg":
            raise ValueError("Draw.io output is not an SVG root element")
    return _artifact_metadata(workspace, output)


async def drawio_export(wf_id: str, source: str, output_format: str = "pdf") -> dict:
    """Export Draw.io XML with the bundled CLI and persist exact provenance."""
    output_format = output_format.casefold().strip()
    if output_format not in _DRAWIO_FORMATS:
        raise ValueError("Draw.io format must be png, pdf, or svg")
    _validate_drawio_source(source)
    executable = _drawio_executable()
    workspace = _workspace(wf_id)
    run_id = uuid.uuid4().hex
    artifact_dir = workspace / "figures" / "drawio"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_path = artifact_dir / f"{run_id}.drawio"
    output_path = artifact_dir / f"{run_id}.{output_format}"
    source_path.write_text(source, encoding="utf-8", newline="\n")
    started = datetime.now(timezone.utc).isoformat()
    command = [str(executable), "--export", "--format", output_format]
    if output_format == "png":
        command.extend(["--scale", "2"])
    command.extend(["--output", str(output_path), str(source_path)])
    returncode, stdout, stderr = await _drawio_process(command, workspace)
    outputs = []
    failure_reason = None
    try:
        if returncode != 0:
            raise ValueError(f"Draw.io exited with code {returncode}")
        outputs = [_validate_drawio_output(workspace, output_path, output_format)]
        status = "completed"
    except ValueError as error:
        status = "failed"
        failure_reason = str(error)
    manifest = {
        "format_version": "1.0",
        "operation": "drawio_export",
        "id": run_id,
        "status": status,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": _artifact_metadata(workspace, source_path),
        "output_format": output_format,
        "runtime": {"executable": executable.name, "sha256": _file_sha256(executable)},
        "command": [executable.name, "--export", "--format", output_format, "--output", output_path.name, source_path.name],
        "outputs": outputs,
        "returncode": returncode,
        "stdout": stdout[-12000:],
        "stderr": stderr[-12000:],
        "failure_reason": failure_reason,
    }
    manifest_ref = _write_operation_manifest(workspace, ".drawio_exports", manifest)
    return {"status": status, "source": manifest["source"], "outputs": outputs, "manifest": manifest_ref, "stdout": manifest["stdout"], "stderr": manifest["stderr"], "failure_reason": failure_reason}


def _mermaid_library_path() -> Path:
    """Locate the offline mermaid runtime shipped with the product skills."""
    candidates = [
        Path(SKILLS_DIR) / "patent-build" / "tools" / "mermaid.min.js",
        Path(TOOLS_DIR).parent / "skills" / "patent-build" / "tools" / "mermaid.min.js",
        Path(__file__).resolve().parents[1] / "skills" / "patent-build" / "tools" / "mermaid.min.js",
    ]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 1000:
            return candidate.resolve()
    raise RuntimeError("Offline mermaid runtime is unavailable; ship skills/patent-build/tools/mermaid.min.js")


def _chromium_family_browser() -> Path:
    """Resolve a local Chromium-family browser for offline diagram rendering."""
    override = os.environ.get("VIBE_CHROMIUM", "").strip() or os.environ.get("EDGE_PATH", "").strip() or os.environ.get("CHROME_PATH", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    for name in ("msedge", "msedge.exe", "chrome", "chrome.exe", "chromium", "google-chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        suffixes = (
            Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
            Path("Google") / "Chrome" / "Application" / "chrome.exe",
        )
        for root in roots:
            if not root:
                continue
            for suffix in suffixes:
                candidates.append(Path(root) / suffix)
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    raise RuntimeError("No local Chromium-family browser is available for mermaid export")


def _validate_mermaid_source(source: str) -> str:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Mermaid source is required")
    data = source.encode("utf-8")
    if len(data) > _MERMAID_SOURCE_MAX_BYTES:
        raise ValueError("Mermaid source exceeds the 512 KiB export limit")
    lowered = source.casefold()
    if any(token in lowered for token in ("<script", "javascript:", "file://", "http://", "https://", "\\\\")):
        raise ValueError("Mermaid source may not contain scripts or external references")
    return source.strip() + ("\n" if not source.endswith("\n") else "")


def _mermaid_html_document(source: str, library: Path) -> str:
    escaped = (
        source.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    library_uri = library.resolve().as_uri()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <style>
    html, body {{ margin: 0; padding: 16px; background: #ffffff; }}
    #diagram {{ display: inline-block; }}
  </style>
</head>
<body>
  <div id="diagram" class="mermaid">{escaped}</div>
  <script src="{library_uri}"></script>
  <script>
    mermaid.initialize({{ startOnLoad: false, securityLevel: "strict", theme: "neutral" }});
    mermaid.run({{ nodes: [document.getElementById("diagram")] }}).then(function () {{
      document.body.setAttribute("data-ready", "1");
    }}).catch(function (error) {{
      document.body.setAttribute("data-error", String(error && error.message ? error.message : error));
    }});
  </script>
</body>
</html>
"""


async def _run_browser(command: list[str], timeout: float = 60) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        return -1, "", f"Browser timed out after {timeout}s"
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _extract_svg_from_dom(dom: str) -> str:
    match = re.search(r"(<svg\b[\s\S]*?</svg>)", dom, re.I)
    if not match:
        raise ValueError("Mermaid renderer did not produce an SVG diagram")
    svg = match.group(1).strip()
    if "mermaid" not in svg.casefold() and "viewbox" not in svg.casefold():
        raise ValueError("Mermaid SVG output failed structural validation")
    return svg


async def mermaid_export(wf_id: str, source: str, output_format: str = "svg") -> dict:
    """Render Mermaid offline with a local browser and persist exact provenance."""
    output_format = output_format.casefold().strip()
    if output_format not in _MERMAID_FORMATS:
        raise ValueError("Mermaid format must be png, pdf, or svg")
    source = _validate_mermaid_source(source)
    library = _mermaid_library_path()
    browser = _chromium_family_browser()
    workspace = _workspace(wf_id)
    run_id = uuid.uuid4().hex
    artifact_dir = workspace / "figures" / "mermaid"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_path = artifact_dir / f"{run_id}.mmd"
    html_path = artifact_dir / f"{run_id}.html"
    output_path = artifact_dir / f"{run_id}.{output_format}"
    source_path.write_text(source, encoding="utf-8", newline="\n")
    html_path.write_text(_mermaid_html_document(source, library), encoding="utf-8", newline="\n")
    started = datetime.now(timezone.utc).isoformat()
    html_uri = html_path.resolve().as_uri()
    command: list[str]
    stdout = ""
    stderr = ""
    returncode = 0
    outputs: list[dict] = []
    failure_reason = None
    try:
        if output_format == "svg":
            command = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--virtual-time-budget=15000",
                "--dump-dom",
                html_uri,
            ]
            returncode, stdout, stderr = await _run_browser(command)
            if returncode != 0:
                raise ValueError(f"Browser exited with code {returncode}")
            if "data-error=" in stdout:
                raise ValueError("Mermaid failed to parse the supplied diagram source")
            if 'data-ready="1"' not in stdout and "data-ready='1'" not in stdout:
                raise ValueError("Mermaid renderer did not reach a ready state")
            svg = _extract_svg_from_dom(stdout)
            output_path.write_text(svg, encoding="utf-8", newline="\n")
        elif output_format == "png":
            command = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--hide-scrollbars",
                "--window-size=1600,1200",
                "--virtual-time-budget=15000",
                f"--screenshot={output_path}",
                html_uri,
            ]
            returncode, stdout, stderr = await _run_browser(command)
            if returncode != 0:
                raise ValueError(f"Browser exited with code {returncode}")
            if not output_path.is_file() or output_path.stat().st_size < 100:
                raise ValueError("Browser did not create a non-empty PNG artifact")
        else:
            command = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--virtual-time-budget=15000",
                f"--print-to-pdf={output_path}",
                html_uri,
            ]
            returncode, stdout, stderr = await _run_browser(command)
            if returncode != 0:
                raise ValueError(f"Browser exited with code {returncode}")
            raw = output_path.read_bytes() if output_path.is_file() else b""
            if not raw.startswith(b"%PDF-"):
                raise ValueError("Browser did not create a valid PDF artifact")
        if output_format == "png":
            outputs = [_image_audit_entry(workspace, output_path)]
            if outputs[0].get("status") != "valid":
                raise ValueError(outputs[0].get("failure_reason", "Generated PNG failed image validation"))
        else:
            outputs = [{
                **_artifact_metadata(workspace, output_path),
                "status": "valid",
                "format": output_format,
            }]
        status = "completed"
    except Exception as error:  # noqa: BLE001 - convert to durable failed artifact
        status = "failed"
        failure_reason = str(error)
        command = locals().get("command") or [str(browser)]
    manifest = {
        "format_version": "1.0",
        "operation": "mermaid_export",
        "id": run_id,
        "status": status,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": _artifact_metadata(workspace, source_path),
        "html": _artifact_metadata(workspace, html_path),
        "output_format": output_format,
        "runtime": {
            "browser": browser.name,
            "browser_sha256": _file_sha256(browser),
            "mermaid_library": library.name,
            "mermaid_library_sha256": _file_sha256(library),
            "offline": True,
        },
        "command": [Path(part).name if i == 0 else part for i, part in enumerate(command)],
        "outputs": outputs,
        "returncode": returncode,
        "stdout": stdout[-12000:],
        "stderr": stderr[-12000:],
        "failure_reason": failure_reason,
    }
    manifest_ref = _write_operation_manifest(workspace, ".mermaid_exports", manifest)
    return {
        "status": status,
        "source": manifest["source"],
        "outputs": outputs,
        "manifest": manifest_ref,
        "stdout": manifest["stdout"],
        "stderr": manifest["stderr"],
        "failure_reason": failure_reason,
    }


async def _pandoc(command: list[str], workspace: Path, timeout: float = 90) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        return -1, "", f"Pandoc timed out after {timeout}s"
    return process.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _compile_source(workspace: Path, source_md: str) -> Path:
    if source_md:
        if len(source_md.encode("utf-8")) > 2_000_000:
            raise ValueError("Markdown source exceeds the 2 MB editor compilation limit")
        source = workspace / "paper" / "main.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(source_md, encoding="utf-8", newline="\n")
        return source
    for relative in ("paper/main.md", "paper/main.tex", "COURSE_PAPER.md", "COURSE_REPORT.md", "REPORT.md", "RESULTS.md", "MODELING_REPORT.md"):
        candidate = _workspace_path(workspace.name, relative)
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No Markdown or LaTeX source exists in the workspace")


async def compile_paper(wf_id: str, source_md: str = "") -> dict:
    """Compile a workspace paper with the bundled Pandoc runtime.

    PDF is intentionally not faked when TeX is absent.  DOCX and standalone
    HTML are durable, inspectable compilation artifacts available in every
    shipped runtime that contains Pandoc.
"""
    workspace = _workspace(wf_id)
    source = _compile_source(workspace, source_md)
    pandoc = Path(PANDOC_BIN or shutil.which("pandoc") or "")
    if not pandoc.is_file():
        raise RuntimeError("Pandoc runtime is unavailable; DOCX and HTML compilation cannot run")
    input_format = "latex" if source.suffix.casefold() == ".tex" else "markdown"
    docx = source.with_suffix(".docx")
    html_output = source.with_suffix(".html")
    for output in (docx, html_output):
        output.unlink(missing_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    common = [str(pandoc), "--standalone", "--resource-path", str(workspace), "-f", input_format, str(source)]
    returncode, stdout, stderr = await _pandoc([*common, "-t", "docx", "-o", str(docx)], workspace)
    html_returncode, html_stdout, html_stderr = 0, "", ""
    if returncode == 0 and docx.is_file() and docx.stat().st_size > 0:
        html_returncode, html_stdout, html_stderr = await _pandoc([*common, "-t", "html5", "-o", str(html_output)], workspace)
    status = "completed" if returncode == 0 and html_returncode == 0 and docx.is_file() and html_output.is_file() else "failed"
    outputs = [_artifact_metadata(workspace, item) for item in (docx, html_output) if item.is_file() and item.stat().st_size > 0]
    run_id = uuid.uuid4().hex
    manifest = {
        "format_version": "1.0",
        "operation": "pandoc_compile",
        "id": run_id,
        "status": status,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": _artifact_metadata(workspace, source),
        "input_format": input_format,
        "runtime": {"executable": pandoc.name, "sha256": hashlib.sha256(pandoc.read_bytes()).hexdigest()},
        "outputs": outputs,
        "docx_returncode": returncode,
        "html_returncode": html_returncode,
        "stdout": (stdout + html_stdout)[-12000:],
        "stderr": (stderr + html_stderr)[-12000:],
    }
    audit_dir = workspace / ".editor_compile"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audit_dir / f"{run_id}.json"
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_path.write_bytes(raw)
    response = {
        "status": status,
        "source": manifest["source"],
        "outputs": outputs,
        "manifest": {"path": manifest_path.relative_to(workspace).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()},
        "stdout": manifest["stdout"],
        "stderr": manifest["stderr"],
    }
    if status == "failed":
        response["failure_reason"] = "Pandoc did not produce both DOCX and standalone HTML artifacts"
    return response


def docx_status(wf_id: str) -> dict:
    workspace = _workspace(wf_id)
    documents = []
    for candidate in sorted(workspace.rglob("*.docx")):
        if any(part.startswith(".") for part in candidate.relative_to(workspace).parts):
            continue
        documents.append(_artifact_metadata(workspace, candidate))
    manifests = sorted((workspace / ".editor_compile").glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True) if (workspace / ".editor_compile").is_dir() else []
    latest = None
    if manifests:
        try:
            latest = json.loads(manifests[0].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            latest = {"status": "failed", "failure_reason": "Latest editor compile manifest is invalid JSON"}
    return {"status": "available" if documents else "missing", "documents": documents, "latest_compile": latest}


def _script_interpreter(language: str) -> list[str]:
    """Resolve a concrete interpreter, preferring the bundled desktop runtime."""
    language = str(language or "python").lower().strip()
    if language == "python":
        candidates: list[str] = []
        if RUNTIME_PYTHON and Path(RUNTIME_PYTHON).is_file():
            candidates.append(str(Path(RUNTIME_PYTHON).resolve()))
        for name in ("python", "python3"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        candidates.append(sys.executable)
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return [candidate]
        raise RuntimeError("No Python interpreter is available for run-script")
    if language == "bash":
        for name in ("bash", "sh"):
            found = shutil.which(name)
            if found:
                return [found]
        raise RuntimeError("No bash interpreter is available for run-script")
    if language == "node":
        from config import RUNTIME_NODE

        candidates = []
        if RUNTIME_NODE and Path(RUNTIME_NODE).is_file():
            candidates.append(str(Path(RUNTIME_NODE).resolve()))
        found = shutil.which("node")
        if found:
            candidates.append(found)
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return [candidate]
        raise RuntimeError("No Node interpreter is available for run-script")
    raise ValueError(f"Unsupported language: {language}")


async def run_script(wf_id: str, script: str, language: str = "python") -> dict:
    """Run an allowlisted script in the workspace with bounded resources."""
    workspace = _workspace_root(wf_id)
    if not isinstance(script, str) or not script.strip():
        raise ValueError("Script must not be empty")
    if len(script.encode("utf-8")) > 512 * 1024:
        raise ValueError("Script exceeds the 512 KiB limit")
    language = str(language or "python").lower().strip()
    if language not in {"python", "bash", "node"}:
        raise ValueError(f"Unsupported language: {language}")
    extension = {"python": "py", "bash": "sh", "node": "js"}[language]
    script_path = workspace / f"_run_script_{uuid.uuid4().hex}.{extension}"
    script_path.write_text(script, encoding="utf-8")
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        from services.process_supervisor import ProcessSupervisor

        try:
            interpreter = _script_interpreter(language)
        except RuntimeError as error:
            raise RuntimeError(str(error)) from error
        command = [*interpreter, str(script_path)]
        allowed = {Path(command[0]).name}
        supervisor = ProcessSupervisor(workspace, allowed_commands=allowed)
        result = await supervisor.run(f"editor-script-{uuid.uuid4().hex}", command, workspace, timeout=60)
        result.update({"success": result["returncode"] == 0, "language": language,
                       "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat()})
        # Keep an immutable, secret-free execution record beside the workspace.
        audit_dir = workspace / ".editor_runs"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit = {"operation": "run_script", "language": language,
                 "script_sha256": _content_hash(script), "command": [Path(command[0]).name, "<script>"],
                 "result": {"returncode": result["returncode"], "stdout_sha256": _content_hash(result["stdout"]),
                            "stderr_sha256": _content_hash(result["stderr"]), "success": result["success"]},
                 "started_at": started_at, "finished_at": result["finished_at"]}
        audit_path = audit_dir / f"{uuid.uuid4().hex}.json"
        raw = json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8")
        audit_path.write_bytes(raw)
        result["audit"] = {"path": audit_path.relative_to(workspace).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
        return result
    finally:
        script_path.unlink(missing_ok=True)


def get_chat_history(wf_id: str) -> list:
    """Get chat history."""
    workspace = _workspace_root(wf_id)
    history_path = workspace / "_chat_history.json"
    if history_path.exists():
        return json.loads(history_path.read_text(encoding="utf-8"))
    return []


def clear_chat_history(wf_id: str) -> None:
    """Clear chat history."""
    workspace = _workspace_root(wf_id)
    history_path = workspace / "_chat_history.json"
    if history_path.exists():
        history_path.unlink()


def _parse_agent_payload(response: str) -> dict:
    """Parse a model response into the staged-edit JSON schema."""
    text = (response or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:].lstrip()
    # Tolerate leading prose before the first JSON object.
    if text and not text.lstrip().startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Agent returned invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise RuntimeError("Agent response must contain a files array")
    return payload


def _stage_proposals_from_payload(wf_id: str, payload: dict) -> dict:
    """Materialize reviewable proposals from a validated agent payload."""
    proposals = []
    for entry in payload["files"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("content"), str)
        ):
            raise RuntimeError("Agent returned an invalid file proposal")
        path = entry["path"].replace("\\", "/").lstrip("/")
        if not path or ".." in Path(path).parts:
            raise RuntimeError("Agent proposed an invalid path")
        # Bound path resolution; raises ValueError on traversal.
        target = _workspace_path(wf_id, path)
        if path.startswith(".") or any(part.startswith(".") for part in Path(path).parts):
            raise RuntimeError("Agent proposed a hidden path")
        current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        if current == entry["content"]:
            continue
        proposals.append({
            "path": path,
            "content": entry["content"],
            "base_hash": _content_hash(current),
            "proposed_diff": "".join(
                difflib.unified_diff(
                    current.splitlines(True),
                    entry["content"].splitlines(True),
                    fromfile=path,
                    tofile=path,
                )
            ),
            "status": "staged",
        })
    if not proposals:
        return {
            "status": "completed",
            "summary": str(payload.get("summary", "No changes proposed")),
            "changed_files": [],
            "proposals": [],
        }
    state = _load_agent_state(wf_id)
    state["proposals"] = [{"id": str(uuid.uuid4()), **proposal} for proposal in proposals[:20]]
    state["summary"] = str(payload.get("summary", ""))
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_agent_state(wf_id, state)
    return {
        "status": "staged",
        "summary": str(payload.get("summary", "")),
        "task_id": state["proposals"][0]["id"],
        "changed_files": [item["path"] for item in state["proposals"]],
        "proposals": state["proposals"],
    }


async def ai_agent_endpoint(wf_id: str, message: str) -> dict:
    """Ask the configured editor model for a structured, reviewable edit proposal."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must not be empty")
    from services.llm_client import call_llm, get_all_settings

    settings = await get_all_settings()
    if not settings.get("editor_ai_api_key", "").strip() or not settings.get("editor_ai_base_url", "").strip():
        raise RuntimeError("agent_provider_unavailable")
    workspace = _workspace_root(wf_id)
    if not workspace.exists():
        raise FileNotFoundError(f"Workspace not found: {wf_id}")
    files = list_files(wf_id)
    file_blocks = []
    for item in files[:80]:
        path = item["path"]
        if item["size"] > 256 * 1024:
            continue
        try:
            content = read_file(wf_id, path)
        except (FileNotFoundError, ValueError):
            continue
        file_blocks.append(f"FILE: {path}\n```\n{content[:12000]}\n```")
    prompt = f"""You are a workspace editing agent. Return ONLY valid JSON, no markdown fences.
Schema: {{\"summary\": string, \"files\": [{{\"path\": string, \"content\": string}}]}}
The files array must contain complete replacement contents for files that should change. Do not include unchanged files.
Paths are relative to the workspace and must not contain '..', absolute prefixes, or hidden/system directories.
User request: {message}

Workspace files:\n{chr(10).join(file_blocks)}"""
    response = await call_llm("editor_ai", prompt, timeout=300)
    payload = _parse_agent_payload(response)
    return _stage_proposals_from_payload(wf_id, payload)


async def stage_agent_proposal(wf_id: str, path: str, content: str) -> dict:
    """Stage a supplied edit, binding it to the current file hash and diff."""
    target = _workspace_path(wf_id, path)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    current = target.read_text(encoding="utf-8", errors="replace")
    base_hash = _content_hash(current)
    proposal_id = str(uuid.uuid4())
    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True), content.splitlines(keepends=True),
        fromfile=path, tofile=path,
    ))
    state = _load_agent_state(wf_id)
    state["proposals"] = [{
        "id": proposal_id,
        "path": path,
        "base_hash": base_hash,
        "content": content,
        "proposed_diff": diff,
        "status": "staged",
    }]
    _save_agent_state(wf_id, state)
    return {"task_id": proposal_id, "status": "staged", "base_hash": base_hash,
            "proposed_diff": diff, "changed_files": [path]}


async def ai_agent_apply(wf_id: str, files: list) -> dict:
    state = _load_agent_state(wf_id)
    proposals = state.get("proposals", [])
    if not proposals:
        raise ValueError("No staged agent proposal")
    proposal = proposals[0]
    if files and proposal["path"] not in files:
        raise ValueError("Requested files do not match staged proposal")
    target = _workspace_path(wf_id, proposal["path"])
    current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
    if current is None or _content_hash(current) != proposal["base_hash"]:
        raise ValueError("Staged proposal base hash no longer matches")
    backup = _workspace_path(wf_id, Path("_editor_backup") / proposal["path"])
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(current, encoding="utf-8")
    target.write_text(proposal["content"], encoding="utf-8")
    proposal["status"] = "applied"
    _save_agent_state(wf_id, state)
    return {"success": True, "applied": [proposal["path"]], "task_id": proposal["id"]}


async def ai_agent_discard(wf_id: str) -> dict:
    state = _load_agent_state(wf_id)
    state["proposals"] = []
    _save_agent_state(wf_id, state)
    return {"success": True, "discarded": True}


async def ai_agent_undo(wf_id: str) -> dict:
    """Undo auto-applied changes."""
    workspace = _workspace_root(wf_id)
    backup_dir = workspace / "_editor_backup"
    if backup_dir.exists():
        for item in backup_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(backup_dir)
                target = workspace / rel
                shutil.copy2(str(item), str(target))
        shutil.rmtree(str(backup_dir))
    return {"success": True}


async def ai_agent_stop(wf_id: str) -> dict:
    return {"success": True, "stopped": False, "reason": "no_local_agent_process"}


async def ai_agent_check(wf_id: str, log_offset: int = 0) -> dict:
    state = _load_agent_state(wf_id)
    proposals = state.get("proposals", [])
    proposal = proposals[0] if proposals else None
    workspace = _workspace_root(wf_id)
    return {"has_diff": bool(proposal and proposal["status"] == "staged"),
            "has_backup": (workspace / "_editor_backup").exists(),
            "proposal": proposal, "logs": [], "log_offset": log_offset}


async def ai_edit_endpoint(wf_id: str, message: str, current_file: str, current_content: str,
                           workspace_files: list, compile_log: str = "", extra_context: str = "",
                           history: list = None, role: str = "latex", chat_summary: str = "") -> dict:
    """AI edit endpoint with workspace-scoped chat history persistence."""
    # Bound the file path so history cannot be attributed to a traversal target.
    _workspace_path(wf_id, current_file)
    return await ai_edit(
        message,
        current_file,
        current_content,
        workspace_files,
        compile_log,
        extra_context,
        history,
        role,
        chat_summary,
        wf_id=wf_id,
    )
