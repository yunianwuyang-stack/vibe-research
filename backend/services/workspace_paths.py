"""Resolve workflow workspaces from durable DB state, not process constants alone.

Editor, artifacts, recovery, and dual clean user-data roots must all open the
same on-disk tree that `create_new_workflow` recorded.  Falling back to the
process-level WORKSPACES_DIR keeps unit tests that never insert a workflow row
working, while production paths always prefer the persisted absolute directory.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

class WorkspacePathError(ValueError):
    """Raised when a workflow id or path cannot be safely resolved."""


def _active_db_path() -> Path:
    # Read through the config module so tests that rebind config.DB_PATH are honored.
    import config as app_config

    return Path(app_config.DB_PATH)


def _active_workspaces_dir() -> Path:
    import config as app_config

    return Path(app_config.WORKSPACES_DIR).expanduser()


def persisted_workspace_dir(wf_id: str) -> Path | None:
    """Return the durable workspace_dir for a workflow when the ledger has one."""
    if not wf_id or any(sep in wf_id for sep in ("/", "\\", "..")):
        raise WorkspacePathError("Invalid workflow id")
    db_path = _active_db_path()
    if not db_path.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT workspace_dir FROM workflows WHERE id=?",
                (wf_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    raw = str(row[0] or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def resolve_workflow_workspace(
    wf_id: str,
    *,
    require_exists: bool = False,
    fallback_root: Path | None = None,
) -> Path:
    """Resolve the workspace root for a workflow id.

    Preference order:
    1. Absolute workspace_dir recorded when the workflow was created
    2. ``fallback_root / wf_id`` or ``config.WORKSPACES_DIR / wf_id``
    """
    if not wf_id or any(sep in wf_id for sep in ("/", "\\", "..")):
        raise WorkspacePathError("Invalid workflow id")

    persisted = persisted_workspace_dir(wf_id)
    if persisted is not None:
        workspace = persisted.resolve(strict=False)
    else:
        root = (fallback_root or _active_workspaces_dir()).expanduser().resolve(strict=False)
        workspace = (root / wf_id).resolve(strict=False)
        try:
            workspace.relative_to(root)
        except ValueError as exc:
            raise WorkspacePathError("Invalid workspace") from exc

    if require_exists and not workspace.is_dir():
        raise FileNotFoundError(f"Workflow workspace not found: {wf_id}")
    return workspace
