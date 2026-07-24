"""Read-only runtime capability inventory with explicit failure states."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


CAPABILITIES = {
    "python": "python",
    "node": "node",
    "git": "git",
    "pandoc": "pandoc",
    "drawio": "draw.io",
    "latex": "xelatex",
    "codex": "codex",
    "claude": "claude",
    "reviewer": None,
    "scholar": None,
}


def _version(command: str) -> str:
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0][:200] if result.returncode == 0 and output else ""


def _hash_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _candidate_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        return [os.fspath(value)]
    if isinstance(value, Iterable):
        return [os.fspath(item) for item in value if item]
    return []


def _resolve(candidates: list[str], command: str | None) -> tuple[str | None, str | None]:
    for candidate in candidates:
        expanded = Path(candidate).expanduser()
        if expanded.is_file():
            return str(expanded.resolve()), "configured"
        resolved = shutil.which(candidate)
        if resolved:
            return resolved, "configured"
    resolved = shutil.which(command) if command else None
    return resolved, "path" if resolved else None


def runtime_candidates() -> dict[str, list[str]]:
    """Return configured and bundled candidates without mutating the host."""
    from config import (
        CLAUDE_BIN, CODEX_BIN, PANDOC_BIN, PROJECT_ROOT, RUNTIME_DRAWIO, RUNTIME_NODE,
        RUNTIME_PYTHON, RUNTIME_TEXLIVE, TOOLS_DIR,
    )

    runtime_root = Path(RUNTIME_NODE).parent if RUNTIME_NODE else PROJECT_ROOT / "runtime"
    python_candidates = [str(RUNTIME_PYTHON)] if RUNTIME_PYTHON else [sys.executable]
    node_candidates: list[str] = []
    if RUNTIME_NODE:
        node_root = Path(RUNTIME_NODE)
        node_candidates.extend([str(node_root / "node.exe"), str(node_root / "node")])
    tex_candidates: list[str] = []
    if RUNTIME_TEXLIVE:
        tex_root = Path(RUNTIME_TEXLIVE)
        tex_candidates.extend([
            str(tex_root / "texmfs" / "install" / "miktex" / "bin" / "x64" / "xelatex.exe"),
            str(tex_root / "bin" / "windows" / "xelatex.exe"),
            str(tex_root / "miktex" / "bin" / "x64" / "xelatex.exe"),
        ])
    drawio_candidates: list[str] = []
    if RUNTIME_DRAWIO:
        drawio_root = Path(RUNTIME_DRAWIO)
        drawio_candidates.extend([
            str(drawio_root / "draw.io.exe"), str(drawio_root / "drawio.exe"),
        ])
    return {
        "python": python_candidates,
        "node": node_candidates,
        "git": [
            str(runtime_root / "git" / "cmd" / "git.exe"),
            str(runtime_root / "git" / "bin" / "git.exe"),
        ],
        "pandoc": [str(PANDOC_BIN)] if PANDOC_BIN else [],
        "drawio": drawio_candidates,
        "latex": tex_candidates,
        "codex": [str(CODEX_BIN)] if CODEX_BIN else [],
        "claude": [str(CLAUDE_BIN)] if CLAUDE_BIN else [],
        "reviewer": [str(TOOLS_DIR / "reviewer_client.py")],
        "scholar": [str(TOOLS_DIR / "scholar_fetch.py")],
    }


def build_registry(candidates: Mapping[str, Any] | None = None) -> dict:
    """Probe configured candidates and PATH and return a stable envelope.

    Omitting candidates intentionally preserves host-only discovery for tests
    and low-level callers. Desktop/API callers pass runtime_candidates().
    """
    entries: dict[str, dict[str, Any]] = {}
    for name, command in CAPABILITIES.items():
        configured = _candidate_values(candidates.get(name)) if candidates else []
        path, source = _resolve(configured, command)
        if path:
            file_path = Path(path)
            is_script = command is None
            entries[name] = {
                "status": "available",
                "path": str(file_path),
                "version": "bundled-script" if is_script else (_version(str(file_path)) or None),
                "reason": None,
                "source": source,
                "kind": "script" if is_script else "executable",
                "hash": _hash_file(file_path) if file_path.is_file() else None,
            }
        else:
            entries[name] = {
                "status": "blocked",
                "path": None,
                "version": None,
                "reason": "not_configured_or_not_found",
                "source": None,
                "kind": "script" if command is None else "executable",
                "hash": None,
            }
    return {"schema_version": "1.0", "capabilities": entries}


def require(registry: dict, name: str) -> dict:
    entry = registry["capabilities"].get(name)
    if not entry or entry["status"] != "available":
        reason = entry["reason"] if entry else "unknown"
        raise RuntimeError(f"CAPABILITY_BLOCKED:{name}:{reason}")
    return entry
