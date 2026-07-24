"""(docstring)"""
from __future__ import annotations

import logging
import os
import shutil
import json
import tempfile
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import DB_PATH

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    settings: Dict[str, str] = Field(default_factory=dict)


class ModelProfileUpdate(BaseModel):
    provider: str = "openai_responses"
    base_url: str = ""
    model_id: str = Field(min_length=1, max_length=240)
    temperature: float = Field(ge=0, le=2)
    top_p: float = Field(ge=0, le=1)
    max_tokens: int = Field(ge=1, le=32768)
    reasoning_effort: str = ""
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


class DataDirUpdate(BaseModel):
    data_dir: str = Field(min_length=1, max_length=2048)


@router.get("")
async def get_settings():
    """(docstring)"""
    from services.state_store import get_settings_metadata
    return await get_settings_metadata()


@router.put("")
async def update_settings(update: SettingsUpdate):
    """(docstring)"""
    from services.state_store import save_settings
    # The data root has a dedicated validated endpoint and a stable pointer
    # outside SQLite. Ignore the legacy field here so an old renderer cannot
    # create a stale value in whichever database happens to be active.
    values = dict(update.settings)
    values.pop("data_dir", None)
    await save_settings(values)
    return {"ok": True}


def _active_data_root() -> Path:
    configured = os.environ.get("VIBE_USER_DATA_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else DB_PATH.parent.parent.resolve()


@router.get("/data-dir")
async def get_data_dir():
    """Return the active/default roots and the restart-selected location."""
    from services.state_store import get_setting
    active = _active_data_root()
    default_value = os.environ.get("VIBE_DEFAULT_USER_DATA_ROOT", "").strip()
    default = Path(default_value).expanduser().resolve() if default_value else active
    selected = ""
    pointer_value = os.environ.get("VIBE_DATA_POINTER_FILE", "").strip()
    if pointer_value:
        try:
            pointer = json.loads(Path(pointer_value).expanduser().resolve().read_text(encoding="utf-8"))
            candidate = str(pointer.get("data_dir") or "").strip() if pointer.get("schema") == 1 else ""
            if candidate and Path(candidate).expanduser().is_absolute():
                selected = str(Path(candidate).expanduser().resolve())
        except (OSError, ValueError, TypeError):
            log.warning("Ignoring invalid data-directory pointer: %s", pointer_value)
    if not selected and not pointer_value:
        # Compatibility for backend-only/source launches created before the
        # desktop pointer existed. Desktop launches always provide a pointer.
        selected = str(await get_setting("data_dir", "") or "").strip()
    return {
        "data_dir": str(active),
        "default_data_dir": str(default),
        "selected_data_dir": selected or str(active),
        "restart_required": bool(selected and Path(selected).expanduser().resolve() != active),
    }


@router.put("/data-dir")
async def set_data_dir(body: DataDirUpdate):
    """Validate a writable target and atomically write the desktop pointer."""
    raw = body.data_dir.strip()
    target = Path(raw).expanduser()
    if not target.is_absolute():
        raise HTTPException(422, detail="data_dir must be an absolute path")
    target = target.resolve()
    try:
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target, delete=False) as handle:
            probe = Path(handle.name)
            handle.write("vibe-data-dir-write-test")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(422, detail=f"data_dir is not writable: {exc}") from exc

    pointer_value = os.environ.get("VIBE_DATA_POINTER_FILE", "").strip()
    if pointer_value:
        pointer = Path(pointer_value).expanduser().resolve()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temporary = pointer.with_suffix(pointer.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema": 1, "data_dir": str(target)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, pointer)

    if not pointer_value:
        from services.state_store import save_settings
        await save_settings({"data_dir": str(target)})
    active = _active_data_root()
    return {
        "ok": True,
        "data_dir": str(active),
        "selected_data_dir": str(target),
        "restart_required": target != active,
    }


@router.get("/model-profiles")
async def get_model_profiles():
    from services import model_profiles
    return await model_profiles.profiles()


@router.put("/model-profiles/{role}")
async def update_model_profile(role: str, update: ModelProfileUpdate):
    from services import model_profiles
    return await model_profiles.save(role, update.model_dump())


@router.post("/model-profiles/{role}/test")
async def test_model_profile(role: str):
    from services import model_profiles
    from services.llm_client import test_connection
    model_profiles._role_or_404(role)
    return await test_connection(role)


@router.post("/test/{agent}")
async def test_agent_connection(agent: str):
    """(docstring)"""
    from services.llm_client import test_connection
    return await test_connection(agent)


def _detect_cli(setting_key: str, env_key: str, command: str) -> dict:
    """Resolve a user-managed or host-installed Agent CLI path.

    Packaged builds may still ship a separate immutable Codex bundle through
    the runtime manifest.  These settings endpoints only surface an explicit
    override, environment variable, or PATH discovery result so the desktop UI
    can write a durable ``*_bin`` setting without claiming authentication.
    """
    from services.state_store import get_setting

    async def _run() -> dict:
        saved = str(await get_setting(setting_key, "") or "").strip()
        if saved and os.path.isfile(saved):
            return {"detected": True, "path": saved, "source": "settings"}
        configured = str(os.environ.get(env_key, "") or "").strip()
        if configured:
            resolved = configured if os.path.isfile(configured) else shutil.which(configured)
            if resolved:
                return {"detected": True, "path": resolved, "source": "environment"}
        discovered = shutil.which(command)
        if discovered:
            return {"detected": True, "path": discovered, "source": "path"}
        return {"detected": False, "path": None, "source": None}

    return _run()


@router.get("/detect-claude")
async def detect_claude():
    """Locate Claude Code CLI without embedding or redistributing it."""
    return await _detect_cli("claude_bin", "CLAUDE_BIN", "claude")


@router.get("/detect-codex")
async def detect_codex():
    """Locate Codex CLI from settings, environment, or PATH discovery."""
    return await _detect_cli("codex_bin", "CODEX_BIN", "codex")


@router.post("/import-claude-code")
async def import_claude_code_settings():
    """Import Anthropic credentials from the local Claude Code settings file.

    Reads ``~/.claude/settings.json`` (or ``CLAUDE_CODE_SETTINGS_PATH``) and
    stores the key in the encrypted secret store. The response is always
    redacted — raw API keys and base URLs are never returned to the client.
    """
    from services.claude_code_config import import_claude_code_into_secret_store

    try:
        summary = await import_claude_code_into_secret_store(roles=("executor", "reviewer"))
    except Exception as exc:  # pragma: no cover - defensive operator path
        log.exception("Claude Code settings import failed")
        raise HTTPException(status_code=500, detail="import failed") from exc
    return {"ok": True, **summary}
