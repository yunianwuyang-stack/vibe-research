"""Workspace-scoped artifact IO with traversal protection and content hashes."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


class ArtifactPathError(ValueError):
    """Raised when an artifact path escapes its workspace."""


def workspace_path(workspace: str | os.PathLike[str], relative_path: str | os.PathLike[str], *, allow_missing: bool = True) -> Path:
    """Resolve a user path and require it to remain under the workspace."""
    root = Path(workspace).expanduser().resolve()
    raw = os.fspath(relative_path)
    if "\x00" in raw:
        raise ArtifactPathError("artifact path contains NUL")
    candidate = Path(raw).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ArtifactPathError("artifact path escapes workspace") from exc
    if not allow_missing and not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


resolve_workspace_path = workspace_path


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


def write_artifact(workspace: str | os.PathLike[str], relative_path: str | os.PathLike[str], data: bytes | str, *, encoding: str = "utf-8", kind: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    path = workspace_path(workspace, relative_path)
    payload = data.encode(encoding) if isinstance(data, str) else bytes(data)
    _atomic_write(path, payload)
    return record_artifact(workspace, path, kind=kind, metadata=metadata)


def read_artifact(workspace: str | os.PathLike[str], relative_path: str | os.PathLike[str]) -> bytes:
    return workspace_path(workspace, relative_path, allow_missing=False).read_bytes()


def record_artifact(workspace: str | os.PathLike[str], path: str | os.PathLike[str], *, kind: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    resolved = workspace_path(root, path, allow_missing=False)
    digest = sha256_file(resolved)
    relative = resolved.relative_to(root).as_posix()
    result: dict[str, Any] = {
        "path": relative,
        "sha256": digest,
        "size": resolved.stat().st_size,
        "kind": kind or (resolved.suffix.lstrip(".") or "file"),
        "status": "verified",
    }
    if metadata:
        result["metadata"] = dict(metadata)
    return result


def manifest(workspace: str | os.PathLike[str], paths: Iterable[str | os.PathLike[str]] | None = None) -> list[dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    selected = (workspace_path(root, item, allow_missing=False) for item in paths) if paths else root.rglob("*")
    records = []
    for path in selected:
        if path.is_file():
            records.append(record_artifact(root, path))
    return sorted(records, key=lambda item: item["path"])
