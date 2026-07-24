"""(docstring)"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeLayout:
    app_root: Path
    runtime_root: Path | None
    source_mode: bool


class RuntimeLayoutResolver:
    """Resolve portable source and packaged layouts without hard-coded depth."""

    def __init__(self, backend_dir: Path, environ: dict[str, str] | None = None):
        self.backend_dir = backend_dir.resolve()
        self.environ = os.environ if environ is None else environ

    def resolve(self) -> RuntimeLayout:
        override = self.environ.get("VIBE_RUNTIME_ROOT")
        if override:
            runtime = Path(override).expanduser().resolve()
            return RuntimeLayout(self.backend_dir.parent, runtime if runtime.is_dir() else None, False)
        # Development workspaces may sit beside unrelated runtime directories.
        # Only Electron/package launch explicitly opts into the desktop layout.
        desktop = self.environ.get("VIBE_DESKTOP") == "1"
        if desktop:
            app_root = self.backend_dir.parent
            runtime = app_root.parent / "runtime"
            return RuntimeLayout(app_root, runtime if runtime.is_dir() else None, False)
        return RuntimeLayout(self.backend_dir.parent, None, True)


def _is_desktop_mode() -> bool:
    """(docstring)"""
    if os.environ.get("VIBE_DESKTOP", "") == "1":
        return True
    return RuntimeLayoutResolver(Path(__file__).resolve().parent).resolve().runtime_root is not None


def _find_app_dir() -> Path:
    """(docstring)"""
    _here = Path(__file__).resolve().parent
    _app_dir = _here.parent
    _dev_runtime = _here.parent.parent / "desktop" / "runtime"
    if _dev_runtime.is_dir():
        return _here.parent.parent
    return _app_dir


# ============================================================

# Canonical product ledger filename. Older installs may still have a legacy
# SQLite file on disk; migrate once on first open (filename kept only for
# filesystem compatibility with existing user data directories).
PRODUCT_DB_NAME = "vibe.db"
_LEGACY_DB_NAMES = ("aris.db",)


def resolve_product_db_path(db_dir: Path) -> Path:
    """Return the durable SQLite path under *db_dir*, migrating legacy names."""
    db_dir = Path(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    preferred = db_dir / PRODUCT_DB_NAME
    if preferred.is_file():
        return preferred
    for legacy_name in _LEGACY_DB_NAMES:
        legacy = db_dir / legacy_name
        if not legacy.is_file():
            continue
        try:
            legacy.replace(preferred)
            return preferred
        except OSError:
            # File locked or cross-device; keep serving the readable legacy path.
            return legacy
    return preferred


# ============================================================
_LAYOUT = RuntimeLayoutResolver(Path(__file__).resolve().parent).resolve()
IS_DESKTOP = _LAYOUT.runtime_root is not None

if IS_DESKTOP:
    _BACKEND_DIR = Path(__file__).resolve().parent
    _APP_DIR = _LAYOUT.app_root
    _RUNTIME_DIR = _LAYOUT.runtime_root

    if os.environ.get("VIBE_USER_DATA_ROOT"):
        _USER_DATA = Path(os.environ["VIBE_USER_DATA_ROOT"]).expanduser().resolve()
    elif platform.system() == "Windows":
        # Compatibility for direct/backend-only launches. Electron supplies
        # VIBE_USER_DATA_ROOT and therefore uses the canonical branded root.
        _USER_DATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "VibeResearch"
    else:
        _USER_DATA = Path.home() / ".vibe-research"
    _USER_DATA.mkdir(parents=True, exist_ok=True)

    PROJECT_ROOT = _APP_DIR
    SKILLS_DIR = _APP_DIR / "skills"
    TOOLS_DIR = _APP_DIR / "tools"
    TEMPLATES_DIR = _APP_DIR / "templates"
    WORKSPACES_DIR = _USER_DATA / "workspaces"
    DB_PATH = resolve_product_db_path(_USER_DATA / "db")

    RUNTIME_PYTHON = _RUNTIME_DIR / "python" / ("python.exe" if platform.system() == "Windows" else "python")
    _RUNTIME_NODE = _RUNTIME_DIR / "node"
    RUNTIME_NODE = _RUNTIME_NODE
    RUNTIME_TEXLIVE = _RUNTIME_DIR / "texlive"
    RUNTIME_DRAWIO = _RUNTIME_DIR / "draw.io"

    _pandoc_candidates = [_RUNTIME_DIR / "pandoc" / ("pandoc.exe" if platform.system() == "Windows" else "pandoc")]
    PANDOC_BIN = None
    for _p in _pandoc_candidates:
        if _p.exists():
            PANDOC_BIN = str(_p)
            break
    if PANDOC_BIN is None:
        PANDOC_BIN = shutil.which("pandoc")

    _codex_candidates = [
        _RUNTIME_NODE / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe",
        _RUNTIME_NODE / "codex.cmd",
        _RUNTIME_NODE / "codex",
        _RUNTIME_NODE / ".bin" / "codex",
    ]
    _default_codex = os.environ.get("CODEX_BIN", "codex")
    CODEX_BIN = _default_codex
    for _c in _codex_candidates:
        if _c.exists():
            CODEX_BIN = str(_c)
            break

    # Claude Code is never resolved from the packaged runtime.  An explicit
    # environment override (including the saved setting forwarded by the
    # runner) or the user's PATH is the only supported discovery mechanism.
    CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

    FRONTEND_DIST = _APP_DIR / "dist"
else:
    # config.py lives at <repository>/backend/config.py; source mode must
    # remain within that repository even when adjacent worktrees exist.
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    SKILLS_DIR = PROJECT_ROOT / "skills"
    TOOLS_DIR = PROJECT_ROOT / "tools"
    TEMPLATES_DIR = PROJECT_ROOT / "templates"
    # Source mode is self-contained by default. An explicit user-data root still
    # wins so desktop-parity verification and custom install locations can share
    # the same encrypted settings/secrets without flipping VIBE_DESKTOP.
    if os.environ.get("VIBE_USER_DATA_ROOT"):
        _USER_DATA = Path(os.environ["VIBE_USER_DATA_ROOT"]).expanduser().resolve()
        _USER_DATA.mkdir(parents=True, exist_ok=True)
        WORKSPACES_DIR = _USER_DATA / "workspaces"
        DB_PATH = resolve_product_db_path(_USER_DATA / "db")
    else:
        WORKSPACES_DIR = PROJECT_ROOT / "runtime" / "workspaces"
        DB_PATH = resolve_product_db_path(PROJECT_ROOT / "runtime" / "backend")
    CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
    CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
    FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
    RUNTIME_PYTHON = None
    RUNTIME_NODE = None
    RUNTIME_TEXLIVE = None
    RUNTIME_DRAWIO = None
    _RUNTIME_DIR = None
    PANDOC_BIN = shutil.which("pandoc")

WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
API_PORT = int(os.environ.get("API_PORT", "18088"))
